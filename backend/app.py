"""商务分析基础版。未确认规则不参与计算，外部连接仅做元数据读取。"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, Integer, Numeric, String, Text, create_engine, delete, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from backend.reference_data import query_reference
from backend.commission_data import service_key, record_key, project_row, with_display_note

ROOT = Path(__file__).resolve().parent.parent
DEMO = os.getenv('DEMO_MODE', 'true').lower() == 'true'
(ROOT / 'data').mkdir(exist_ok=True)
DB_URL = os.getenv('DATABASE_URL', 'sqlite:///' + (ROOT / 'data/app.db').as_posix())
engine = create_engine(DB_URL, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False}} if DB_URL.startswith('sqlite') else {}))


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(20), default='blue')


class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    expires: Mapped[int] = mapped_column(Integer)


class Bonus(Base):
    __tablename__ = 'bonus_demo_records'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    order_no: Mapped[str] = mapped_column(String(60), unique=True)
    customer: Mapped[str] = mapped_column(String(120))
    service: Mapped[str] = mapped_column(String(60))
    period: Mapped[str] = mapped_column(String(7), index=True)
    basis: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    accrued: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    issue: Mapped[str] = mapped_column(String(100), default='')


class Source(Base):
    __tablename__ = 'data_sources'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[str] = mapped_column(Text)


class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    config: Mapped[str] = mapped_column(Text)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))


class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def audit(db, actor, action):
    db.add(Audit(actor=actor, action=action, created_at=datetime.now(timezone.utc).isoformat()))


def initialize():
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        from backend.bonus_rules import initialize_rule_sources
        initialize_rule_sources(db)
        if not db.get(SystemSetting, 'bd_categories'):
            names = ['何卫', '余飞', '周政', '屈敬东', '崔赵鹏', '曾德康', '杨红星', '贺庆锋']
            secrets.SystemRandom().shuffle(names)
            mapping = {name: 'sales' if i < 4 else 'market' for i, name in enumerate(names)}
            db.add(SystemSetting(key='bd_categories', value=json.dumps(mapping, ensure_ascii=False), version=1))
            db.commit()
        if not db.get(SystemSetting, 'reference_bd_self_only'):
            db.add(SystemSetting(key='reference_bd_self_only', value='true', version=1))
            db.commit()
        if not db.scalar(select(User.id).limit(1)):
            password = 'Demo2026!' if DEMO else os.getenv('ADMIN_PASSWORD', '')
            if len(password) < 12 and not DEMO:
                raise RuntimeError('生产首次启动必须提供至少12位 ADMIN_PASSWORD')
            db.add(User(username='admin', name='系统管理员', password=hash_password(password), role='admin'))
            if DEMO:
                db.add_all([User(username='bd.lin', name='林晨', password=hash_password('Demo2026!'), role='bd'), User(username='bd.zhou', name='周宁', password=hash_password('Demo2026!'), role='bd')])
            db.commit()
        if not DEMO:
            if db.scalar(select(Bonus.id).limit(1)) or db.scalar(select(User.id).where(User.username.in_(['bd.lin', 'bd.zhou'])).limit(1)):
                raise RuntimeError('检测到演示数据或演示账号，生产模式请使用独立空数据库')
        if DEMO and not db.scalar(select(Bonus.id).limit(1)):
            people = db.scalars(select(User).where(User.role == 'bd')).all()
            for person in people:
                for month in range(7, 11):
                    for i in range(1, 7):
                        basis = Decimal(28000 + i * 13500 + (month - 7) * 3200 + person.id * 800)
                        accrued = Decimal(700 + i * 360 + month * 40)
                        paid = accrued if i < 4 else (Decimal(500) if i == 4 else Decimal(0))
                        db.add(Bonus(owner_id=person.id, order_no=f'DEMO-{person.id}-{month:02d}{i:03d}', customer=['星河科技', '远山互动', '启航传媒', '云帆网络', '拾光品牌', '青禾数字'][i-1], service=['品牌推广', '内容营销', '渠道合作'][i % 3], period=f'2026-{month:02d}', basis=basis, accrued=accrued, paid=paid, shared=i == 4, issue='分摊依据待核对' if i == 4 else ''))
            db.commit()


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title='商务数据分析 API', version='0.0.6', lifespan=lifespan, docs_url='/api/docs' if DEMO else None, redoc_url=None, openapi_url='/api/openapi.json' if DEMO else None)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.headers.get('X-Requested-With') != 'BD-Workbench':
        return Response('请求校验失败', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
    return response


def database():
    with Session(engine) as db:
        yield db


def current_user(request: Request, db: Session = Depends(database)):
    token = request.cookies.get('bd_session', '')
    session = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
    user = db.get(User, session.user_id) if session and session.expires > int(time.time()) else None
    if not user or not user.active:
        raise HTTPException(401, '请重新登录')
    return user


def admin(user: User = Depends(current_user)):
    if user.role not in ('admin', 'superadmin'):
        raise HTTPException(403, '此操作仅限系统管理员')
    return user


def can_manage_reference_policy(user: User):
    return user.role == 'superadmin' or (user.role == 'admin' and user.username == 'admin')


def reference_policy_manager(user: User = Depends(current_user)):
    if not can_manage_reference_policy(user):
        raise HTTPException(403, '此操作仅限超级管理员或admin账号')
    return user


def user_view(user):
    return {'id': user.id, 'username': user.username, 'name': user.name, 'role': user.role, 'theme': user.theme, 'demo': DEMO}


class LoginBody(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=256)


attempts = {}


@app.get('/api/health')
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ok', 'demo': DEMO, 'version': app.version}


@app.post('/api/login')
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(database)):
    key = request.client.host
    now = time.time()
    recent = [t for t in attempts.get(key, []) if now - t < 300]
    if len(recent) >= 10:
        raise HTTPException(429, '登录尝试过多，请5分钟后重试')
    attempts[key] = recent + [now]
    user = db.scalar(select(User).where(User.username == body.username))
    stored = user.password if user else hash_password('invalid-password', 'dummy-salt')
    if not user or not user.active or not hmac.compare_digest(stored, hash_password(body.password, stored.split(':')[0])):
        raise HTTPException(401, '账号或密码错误，或账号已停用')
    attempts.pop(key, None)
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id, expires=int(now) + 28800))
    audit(db, user.username, '登录系统')
    db.commit()
    response.set_cookie('bd_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true', samesite='strict', max_age=28800, path='/')
    return user_view(user)


@app.post('/api/logout')
def logout(request: Request, response: Response, user=Depends(current_user), db: Session = Depends(database)):
    record = db.get(LoginSession, hashlib.sha256(request.cookies['bd_session'].encode()).hexdigest())
    if record:
        db.delete(record)
        db.commit()
    response.delete_cookie('bd_session', path='/')
    return {'ok': True}


@app.get('/api/me')
def me(user=Depends(current_user)):
    return user_view(user)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


@app.put('/api/me/password')
def change_password(body: ChangePasswordBody, response: Response, user=Depends(current_user), db: Session = Depends(database)):
    if not hmac.compare_digest(user.password, hash_password(body.current_password, user.password.split(':')[0])):
        raise HTTPException(400, '当前密码不正确')
    if body.new_password != body.confirm_password:
        raise HTTPException(422, '两次新密码输入不一致')
    if body.current_password == body.new_password:
        raise HTTPException(422, '新密码不能与当前密码相同')
    user.password = hash_password(body.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, user.username, '修改本人密码，注销全部登录会话')
    db.commit()
    response.delete_cookie('bd_session', path='/')
    return {'ok': True, 'message': '密码已修改，请使用新密码重新登录'}


class ThemeBody(BaseModel):
    theme: Literal['blue', 'green', 'purple', 'cyan', 'amber']


@app.put('/api/me/theme')
def theme(body: ThemeBody, user=Depends(current_user), db: Session = Depends(database)):
    user.theme = body.theme
    db.commit()
    return user_view(user)


def scoped_bonuses(db, user, period=None, personal=False):
    query = select(Bonus)
    if user.role not in ('admin', 'superadmin') or personal:
        query = query.where(Bonus.owner_id == user.id)
    if period:
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period):
            raise HTTPException(422, '期间格式须为 YYYY-MM')
        query = query.where(Bonus.period == period)
    return db.scalars(query.order_by(Bonus.id.desc())).all()


def bonus_view(b, db):
    return {'id': b.id, 'order_no': b.order_no, 'customer': b.customer, 'service': b.service, 'owner': db.get(User, b.owner_id).name, 'period': b.period, 'basis': str(b.basis), 'accrued': str(b.accrued), 'paid': str(b.paid), 'unpaid': str(b.accrued-b.paid), 'shared': b.shared, 'issue': b.issue, 'status': '已发放' if b.paid == b.accrued else ('部分发放' if b.paid else '未发放'), 'rule_version': '演示快照 · 不代表真实计奖规则', 'source': '系统演示数据', 'demo': True}


@app.get('/api/bonuses')
def bonuses(period: str | None = None, personal: bool = False, user=Depends(current_user), db: Session = Depends(database)):
    return [bonus_view(b, db) for b in scoped_bonuses(db, user, period, personal)]


@app.get('/api/bonuses/export')
def export(period: str | None = None, personal: bool = False, user=Depends(current_user), db: Session = Depends(database)):
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['数据性质', '订单编号', '客户', 'BD', '期间', '计奖基数', '应计', '已发放', '待发放'])
    for b in scoped_bonuses(db, user, period, personal):
        row = bonus_view(b, db)
        values = ['演示数据', b.order_no, b.customer, row['owner'], b.period, str(b.basis), str(b.accrued), str(b.paid), row['unpaid']]
        writer.writerow(["'" + x if x.startswith(('=', '+', '-', '@', '\t', '\r')) else x for x in values])
    audit(db, user.username, '导出本人或授权范围奖金明细')
    db.commit()
    return StreamingResponse(iter([output.getvalue()]), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="bonus-demo.csv"'})


@app.get('/api/bonuses/{record_id}')
def bonus_detail(record_id: int, user=Depends(current_user), db: Session = Depends(database)):
    b = db.get(Bonus, record_id)
    if not b or (user.role not in ('admin', 'superadmin') and b.owner_id != user.id):
        raise HTTPException(404, '记录不存在或不在授权范围')
    return bonus_view(b, db)


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['mysql', 'maxcompute']
    host: str = Field(default='', max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(default='', max_length=100)
    project: str = Field(default='', max_length=100)
    endpoint: str = Field(default='', max_length=500)
    credential_ref: str = Field(pattern=r'^BD_SOURCE_[A-Z0-9_]{1,60}$')
    description: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def valid_connection(self):
        if self.kind == 'mysql' and (not re.fullmatch(r'[A-Za-z0-9._-]+', self.host) or not self.database):
            raise ValueError('MySQL 必须提供有效主机及数据库名')
        if self.kind == 'maxcompute' and (not self.project or not self.endpoint.startswith('https://')):
            raise ValueError('MaxCompute 必须提供项目与 HTTPS Endpoint')
        return self


def source_view(source):
    config = json.loads(source.config)
    return {'id': source.id, **config, 'credential_configured': bool(os.getenv(config['credential_ref'])), 'status': '待测试'}


@app.get('/api/sources')
def sources(user=Depends(admin), db: Session = Depends(database)):
    return [source_view(s) for s in db.scalars(select(Source)).all()]


@app.get('/api/reference-data')
def reference_data(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default='', max_length=200),
    quarter: str = Query(default='', max_length=30),
    owner: str = Query(default='', max_length=100),
    project: str = Query(default='', max_length=100),
    ownership: str = Query(default='', max_length=30),
    user=Depends(current_user),
    db: Session = Depends(database),
):
    setting = db.get(SystemSetting, 'reference_bd_self_only')
    self_only = not setting or setting.value == 'true'
    allowed_owner = user.name if user.role == 'bd' and self_only else None
    result = query_reference(page, page_size, search, quarter, owner, project, ownership, allowed_owner=allowed_owner)
    return {**result, 'access_scope': 'self' if allowed_owner is not None else 'all', 'policy_version': setting.version if setting else 1}


@app.get('/api/reference-data/policy')
def reference_policy(user=Depends(current_user), db: Session = Depends(database)):
    setting = db.get(SystemSetting, 'reference_bd_self_only')
    return {'self_only': not setting or setting.value == 'true', 'version': setting.version if setting else 1, 'can_manage': can_manage_reference_policy(user)}


class ReferencePolicyBody(BaseModel):
    self_only: bool
    version: int = Field(ge=1)


def commission_snapshot(db, user, **filters):
    allowed_owner = user.name.strip() if user.role == 'bd' else None
    category = filters.pop('category', '')
    if category:
        setting = db.get(SystemSetting, 'bd_categories')
        mapping = json.loads(setting.value) if setting else {}
        filters['allowed_owners'] = {name for name, kind in mapping.items() if kind == category}
    return query_reference(allowed_owner=allowed_owner, **filters)


@app.get('/api/commission-data')
def commission_data(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str = Query('', max_length=200), quarter: str = Query('', max_length=30), owner: str = Query('', max_length=100), category: Literal['', 'sales', 'market'] = '', user=Depends(current_user), db: Session = Depends(database)):
    if category == 'sales':
        from backend.sales_formulas import sales_response
        return sales_response(db, user, page, page_size, search, quarter, owner)
    snapshot = commission_snapshot(db, user, page=page, page_size=page_size, search=search, quarter=quarter, owner=owner, category=category)
    from backend.bonus_rules import shared_service_rule, GLOBAL_KEY, setting_payload, order_year, YEAR_PLAN_PREFIX
    settings = {s.key: s for s in db.scalars(select(SystemSetting))}
    minimum = setting_payload(settings, GLOBAL_KEY).get('vip_minimum', '1680')
    rules, pending = {}, []
    for service in snapshot['options']['projects']:
        rule = shared_service_rule(settings, service, vip_minimum=minimum, year=None)
        if rule:
            rules[service] = rule
        else:
            pending.append(service)
    records = []
    for row in snapshot['rows']:
        setting = settings.get(record_key(row))
        confirmation = {**json.loads(setting.value), 'version': setting.version} if setting else None
        values = row['values']
        rule = shared_service_rule(settings, values.get('付费项目', ''), values.get('订单金额'), minimum, order_year(values))
        if rule:
            rules[values.get('付费项目', '')] = rule
        records.append(with_display_note(project_row(row, rule, confirmation)))
    pending = sorted({r['service'] for r in records if r['enabled'] is None})
    return {'rows': records, 'total': snapshot['total'], 'options': snapshot['options'], 'pending_services': pending, 'can_edit': user.role in ('admin', 'superadmin'), 'can_edit_note': True, 'rules': rules}


class ServiceRuleBody(BaseModel):
    service: str = Field(min_length=1, max_length=200)
    enabled: bool
    note: str = Field(min_length=1, max_length=500)


@app.put('/api/commission-data/service-rule')
def save_service_rule(body: ServiceRuleBody, user=Depends(admin), db: Session = Depends(database)):
    services = commission_snapshot(db, user)['options']['projects']
    if body.service not in services:
        raise HTTPException(422, '所购服务不存在，请刷新列表')
    if body.service == '团队VIP':
        raise HTTPException(422, '团队VIP按全局金额下限判断，请通过是否计发提成的齿轮设置')
    from backend.bonus_rules import YEAR_PLAN_PREFIX
    if db.scalar(select(SystemSetting.key).where(SystemSetting.key.like(YEAR_PLAN_PREFIX+'%')).limit(1)):
        raise HTTPException(409, '请在奖金方案中选择年份并维护本年度规则')
    key = service_key(body.service)
    rule = db.get(SystemSetting, key)
    if rule:
        rule.value = body.model_dump_json()
        rule.version += 1
    else:
        db.add(SystemSetting(key=key, value=body.model_dump_json(), version=1))
    audit(db, user.username, '设置服务提成规则：' + body.service + ('，计发' if body.enabled else '，不计发'))
    db.commit()
    return {'ok': True}


class CommissionConfirmationBody(BaseModel):
    record_key: str = Field(pattern=r'^commission_record_[a-f0-9]{40}$')
    version: int = Field(ge=0)
    enabled: bool | None = None
    shared_bd: str = Field(default='', max_length=200)
    allocation_ratio: Decimal | None = Field(default=None, ge=0, le=1, max_digits=8, decimal_places=6)
    bonus_basis: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    market_bd: str = Field(default='', max_length=100)
    confirmed_rate: Decimal | None = Field(default=None, ge=0, le=1, max_digits=8, decimal_places=6)
    bonus: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    is_paid: bool | None = None
    is_refunded: bool | None = None
    note: str = Field(min_length=1, max_length=1000)


@app.put('/api/commission-data/confirmation')
def save_commission_confirmation(body: CommissionConfirmationBody, user=Depends(admin), db: Session = Depends(database)):
    # Bind edits to the exact source row contents, not a potentially repeated order number.
    rows = commission_snapshot(db, user, page_size=1000000)['rows']
    row = next((r for r in rows if record_key(r) == body.record_key), None)
    if not row:
        raise HTTPException(409, '来源记录已变化，请刷新后重新确认')
    previous = db.get(SystemSetting, body.record_key)
    payload = body.model_dump_json(exclude={'record_key', 'version'})
    if previous:
        from sqlalchemy import update
        result = db.execute(update(SystemSetting).where(SystemSetting.key == body.record_key, SystemSetting.version == body.version).values(value=payload, version=body.version+1))
        if result.rowcount != 1:
            raise HTTPException(409, '记录已被修改，请刷新后重试')
    else:
        if body.version != 0:
            raise HTTPException(409, '确认版本不一致，请刷新后重试')
        db.add(SystemSetting(key=body.record_key, value=payload, version=1))
    audit(db, user.username, '人工确认提成记录：' + row['values'].get('订单号', '') + '，来源行' + str(row['row_id']))
    db.commit()
    return {'ok': True}


class CommissionNoteBody(BaseModel):
    model_config = {'extra': 'forbid'}
    record_key: str = Field(pattern=r'^commission_record_[a-f0-9]{40}$')
    version: int = Field(ge=0)
    note: str = Field(max_length=4000)


@app.put('/api/commission-data/note')
def save_commission_note(body: CommissionNoteBody, user=Depends(current_user), db: Session=Depends(database)):
    from backend.bonus_v2 import save_setting
    rows = commission_snapshot(db, user, page_size=1000000)['rows']
    row = next((r for r in rows if record_key(r)==body.record_key), None)
    if not row:
        raise HTTPException(409, '来源记录已变化或无权限，请重新加载')
    previous = db.get(SystemSetting, body.record_key)
    payload = json.loads(previous.value) if previous else {}
    payload['note_override'] = body.note
    save_setting(db, body.record_key, json.dumps(payload, ensure_ascii=False), body.version)
    audit(db,user.username,'修改订单备注：'+row['values'].get('订单号','')+'，来源行'+str(row['row_id']))
    db.commit()
    return {'ok':True}


@app.put('/api/reference-data/policy')
def update_reference_policy(body: ReferencePolicyBody, user=Depends(reference_policy_manager), db: Session = Depends(database)):
    # Version check prevents one administrator tab silently overwriting another.
    setting = db.get(SystemSetting, 'reference_bd_self_only')
    if not setting:
        raise HTTPException(409, '权限配置尚未初始化，请刷新后重试')
    from sqlalchemy import update
    updated = db.execute(update(SystemSetting).where(SystemSetting.key == setting.key, SystemSetting.version == body.version).values(value='true' if body.self_only else 'false', version=body.version+1))
    if updated.rowcount != 1:
        raise HTTPException(409, '权限配置已更新，请刷新后重试')
    audit(db, user.username, '业务参考表BD数据范围：' + ('仅本人账单' if body.self_only else '全部账单（含无归属）'))
    db.commit()
    return {'self_only': body.self_only, 'version': body.version + 1, 'can_manage': True}


@app.post('/api/sources', status_code=201)
def create_source(body: SourceBody, user=Depends(admin), db: Session = Depends(database)):
    if db.scalar(select(Source).where(Source.name == body.name)):
        raise HTTPException(409, '连接名称已存在')
    row = Source(name=body.name, config=body.model_dump_json())
    db.add(row)
    audit(db, user.username, '新增数据源配置：' + body.name)
    db.commit()
    return source_view(row)


def get_source(db, source_id):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, '数据源不存在')
    return json.loads(source.config)


def connect_source(config, metadata=False):
    """Read-only probes. Destinations and credentials must both be provisioned server-side."""
    from urllib.parse import urlparse
    hostname = config['host'] if config['kind'] == 'mysql' else urlparse(config['endpoint']).hostname
    allowed = {x.strip().lower() for x in os.getenv('BD_ALLOWED_SOURCE_HOSTS', '').split(',') if x.strip()}
    if not hostname or hostname.lower() not in allowed:
        raise HTTPException(422, '请先由服务器管理员将目标主机加入 BD_ALLOWED_SOURCE_HOSTS')
    secret_raw = os.getenv(config['credential_ref'])
    if not secret_raw:
        raise HTTPException(422, '凭证引用尚未在服务器配置，请配置对应环境变量后重启服务')
    try:
        secret = json.loads(secret_raw)
        if config['kind'] == 'mysql':
            import pymysql
            connection = pymysql.connect(host=config['host'], port=config['port'], user=secret['username'], password=secret['password'], database=config['database'], connect_timeout=5, read_timeout=10, write_timeout=5, ssl=secret.get('ssl'))
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    if not metadata:
                        return {'ok': True, 'message': 'MySQL 连接成功（只读探测）'}
                    cursor.execute('SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 2000', (config['database'],))
                    return {'columns': [{'table': r[0], 'name': r[1], 'type': r[2]} for r in cursor.fetchall()], 'limit': 2000}
            finally:
                connection.close()
        from odps import ODPS, options
        options.connect_timeout = 5
        options.read_timeout = 10
        client = ODPS(secret['access_id'], secret['access_key'], project=config['project'], endpoint=config['endpoint'])
        # Project metadata lookup verifies authentication; list_tables is lazy otherwise.
        client.get_project(config['project']).reload()
        if not metadata:
            return {'ok': True, 'message': 'MaxCompute 项目连接成功（只读探测）'}
        columns = []
        for i, table in enumerate(client.list_tables()):
            if i >= 20:
                break
            for col in table.table_schema.columns:
                columns.append({'table': table.name, 'name': col.name, 'type': str(col.type)})
        return {'columns': columns, 'limit': 20}
    except HTTPException:
        raise
    except Exception:
        # SDK errors can contain credentials, SQL or topology. Never return raw exceptions.
        raise HTTPException(502, '连接或元数据读取失败，请核对网络、权限和服务器凭证配置')


@app.post('/api/sources/{source_id}/test')
def test_source(source_id: int, user=Depends(admin), db: Session = Depends(database)):
    result = connect_source(get_source(db, source_id))
    audit(db, user.username, f'测试数据源 #{source_id}：成功')
    db.commit()
    return result


@app.get('/api/sources/{source_id}/metadata')
def source_metadata(source_id: int, user=Depends(admin), db: Session = Depends(database)):
    return connect_source(get_source(db, source_id), True)


class DatasetBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_id: int
    table_name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
    target: Literal['orders', 'receipts', 'allocations', 'payments', 'custom']
    primary_key: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
    owner_field: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
    watermark: str = Field(default='', pattern=r'^([A-Za-z_][A-Za-z0-9_]{0,127})?$')
    partition: str = Field(default='', max_length=120)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=80)

    @model_validator(mode='after')
    def safe_mapping(self):
        for key, value in self.mapping.items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', key) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', value):
                raise ValueError('字段映射只允许字段标识，不允许 SQL 或表达式')
        return self


@app.get('/api/datasets')
def datasets(user=Depends(admin), db: Session = Depends(database)):
    return [{'id': d.id, **json.loads(d.config), 'status': '草稿 · 未启用同步'} for d in db.scalars(select(Dataset)).all()]


@app.post('/api/datasets', status_code=201)
def create_dataset(body: DatasetBody, user=Depends(admin), db: Session = Depends(database)):
    get_source(db, body.source_id)
    if db.scalar(select(Dataset.id).where(Dataset.name == body.name)):
        raise HTTPException(409, '数据集名称已存在')
    d = Dataset(name=body.name, source_id=body.source_id, config=body.model_dump_json())
    db.add(d)
    audit(db, user.username, '新增数据集草稿：' + body.name)
    db.commit()
    return {'id': d.id, **body.model_dump(), 'status': '草稿 · 未启用同步'}


@app.post('/api/settlements/preview')
def preview(user=Depends(admin)):
    raise HTTPException(409, '计奖基数、阶梯算法和分摊顺序尚未确认，暂不能生成真实试算或结算')


@app.get('/api/audit')
def audit_list(user=Depends(admin), db: Session = Depends(database)):
    return [{'id': a.id, 'actor': a.actor, 'action': a.action, 'created_at': a.created_at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(100)).all()]


@app.get('/api/users')
def user_list(user=Depends(admin), db: Session = Depends(database)):
    return [{**user_view(u), 'active': u.active} for u in db.scalars(select(User)).all()]


class NewUser(BaseModel):
    username: str = Field(pattern=r'^[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9._-]{0,79}$')
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=5, max_length=128)
    role: Literal['admin', 'bd'] = 'bd'


@app.post('/api/users', status_code=201)
def create_user(body: NewUser, user=Depends(admin), db: Session = Depends(database)):
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, '账号已存在')
    new = User(username=body.username, name=body.name, role=body.role, password=hash_password(body.password))
    db.add(new)
    audit(db, user.username, '创建账号：' + body.username)
    db.commit()
    return user_view(new)


class ActiveBody(BaseModel):
    active: bool


@app.put('/api/users/{user_id}/active')
def active_user(user_id: int, body: ActiveBody, user=Depends(admin), db: Session = Depends(database)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, '账号不存在')
    if target.id == user.id:
        raise HTTPException(409, '不能停用当前登录账号')
    if target.role == 'superadmin' and user.role != 'superadmin':
        raise HTTPException(403, '普通管理员不能修改超级管理员状态')
    target.active = body.active
    audit(db, user.username, f'账号 {target.username}：' + ('启用' if body.active else '停用'))
    db.commit()
    return {'ok': True}


from backend import bonus_v2  # Register API routes before the frontend catch-all.
from backend import sales_formulas
from backend import sales_workspace
from backend import bonus_config
from backend import bonus_transfer

if (ROOT / 'dist').is_dir():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
