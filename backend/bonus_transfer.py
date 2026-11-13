"""Protected commission workbooks and atomic, latest-export-only status round trips."""
import io
import json
import posixpath
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from xml.etree import ElementTree as ET

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app import app, database, current_user, SystemSetting, audit, commission_data
from backend.bonus_v2 import COMMISSION_FIELDS, save_setting, workbook_bytes

MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
DOCREL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CUSTOM='http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
VT='http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
NS={'m':MAIN}
TRI={'是':True,'否':False,'待确认':None}
COUNTER_KEY='bonus_export_sequence'
LIMIT=10*1024*1024


def latest_key(user):
    return f'bonus_export_latest_{user.id}'


def export_second():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')


def require_kind(kind):
    if kind not in ('sales','market'):
        raise HTTPException(404,'仅销售、市场奖金表支持此导入流程')


def canonical(value):
    if isinstance(value,Decimal):
        if not value.is_finite():
            raise HTTPException(422,'工作簿含有无效数值')
        return {'n':str(Decimal(format(value,'.15g')).normalize())}
    return {'s':str(value).replace('\r\n','\n').replace('\r','\n')}


def parse_xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise HTTPException(422,'工作簿XML包含不允许的声明')
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HTTPException(422,'工作簿XML格式无效') from exc


def literal_text(node):
    if node is None:
        return ''
    return ''.join(t.text or '' for child in node for t in ([child] if child.tag=='{'+MAIN+'}t' else child.findall('m:t',NS) if child.tag=='{'+MAIN+'}r' else []))


def read_workbook(content):
    if len(content)>LIMIT:
        raise HTTPException(413,'工作簿不能超过10MB')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as book:
            infos=book.infolist()
            if len(infos)>500 or any(x.file_size>32*1024*1024 for x in infos) or sum(x.file_size for x in infos)>80*1024*1024 or len({x.filename for x in infos})!=len(infos):
                raise HTTPException(422,'工作簿结构或解压大小超限')
            for info in infos:
                name=info.filename
                if '\\' in name or name.startswith('/') or '..' in name.split('/') or info.flag_bits&1:
                    raise HTTPException(422,'工作簿包路径或加密格式不受支持')
                if 'vbaproject' in name.lower() or name.startswith('xl/externalLinks/'):
                    raise HTTPException(422,'不接受宏或外部链接工作簿')
                if name.endswith('.rels'):
                    relroot=parse_xml(book.read(name))
                    if any(r.get('TargetMode')=='External' for r in relroot):
                        raise HTTPException(422,'不接受外部链接')
            root=parse_xml(book.read('xl/workbook.xml'))
            relations={r.get('Id'):r.get('Target','') for r in parse_xml(book.read('xl/_rels/workbook.xml.rels'))}
            shared=[]
            if 'xl/sharedStrings.xml' in book.namelist():
                # Phonetic/formatting data is not a second cell value.
                shared=[literal_text(item) for item in parse_xml(book.read('xl/sharedStrings.xml'))]
            sheets=[]
            for sheet in root.findall('m:sheets/m:sheet',NS):
                target=relations.get(sheet.get('{'+DOCREL+'}id'))
                if not target:
                    raise HTTPException(422,'工作表关系缺失')
                path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
                if not path.startswith('xl/worksheets/') or not path.endswith('.xml'):
                    raise HTTPException(422,'工作表路径不受支持')
                cells={}
                seen=set()
                data=parse_xml(book.read(path))
                row_number=0
                for row in data.findall('m:sheetData/m:row',NS):
                    row_number=int(row.get('r',row_number+1))
                    if not 1<=row_number<=100001:
                        raise HTTPException(422,'工作表行数超限')
                    col=0
                    for cell in row.findall('m:c',NS):
                        ref=cell.get('r')
                        if ref:
                            match=re.fullmatch(r'([A-Z]+)([1-9]\d*)',ref)
                            if not match or int(match[2])!=row_number:
                                raise HTTPException(422,'单元格坐标无效')
                            col=0
                            for char in match[1]:
                                col=col*26+ord(char)-64
                        else:
                            col+=1
                        if cell.find('m:f',NS) is not None:
                            raise HTTPException(422,'导入单元格不能包含公式')
                        value=cell.find('m:v',NS)
                        kind=cell.get('t','n')
                        if kind=='inlineStr':
                            parsed=literal_text(cell.find('m:is',NS))
                        elif value is None or value.text is None:
                            parsed=''
                        elif kind=='s':
                            parsed=shared[int(value.text)]
                        elif kind in ('str','e','b','d'):
                            if kind!='str':
                                raise HTTPException(422,'不支持错误值、布尔单元格或日期类型，请保留原导出格式')
                            parsed=value.text
                        else:
                            parsed=Decimal(value.text)
                            if not parsed.is_finite():
                                raise HTTPException(422,'工作簿数值无效')
                        if col>19:
                            if parsed!='':
                                raise HTTPException(422,'不能新增S列之后的数据')
                            continue
                        if (row_number,col) in seen:
                            raise HTTPException(422,'单元格坐标重复')
                        seen.add((row_number,col))
                        if parsed!='':
                            cells[(row_number,col)]=parsed
                        if len(seen)>2000000:
                            raise HTTPException(422,'工作簿单元格数量超限')
                last=max((r for r,c in cells),default=0)
                matrix=[[cells.get((r,c),'') for c in range(1,20)] for r in range(1,last+1)]
                sheets.append({'name':sheet.get('name',''),'matrix':matrix})
            meta=None
            if 'docProps/custom.xml' in book.namelist():
                props=parse_xml(book.read('docProps/custom.xml'))
                prop=next((p for p in props if p.get('name')=='BDExport'),None)
                if prop is not None and len(prop):
                    meta=json.loads(prop[0].text or '{}')
            return sheets,meta
    except HTTPException:
        raise
    except (zipfile.BadZipFile,KeyError,ValueError,TypeError,IndexError,InvalidOperation,RuntimeError,OverflowError) as exc:
        raise HTTPException(422,'无法读取有效XLSX，请使用系统导出文件编辑后回传') from exc


def password_hash(text):
    result=0
    for index,char in enumerate(text,1):
        value=ord(char)<<index
        result^=(value&0x7fff)|(value>>15)
    return format(result^len(text)^0xCE4B,'X')


STYLES='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1" applyProtection="1"><alignment horizontal="center" vertical="center" wrapText="1"/><protection locked="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1" applyProtection="1"><alignment horizontal="center" vertical="center" wrapText="1"/><protection locked="0"/></xf>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyAlignment="1" applyProtection="1"><alignment horizontal="center" vertical="center" wrapText="1"/><protection locked="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''


def protected_workbook(rows,meta):
    source=workbook_bytes(rows,COMMISSION_FIELDS)
    output=io.BytesIO()
    protection=password_hash(secrets.token_hex(4))
    with zipfile.ZipFile(io.BytesIO(source)) as original,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as book:
        for name in original.namelist():
            raw=original.read(name)
            if name.startswith('xl/worksheets/'):
                root=parse_xml(raw)
                data=root.find('m:sheetData',NS)
                columns=ET.Element('{'+MAIN+'}cols')
                for minimum,maximum,width,style in [(1,16,18,1),(17,18,15,2),(19,19,48,1)]:
                    ET.SubElement(columns,'{'+MAIN+'}col',{'min':str(minimum),'max':str(maximum),'width':str(width),'customWidth':'1','style':str(style)})
                root.insert(list(root).index(data),columns)
                for r,row in enumerate(data,1):
                    row.set('r',str(r))
                    for col,cell in enumerate(row,1):
                        cell.set('r',chr(64+col)+str(r))
                        cell.set('s','3' if r==1 else '2' if col in (17,18) else '1')
                        if cell.get('t')=='n':
                            value=cell.find('m:v',NS)
                            value.text=format(Decimal(value.text),'.15g')
                ET.SubElement(root,'{'+MAIN+'}sheetProtection',{'sheet':'1','objects':'1','scenarios':'1','formatCells':'1','formatColumns':'1','formatRows':'1','insertColumns':'1','insertRows':'1','deleteColumns':'1','deleteRows':'1','sort':'1','password':protection})
                rules=ET.SubElement(root,'{'+MAIN+'}dataValidations',{'count':'1'})
                validation=ET.SubElement(rules,'{'+MAIN+'}dataValidation',{'type':'list','allowBlank':'0','showErrorMessage':'1','errorStyle':'stop','errorTitle':'状态值不正确','error':'只能选择：是、否、待确认','sqref':f'Q2:R{max(2,len(data))}'})
                ET.SubElement(validation,'{'+MAIN+'}formula1').text='"是,否,待确认"'
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            elif name=='xl/workbook.xml':
                root=parse_xml(raw)
                root.insert(0,ET.Element('{'+MAIN+'}workbookProtection',{'workbookPassword':protection,'lockStructure':'1'}))
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            elif name=='xl/_rels/workbook.xml.rels':
                root=parse_xml(raw)
                ET.SubElement(root,'{'+REL+'}Relationship',{'Id':'rIdStyles','Type':DOCREL+'/styles','Target':'styles.xml'})
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            elif name=='_rels/.rels':
                root=parse_xml(raw)
                ET.SubElement(root,'{'+REL+'}Relationship',{'Id':'rIdCustom','Type':DOCREL+'/custom-properties','Target':'docProps/custom.xml'})
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            elif name=='[Content_Types].xml':
                root=parse_xml(raw)
                namespace='http://schemas.openxmlformats.org/package/2006/content-types'
                ET.SubElement(root,'{'+namespace+'}Override',{'PartName':'/xl/styles.xml','ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'})
                ET.SubElement(root,'{'+namespace+'}Override',{'PartName':'/docProps/custom.xml','ContentType':'application/vnd.openxmlformats-officedocument.custom-properties+xml'})
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            book.writestr(name,raw)
        book.writestr('xl/styles.xml',STYLES)
        root=ET.Element('{'+CUSTOM+'}Properties')
        prop=ET.SubElement(root,'{'+CUSTOM+'}property',{'fmtid':'{D5CDD505-2E9C-101B-9397-08002B2CF9AE}','pid':'2','name':'BDExport'})
        ET.SubElement(prop,'{'+VT+'}lpwstr').text=json.dumps(meta,ensure_ascii=False)
        book.writestr('docProps/custom.xml',ET.tostring(root,encoding='utf-8',xml_declaration=True))
    return output.getvalue()


def export_commission(kind,rows,user,db):
    require_kind(kind)
    for attempt in range(6):
        db.expire_all()
        sequence=db.get(SystemSetting,COUNTER_KEY)
        prior=json.loads(sequence.value) if sequence else {}
        second=export_second()
        number=prior.get('n',0)+1 if prior.get('second')==second else 1
        suffix=f'{second}_v{number}'
        meta={'suffix':suffix,'token':secrets.token_hex(24),'kind':kind,'user_id':user.id}
        content=protected_workbook(rows,meta)
        matrices,_=read_workbook(content)
        grouped={}
        for row in rows:
            grouped.setdefault(row['owner'].strip() or '未归属',[]).append(row)
        snapshots=[]
        for sheet,(_,records) in zip(matrices,sorted(grouped.items())):
            snapshots.append({'name':sheet['name'],'header':[canonical(v) for v in sheet['matrix'][0]],'rows':[
                {'key':row['record_key'],'version':row['version'],'owner':row['owner'],'quarter':row['quarter'],'order_no':row['order_no'],'values':[canonical(v) for v in values]}
                for row,values in zip(records,sheet['matrix'][1:])]})
        if not rows:
            snapshots=[{'name':matrices[0]['name'],'header':[canonical(v) for v in matrices[0]['matrix'][0]],'rows':[]}]
        filename=('销售奖金表' if kind=='sales' else '市场奖金表')+'_'+suffix+'.xlsx'
        latest=db.get(SystemSetting,latest_key(user))
        payload={**meta,'filename':filename,'consumed':False,'sheets':snapshots}
        try:
            save_setting(db,COUNTER_KEY,json.dumps({'second':second,'n':number}),sequence.version if sequence else 0)
            save_setting(db,latest_key(user),json.dumps(payload,ensure_ascii=False),latest.version if latest else 0)
            audit(db,user.username,f'导出{kind}奖金表：{len(rows)}行；版本{suffix}')
            db.commit()
            return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename=\"{kind}_{suffix}.xlsx\"; filename*=UTF-8''{quote(filename)}",'X-Export-Version':suffix})
        except HTTPException as exc:
            db.rollback()
            if exc.status_code!=409 or attempt==5:
                raise
    raise HTTPException(409,'并发导出繁忙，请重试')


def validate_import(kind,filename,content,user,db):
    require_kind(kind)
    latest=db.get(SystemSetting,latest_key(user),populate_existing=True)
    if not latest:
        raise HTTPException(409,'请先用当前账号导出销售或市场奖金表')
    expected=json.loads(latest.value)
    match=re.search(r'_(\d{8}-\d{6}_v[1-9]\d*)\.xlsx$',filename,re.I)
    if not match or match[1]!=expected['suffix']:
        raise HTTPException(409,'文件版本不是当前账号最后一次导出版本：'+expected['suffix'])
    if expected['kind']!=kind:
        raise HTTPException(409,'文件类型与最后一次导出不一致，请选择对应奖金表')
    if expected['consumed']:
        raise HTTPException(409,'此版本已经导入，请重新导出后再修改')
    sheets,meta=read_workbook(content)
    if not isinstance(meta,dict) or any(meta.get(k)!=expected[k] for k in ('suffix','token','kind','user_id')):
        raise HTTPException(409,'文件内部版本标识不匹配，不能通过改名回传旧文件或其他用户文件')
    if len(sheets)!=len(expected['sheets']) or {s['name'] for s in sheets}!={s['name'] for s in expected['sheets']}:
        raise HTTPException(422,'工作表名称或数量已变化，请保留原导出结构')
    current=commission_data(page=1,page_size=1000000,search='',quarter='',owner='',category=kind,user=user,db=db)['rows']
    current_by_key={r['record_key']:r for r in current}
    current_matrices,_=read_workbook(protected_workbook(current,{}))
    current_grouped={}
    for row in current:
        current_grouped.setdefault(row['owner'].strip() or '未归属',[]).append(row)
    current_values={}
    for sheet,(_,records) in zip(current_matrices,sorted(current_grouped.items())):
        current_values.update({row['record_key']:[canonical(v) for v in values] for row,values in zip(records,sheet['matrix'][1:])})
    supplied={s['name']:s['matrix'] for s in sheets}
    changes=[]
    for sheet in expected['sheets']:
        matrix=supplied[sheet['name']]
        if len(matrix)!=len(sheet['rows'])+1 or [canonical(v) for v in matrix[0]]!=sheet['header']:
            raise HTTPException(422,'表头或数据行数被修改，不能新增、删除或移动行')
        for ordinal,(snapshot,values) in enumerate(zip(sheet['rows'],matrix[1:]),2):
            row=current_by_key.get(snapshot['key'])
            if not row or row['version']!=snapshot['version']:
                raise HTTPException(409,f'{sheet["name"]}第{ordinal}行已变化或超出权限，请重新导出')
            for col in [*range(16),18]:
                if canonical(values[col])!=snapshot['values'][col]:
                    raise HTTPException(422,f'{sheet["name"]}第{ordinal}行{chr(65+col)}列为只读，不能修改')
                if current_values[snapshot['key']][col]!=snapshot['values'][col]:
                    raise HTTPException(409,f'{sheet["name"]}第{ordinal}行源数据或公式结果已更新，请重新导出')
            if any(not isinstance(values[col],str) or values[col] not in TRI for col in (16,17)):
                raise HTTPException(422,f'{sheet["name"]}第{ordinal}行状态只能是：是、否、待确认，不可留空')
            after={'is_paid':TRI[values[16]],'is_refunded':TRI[values[17]]}
            before={key:row[key] for key in after}
            if after!=before:
                changes.append({'key':snapshot['key'],'version':snapshot['version'],'owner':snapshot['owner'],'quarter':snapshot['quarter'],'order_no':snapshot['order_no'],'before':before,'after':after})
    return latest,expected,changes


async def request_file(request):
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>LIMIT:
            raise HTTPException(413,'工作簿不能超过10MB')
    return bytes(content)


def preview_result(expected,changes):
    return {'suffix':expected['suffix'],'filename':expected['filename'],'total':sum(len(s['rows']) for s in expected['sheets']),'changed_count':len(changes),
            'rows':[{k:v for k,v in row.items() if k not in ('key','version')} for row in changes[:50]]}


@app.get('/api/bonus-import/latest')
def latest_export(user=Depends(current_user),db:Session=Depends(database)):
    setting=db.get(SystemSetting,latest_key(user))
    if not setting:
        return {'exists':False}
    payload=json.loads(setting.value)
    return {'exists':True,**{k:payload[k] for k in ('suffix','filename','kind','consumed')}}


@app.post('/api/bonus-import/{kind}/preview')
async def preview_bonus_import(kind:str,filename:str,request:Request,user=Depends(current_user),db:Session=Depends(database)):
    _,expected,changes=validate_import(kind,filename,await request_file(request),user,db)
    return preview_result(expected,changes)


@app.post('/api/bonus-import/{kind}')
async def commit_bonus_import(kind:str,filename:str,request:Request,user=Depends(current_user),db:Session=Depends(database)):
    latest,expected,changes=validate_import(kind,filename,await request_file(request),user,db)
    # Validate every row first. The latest-version CAS and every status update share one transaction.
    version=latest.version
    save_setting(db,latest_key(user),json.dumps({**expected,'consumed':True},ensure_ascii=False),version)
    for row in changes:
        previous=db.get(SystemSetting,row['key'])
        payload=json.loads(previous.value) if previous else {}
        save_setting(db,row['key'],json.dumps({**payload,**row['after']},ensure_ascii=False),row['version'])
    audit(db,user.username,f'导入{kind}奖金状态：版本{expected["suffix"]}；{len(changes)}行变化')
    db.commit()
    return {'ok':True,**preview_result(expected,changes)}
