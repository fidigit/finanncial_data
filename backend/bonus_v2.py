"""v0.0.2 classification, meeting records, and permission-scoped XLSX exports."""
import io
import json
import re
import zipfile
from datetime import date
from decimal import Decimal
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app import (app, database, current_user, admin, User, SystemSetting,
                         audit, commission_data, query_reference)

COMMISSION_FIELDS = [('quarter','季度'),('owner','BD姓名'),('company','付款公司'),('paid_date','付款时间'),('service','所购服务'),('purchase_type','首购/续费'),('order_amount','订单金额'),('enabled','是否计发提成'),('shared_bd','共享订单'),('allocation_ratio','分摊比例'),('bonus_basis','奖金计算基数'),('market_bd','市场渠道'),('referral','转介绍'),('revenue_total','累计营收'),('confirmed_rate','适用提点（分段提点）'),('bonus','奖金'),('is_paid','是否发放'),('is_refunded','是否退款'),('note','备注')]
MEETING_FIELDS = [('owner','姓名'),('meeting_date','会议时间'),('meeting_type','会议类型'),('location','会议举办地点'),('companies','参会企业数'),('attendees','参会人数'),('friend_rate','好友通过率（≥90%）'),('registrations','六重报名数'),('leads','意向线索企业数（≥5）'),('qualified','是否达标'),('bonus','会议奖金'),('note','特殊情况备注'),('follow_up','会后联系'),('is_paid','还否发放奖金')]


def category_manager(user):
    return user.username in ('admin', '梁梓珊') and user.role in ('admin', 'superadmin')


@app.get('/api/bd-categories')
def categories(user=Depends(current_user), db: Session = Depends(database)):
    if not category_manager(user):
        raise HTTPException(403, '仅admin和梁梓珊可管理身份归类')
    setting = db.get(SystemSetting, 'bd_categories')
    mapping = json.loads(setting.value) if setting else {}
    names = set(query_reference()['options']['owners'])
    names.update(db.scalars(select(User.name).where(User.role == 'bd')).all())
    return {'mapping': mapping, 'names': sorted(names | set(mapping)), 'version': setting.version if setting else 0}


class CategoriesBody(BaseModel):
    mapping: dict[str, Literal['sales', 'market', 'unassigned']]
    version: int = Field(ge=0)


def save_setting(db, key, value, version):
    existing = db.get(SystemSetting, key)
    if existing:
        result = db.execute(update(SystemSetting).where(SystemSetting.key == key, SystemSetting.version == version).values(value=value, version=version + 1))
        if result.rowcount != 1:
            raise HTTPException(409, '数据已被其他人修改，请刷新重试')
    else:
        if version:
            raise HTTPException(409, '数据版本不一致，请刷新重试')
        try:
            db.add(SystemSetting(key=key, value=value, version=1))
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, '配置已被其他人创建，请重新加载') from exc


@app.put('/api/bd-categories')
def set_categories(body: CategoriesBody, user=Depends(current_user), db: Session = Depends(database)):
    known = categories(user, db)['names']
    if set(body.mapping) - set(known):
        raise HTTPException(422, '姓名不存在，请刷新')
    save_setting(db, 'bd_categories', json.dumps(body.mapping, ensure_ascii=False), body.version)
    audit(db, user.username, '修改BD市场/销售身份归类')
    db.commit()
    return {'ok': True}


class MeetingBody(BaseModel):
    owner: str = Field(min_length=1, max_length=80)
    meeting_date: date
    meeting_type: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=200)
    companies: int = Field(ge=0)
    attendees: int = Field(ge=0)
    friend_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    registrations: int = Field(ge=0)
    leads: int = Field(ge=0)
    qualified: bool | None = None
    bonus: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    note: str = Field(default='', max_length=1000)
    follow_up: str = Field(default='', max_length=1000)
    is_paid: bool | None = None
    version: int = Field(default=0, ge=0)


def meeting_rows(db, user, search='', owner=''):
    records = []
    for setting in db.scalars(select(SystemSetting).where(SystemSetting.key.like('meeting_record_%')).order_by(SystemSetting.key)):
        row = {**json.loads(setting.value), 'id': setting.key, 'version': setting.version}
        if user.role == 'bd' and row['owner'].strip() != user.name.strip():
            continue
        if owner and row['owner'] != owner:
            continue
        if search.strip().casefold() and not any(search.strip().casefold() in str(v).casefold() for v in row.values()):
            continue
        records.append(row)
    return records


@app.get('/api/meetings')
def meetings(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str = Query('', max_length=200), owner: str = Query('', max_length=80), user=Depends(current_user), db: Session = Depends(database)):
    rows = meeting_rows(db, user, search, owner)
    return {'rows': rows[(page-1)*page_size:page*page_size], 'total': len(rows), 'can_edit': user.role in ('admin', 'superadmin')}


def validate_meeting_owner(db, owner):
    if owner != owner.strip() or not db.scalar(select(User.id).where(User.name == owner, User.role == 'bd')):
        raise HTTPException(422, '请选择已有BD账号的姓名')


@app.post('/api/meetings')
def create_meeting(body: MeetingBody, user=Depends(admin), db: Session = Depends(database)):
    import uuid
    validate_meeting_owner(db, body.owner)
    key = 'meeting_record_' + uuid.uuid4().hex
    save_setting(db, key, body.model_dump_json(exclude={'version'}), 0)
    audit(db, user.username, '新增会议奖金明细：' + body.owner)
    db.commit()
    return {'ok': True, 'id': key}


@app.put('/api/meetings/{record_id}')
def edit_meeting(record_id: str, body: MeetingBody, user=Depends(admin), db: Session = Depends(database)):
    if not re.fullmatch(r'meeting_record_[a-f0-9]{32}', record_id) or not db.get(SystemSetting, record_id):
        raise HTTPException(404, '会议记录不存在')
    validate_meeting_owner(db, body.owner)
    save_setting(db, record_id, body.model_dump_json(exclude={'version'}), body.version)
    audit(db, user.username, '修改会议奖金明细：' + record_id)
    db.commit()
    return {'ok': True}


def workbook_bytes(rows, fields):
    """Minimal OOXML with literal inline strings (never executable Excel formulas)."""
    groups = {}
    for row in rows:
        groups.setdefault(row.get('owner', '').strip() or '未归属', []).append(row)
    if not groups:
        groups['无数据'] = []
    out = io.BytesIO()
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    names, sheets, rels, overrides = set(), [], [], []
    def cell(value):
        if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
            return '<c t="n"><v>' + str(value) + '</v></c>'
        if value is None:
            value = '待确认'
        elif isinstance(value, bool):
            value = '是' if value else '否'
        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))[:32767]
        return '<c t="inlineStr"><is><t xml:space="preserve">' + escape(value) + '</t></is></c>'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for index, (owner, records) in enumerate(sorted(groups.items()), 1):
            base = re.sub(r'[\\/*?:\[\]]', '_', owner).strip("'")[:31] or '未命名'
            name, suffix = base, 1
            while name.casefold() in names:
                suffix += 1
                name = base[:31-len(str(suffix))-1] + '_' + str(suffix)
            names.add(name.casefold())
            sheets.append(f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>')
            rels.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
            overrides.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            values = [[label for _, label in fields]]
            numeric_fields = {'order_amount', 'bonus_basis', 'revenue_total', 'bonus', 'companies', 'attendees', 'registrations', 'leads'}
            for row in records:
                line = []
                for key, _ in fields:
                    value = row.get(key)
                    if key == 'confirmed_rate' and row.get('rate_display'):
                        value = row['rate_display']
                    elif key in ('allocation_ratio', 'confirmed_rate') and value is not None:
                        value = f'{Decimal(str(value)) * 100}%'
                    elif key == 'friend_rate' and value is not None:
                        value = f'{value}%'
                    elif key in numeric_fields and value not in (None, ''):
                        try:
                            number = Decimal(str(value))
                            if number.is_finite():
                                value = number
                        except ArithmeticError:
                            pass
                    line.append(value)
                values.append(line)
            body = ''.join('<row>' + ''.join(cell(v) for v in line) + '</row>' for line in values)
            z.writestr(f'xl/worksheets/sheet{index}.xml', f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>{body}</sheetData></worksheet>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{"".join(sheets)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(rels)+'</Relationships>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+''.join(overrides)+'</Types>')
    return out.getvalue()


@app.get('/api/bonus-export/{kind}')
def export_bonus(kind: Literal['sales', 'market', 'meetings'], search: str = Query('', max_length=200), quarter: str = Query('', max_length=30), owner: str = Query('', max_length=100), user=Depends(current_user), db: Session = Depends(database)):
    if kind == 'meetings':
        rows, fields = meeting_rows(db, user, search, owner), MEETING_FIELDS
    else:
        rows = commission_data(page=1, page_size=1000000, search=search, quarter=quarter, owner=owner, category=kind, user=user, db=db)['rows']
        fields = COMMISSION_FIELDS
        from backend.bonus_transfer import export_commission
        return export_commission(kind,rows,user,db)
    audit(db, user.username, f'导出{kind}奖金表：{len(rows)}行')
    db.commit()
    return Response(workbook_bytes(rows, fields), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment; filename="{kind}.xlsx"'})
