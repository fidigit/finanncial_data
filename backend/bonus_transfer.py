"""Protected commission workbooks and atomic, latest-export-only status round trips."""
import csv
import io
import json
import posixpath
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import quote
from xml.etree import ElementTree as ET

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import app, database, current_user, SystemSetting, audit, admin, commission_data, commission_snapshot
from backend.bonus_v2 import COMMISSION_FIELDS, MEETING_FIELDS, meeting_rows, named_workbook_bytes, save_setting
from backend.commission_data import refund_key
from backend.bonus_config import all_settings, target_rows
from backend.bonus_summary import (
    SUMMARY_NAME, add_summary_styles, build_summary, meeting_quarter, style_summary_sheet,
)

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
    if kind != 'all':
        raise HTTPException(404,'请使用统一奖金明细回传入口')


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


def read_workbook(content, *, max_columns=20):
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
                        if col > max_columns:
                            if parsed!='':
                                raise HTTPException(422, '工作表超出允许的列数')
                            continue
                        if (row_number,col) in seen:
                            raise HTTPException(422,'单元格坐标重复')
                        seen.add((row_number,col))
                        if parsed!='':
                            cells[(row_number,col)]=parsed
                        if len(seen)>2000000:
                            raise HTTPException(422,'工作簿单元格数量超限')
                last=max((r for r,c in cells),default=0)
                width=max((c for r,c in cells),default=0)
                if last * width > 2000000:
                    raise HTTPException(422, '工作簿单元格数量超限')
                matrix=[[cells.get((r,c),'') for c in range(1,width+1)] for r in range(1,last+1)]
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


def protected_workbook(worksheets,meta):
    tag = lambda name: '{' + MAIN + '}' + name
    source = named_workbook_bytes((name, rows, fields) for _, name, rows, fields in worksheets)
    output=io.BytesIO()
    protection=password_hash(secrets.token_hex(4))
    with zipfile.ZipFile(io.BytesIO(source)) as original,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as book:
        for name in original.namelist():
            raw=original.read(name)
            if name.startswith('xl/worksheets/'):
                root=parse_xml(raw)
                data=root.find('m:sheetData',NS)
                index = int(re.search(r'sheet(\d+)\.xml$', name)[1]) - 1
                kind, _, records, fields = worksheets[index]
                if kind == 'summary':
                    merges = style_summary_sheet(root, data, records, tag)
                else:
                    columns=ET.Element('{'+MAIN+'}cols')
                    editable = next(i for i, (key, _) in enumerate(fields, 1) if key == 'is_paid')
                    last_column = chr(64 + len(fields))
                    for col, (key, _) in enumerate(fields, 1):
                        width = 48 if key in ('note', 'action_note', 'follow_up') else 42 if key == 'order_no' else 18
                        ET.SubElement(columns, '{'+MAIN+'}col', {'min':str(col),'max':str(col),'width':str(width),
                            'customWidth':'1','style':'2' if col == editable else '1'})
                    root.insert(list(root).index(data),columns)
                    for r,row in enumerate(data,1):
                        row.set('r',str(r))
                        for col,cell in enumerate(row,1):
                            cell.set('r',chr(64+col)+str(r))
                            cell.set('s','3' if r==1 else '2' if col == editable else '1')
                            if cell.get('t')=='n':
                                value=cell.find('m:v',NS)
                                value.text=format(Decimal(value.text),'.15g')
                ET.SubElement(root,'{'+MAIN+'}sheetProtection',{'sheet':'1','objects':'1','scenarios':'1','formatCells':'1','formatColumns':'1','formatRows':'1','insertColumns':'1','insertRows':'1','deleteColumns':'1','deleteRows':'1','sort':'1','autoFilter':'0','selectLockedCells':'0','selectUnlockedCells':'0','password':protection})
                if kind == 'summary':
                    if len(merges):
                        root.append(merges)
                else:
                    ET.SubElement(root,'{'+MAIN+'}autoFilter',{'ref':f'A1:{last_column}{len(data)}'})
                    rules=ET.SubElement(root,'{'+MAIN+'}dataValidations',{'count':'1'})
                    validation=ET.SubElement(rules,'{'+MAIN+'}dataValidation',{'type':'list','allowBlank':'0','showErrorMessage':'1','errorStyle':'stop','errorTitle':'状态值不正确','error':'只能选择：是、否、待确认','sqref':f'{chr(64+editable)}2:{chr(64+editable)}{max(2,len(data))}'})
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
        book.writestr('xl/styles.xml', add_summary_styles(STYLES, tag) if worksheets[0][0] == 'summary' else STYLES)
        root=ET.Element('{'+CUSTOM+'}Properties')
        prop=ET.SubElement(root,'{'+CUSTOM+'}property',{'fmtid':'{D5CDD505-2E9C-101B-9397-08002B2CF9AE}','pid':'2','name':'BDExport'})
        ET.SubElement(prop,'{'+VT+'}lpwstr').text=json.dumps(meta,ensure_ascii=False)
        book.writestr('docProps/custom.xml',ET.tostring(root,encoding='utf-8',xml_declaration=True))
    return output.getvalue()


def group_worksheets(data):
    fields = COMMISSION_FIELDS + [('order_no', '订单id')]
    for kind, prefix in (('sales', '销售-'), ('market', '市场-')):
        groups = {}
        for row in data[kind]:
            groups.setdefault(row['owner'].strip() or '未归属', []).append(row)
        for owner, rows in sorted(groups.items()):
            yield kind, prefix + owner, rows, fields
    yield 'meetings', '会议', data['meetings'], MEETING_FIELDS


def bonus_rows(db, user, search='', quarter='', owner=''):
    data = {kind: commission_data(page=1, page_size=1000000, search=search,
                                  quarter=quarter, owner=owner, category=kind, user=user, db=db)['rows']
            for kind in ('sales', 'market')}
    meetings = meeting_rows(db, user, search, owner)
    if quarter:
        meetings = [row for row in meetings if meeting_quarter(row['meeting_date']) == quarter]
    data['meetings'] = meetings
    return data


def workbook_snapshots(worksheets, content):
    matrices, _ = read_workbook(content)
    snapshots = []
    for sheet, (kind, _, records, fields) in zip(matrices, worksheets, strict=True):
        matrix = sheet['matrix']
        if kind == 'summary':
            snapshots.append({'name': sheet['name'], 'kind': kind, 'rows': [],
                              'readonly': [[canonical(value) for value in line] for line in matrix]})
            continue
        editable = next(index for index, (key, _) in enumerate(fields) if key == 'is_paid')
        snapshots.append({
            'name': sheet['name'], 'kind': kind, 'editable': editable,
            'header': [canonical(value) for value in matrix[0]],
            'rows': [{
                'key': row['id'] if kind == 'meetings' else row['record_key'],
                'version': row['version'], 'owner': row['owner'],
                'quarter': meeting_quarter(row['meeting_date']) if kind == 'meetings' else row['quarter'],
                'order_no': row['meeting_date'] if kind == 'meetings' else row['order_no'],
                'is_paid': row['is_paid'], 'values': [canonical(value) for value in values],
            } for row, values in zip(records, matrix[1:], strict=True)],
        })
    return snapshots


@app.get('/api/bonus-export/{kind}')
def export_bonus(kind: Literal['all', 'sales', 'market', 'meetings'], search: str = Query('', max_length=200),
                 quarter: str = Query('', max_length=30), owner: str = Query('', max_length=100),
                 user=Depends(current_user), db: Session=Depends(database)):
    data = bonus_rows(db, user, search, quarter, owner)
    settings = all_settings(db)
    targets = [] if search.strip() else [
        row for row in target_rows(db, settings)
        if (not owner or row['BD姓名'] == owner)
        and (not quarter or row['季度'] == quarter)
        and (user.role != 'bd' or row['BD姓名'] == user.name.strip())
    ]
    summary = build_summary(data, settings, targets)
    worksheets = [('summary', SUMMARY_NAME, summary, None), *group_worksheets(data)]
    for attempt in range(6):
        db.expire_all()
        sequence = db.get(SystemSetting, COUNTER_KEY)
        prior = json.loads(sequence.value) if sequence else {}
        second = export_second()
        number = prior.get('n', 0) + 1 if prior.get('second') == second else 1
        suffix = f'{second}_v{number}'
        meta = {'suffix': suffix, 'token': secrets.token_hex(24), 'kind': 'all', 'user_id': user.id}
        content = protected_workbook(worksheets, meta)
        snapshots = workbook_snapshots(worksheets, content)
        filename = f'奖金明细_{suffix}.xlsx'
        latest = db.get(SystemSetting, latest_key(user))
        payload = {**meta, 'filename': filename, 'consumed': False, 'sheets': snapshots}
        try:
            save_setting(db, COUNTER_KEY, json.dumps({'second': second, 'n': number}), sequence.version if sequence else 0)
            save_setting(db, latest_key(user), json.dumps(payload, ensure_ascii=False), latest.version if latest else 0)
            audit(db, user.username, f'导出统一奖金明细：{sum(len(s["rows"]) for s in snapshots)}行；版本{suffix}')
            db.commit()
            headers = {'Content-Disposition': f"attachment; filename=\"bonus_{suffix}.xlsx\"; filename*=UTF-8''{quote(filename)}",
                       'X-Export-Version': suffix}
            return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)
        except HTTPException as exc:
            db.rollback()
            if exc.status_code != 409 or attempt == 5:
                raise
    raise HTTPException(409, '并发导出繁忙，请重试')


def validate_import(kind, filename, content, user, db):
    require_kind(kind)
    latest = db.get(SystemSetting, latest_key(user), populate_existing=True)
    if not latest:
        raise HTTPException(409, '请先用当前账号导出奖金明细')
    expected = json.loads(latest.value)
    match = re.search(r'_(\d{8}-\d{6}_v[1-9]\d*)\.xlsx$', filename, re.I)
    if not match or match[1] != expected['suffix']:
        raise HTTPException(409, '文件版本不是当前账号最后一次导出版本：' + expected['suffix'])
    if expected['kind'] != kind:
        raise HTTPException(409, '请重新导出统一奖金明细')
    if expected['consumed']:
        raise HTTPException(409, '此版本已经导入，请重新导出后再修改')
    sheets, meta = read_workbook(content)
    if not isinstance(meta, dict) or any(meta.get(k) != expected[k] for k in ('suffix', 'token', 'kind', 'user_id')):
        raise HTTPException(409, '文件内部版本标识不匹配')
    if len(sheets) != len(expected['sheets']) or {s['name'] for s in sheets} != {s['name'] for s in expected['sheets']}:
        raise HTTPException(422, '工作表名称或数量已变化，请保留原导出结构')
    worksheets = list(group_worksheets(bonus_rows(db, user)))
    current = workbook_snapshots(worksheets, protected_workbook(worksheets, {}))
    current_by_key = {(sheet['kind'], row['key']): row for sheet in current for row in sheet['rows']}
    supplied = {sheet['name']: sheet['matrix'] for sheet in sheets}
    changes = []
    for sheet in expected['sheets']:
        matrix = supplied[sheet['name']]
        if sheet.get('kind') == 'summary':
            if [[canonical(value) for value in line] for line in matrix] != sheet['readonly']:
                raise HTTPException(422, '奖金汇总表为只读，不能修改')
            continue
        width = len(sheet['header'])
        if len(matrix) != len(sheet['rows']) + 1 or [canonical(v) for v in matrix[0]] != sheet['header']:
            raise HTTPException(422, '表头或数据行数被修改，不能新增、删除或移动行')
        editable = sheet['editable']
        for ordinal, (snapshot, values) in enumerate(zip(sheet['rows'], matrix[1:], strict=True), 2):
            row = current_by_key.get((sheet['kind'], snapshot['key']))
            location = f'{sheet["name"]}第{ordinal}行'
            if not row or row['version'] != snapshot['version']:
                raise HTTPException(409, f'{location}已变化或超出权限，请重新导出')
            for col in range(width):
                if col == editable:
                    continue
                if canonical(values[col]) != snapshot['values'][col]:
                    raise HTTPException(422, f'{location}{chr(65 + col)}列为只读，不能修改')
                if row['values'][col] != snapshot['values'][col]:
                    raise HTTPException(409, f'{location}源数据或公式结果已更新，请重新导出')
            value = values[editable]
            if not isinstance(value, str) or value not in TRI:
                raise HTTPException(422, f'{location}发放状态只能是：是、否、待确认，不可留空')
            if TRI[value] != row['is_paid']:
                changes.append({key: snapshot[key] for key in ('key', 'version', 'owner', 'quarter', 'order_no')} | {
                    'sheet': sheet['name'], 'before': {'is_paid': row['is_paid']}, 'after': {'is_paid': TRI[value]},
                })
    return latest, expected, changes


def parse_refund_csv(content):
    try:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('gb18030')
        reader = csv.DictReader(io.StringIO(text, newline=''))
        if not reader.fieldnames or reader.fieldnames.count('订单号') != 1:
            raise HTTPException(422, '退款 CSV 缺少唯一的「订单号」列')
        orders = {str(row.get('订单号') or '').strip() for row in reader} - {''}
    except (UnicodeError, csv.Error) as exc:
        raise HTTPException(422, '无法读取退款 CSV') from exc
    if not orders:
        raise HTTPException(422, '退款 CSV 没有可匹配的订单号')
    return orders


def parse_refund_xlsx(content):
    sheets, metadata = read_workbook(content, max_columns=128)
    if metadata is not None:
        raise HTTPException(422, '请上传退款订单明细，奖金发放工作簿请从发放入口回传')
    orders = set()
    found_header = False
    for sheet in sheets:
        matrix = sheet['matrix']
        for index, line in enumerate(matrix[:20]):
            names = [str(value).strip() for value in line]
            if '订单号' not in names:
                continue
            if names.count('订单号') != 1:
                raise HTTPException(422, '退款工作表只能有一个「订单号」列')
            found_header = True
            column = names.index('订单号')
            for row in matrix[index+1:]:
                value = row[column]
                if isinstance(value, Decimal):
                    if value < 0 or value != value.to_integral_value() or value >= 10**15:
                        raise HTTPException(422, '请将长订单号以文本格式保存，避免 Excel 丢失精度')
                    value = str(int(value))
                value = str(value).strip()
                if value:
                    orders.add(value)
            break
    if not found_header or not orders:
        raise HTTPException(422, '退款 XLSX 缺少「订单号」列或没有有效订单号')
    return orders


@app.post('/api/bonus-refunds')
async def import_refunds(filename: str, request: Request, user=Depends(admin), db: Session=Depends(database)):
    suffix = filename.lower().rsplit('.', 1)[-1]
    parsers = {'csv': parse_refund_csv, 'xlsx': parse_refund_xlsx}
    if suffix not in parsers:
        raise HTTPException(422, '请选择退款订单 CSV 或 XLSX 文件')
    orders = parsers[suffix](await request_file(request, '退款文件'))
    matched = set()
    totals = {}
    for kind in ('sales', 'market'):
        rows = commission_snapshot(db, user, page_size=1000000, category=kind)['rows']
        hits = [row['values'].get('订单号', '').strip() for row in rows
                if row['values'].get('订单号', '').strip() in orders]
        totals[kind] = len(hits)
        matched.update(hits)
    saved = set(db.scalars(select(SystemSetting.key).where(SystemSetting.key.like('bonus_refund_%'))))
    added = 0
    for order in sorted(matched):
        key = refund_key(order)
        if key in saved:
            continue
        save_setting(db, key, 'true', 0)
        added += 1
    audit(db, user.username, f'导入退款订单：{len(orders)}个订单号，命中{len(matched)}个，新增标记{added}个')
    db.commit()
    return {'orders': len(orders), 'matched': len(matched), 'added': added, **totals}


async def request_file(request, label='工作簿'):
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>LIMIT:
            raise HTTPException(413, f'{label}不能超过10MB')
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
