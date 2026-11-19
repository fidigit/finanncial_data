"""Versioned editors for quarterly targets, annual service plans and shared constants."""
import json
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import app, admin, current_user, database, SystemSetting, User, audit, query_reference
from backend.bonus_rules import TARGETS_KEY, GLOBAL_KEY, YEAR_PLAN_PREFIX, year_plan_key, setting_payload, target_member_active
from backend.order_source import iter_orders
from backend.bonus_v2 import save_setting

Quarter = Annotated[str, Field(pattern=r'^20\d{2}Q[1-4]$')]
Year = Annotated[int, Field(ge=2000, le=2099)]
COMMON_FIELDS = ['vip_minimum','threshold','renewal_rate','renewal_excess','self_rate','self_excess','market_rate','market_excess','partner_rate','partner_excess']

MARKET_RATES_KEY = 'bonus_market_parameters'
MARKET_DEFAULTS = {
    'direct_referral': '5', 'direct_no_referral': '10', 'indirect_first': '2',
    'renewal_low': '3', 'renewal_high': '5',
}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VersionBody(StrictBody):
    version: int = Field(ge=0)


def all_settings(db):
    return {s.key:s for s in db.scalars(select(SystemSetting))}


def market_rates(settings):
    return {**MARKET_DEFAULTS, **setting_payload(settings, MARKET_RATES_KEY)}


Rate = Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]


class MarketRateUpdate(VersionBody):
    direct_referral: Rate
    direct_no_referral: Rate
    indirect_first: Rate
    renewal_low: Rate
    renewal_high: Rate


@app.get('/api/bonus-config/market-rates')
def get_market_rates(user=Depends(current_user), db: Session=Depends(database)):
    settings = all_settings(db)
    saved = settings.get(MARKET_RATES_KEY)
    return {'parameters': market_rates(settings), 'version': saved.version if saved else 0,
            'can_edit': user.role in ('admin', 'superadmin')}


@app.put('/api/bonus-config/market-rates')
def put_market_rates(body: MarketRateUpdate, user=Depends(admin), db: Session=Depends(database)):
    parameters = body.model_dump(mode='json', exclude={'version'})
    save_setting(db, MARKET_RATES_KEY, json.dumps(parameters), body.version)
    audit(db, user.username, '修改市场奖金全局提点')
    db.commit()
    return get_market_rates(user, db)


def previous_quarter(quarter):
    year, number = int(quarter[:4]), int(quarter[-1])
    return f'{year}Q{number-1}' if number > 1 else f'{year-1}Q4'


def known_names(db):
    names = set(query_reference()['options']['owners'])
    names.update(db.scalars(select(User.name).where(User.role=='bd', User.active.is_(True), User.username.not_in(['bd.lin','bd.zhou']))))
    return sorted(name.strip() for name in names if name.strip())


def target_rows(db, settings):
    from backend.sales_formulas import setting_key
    rows = [dict(r) for r in setting_payload(settings, TARGETS_KEY).get('rows', [])]
    # Include legacy per-person targets in the editor so they can be maintained here.
    pairs = {(r['values'].get('BD姓名','').strip(),r['values'].get('季度','')) for r in query_reference(page_size=1000000)['rows']}
    pairs.update((r['BD姓名'],r['季度']) for r in rows)
    existing = {(r['BD姓名'],r['季度']) for r in rows}
    for name, quarter in sorted(pairs):
        old = setting_payload(settings, setting_key('period', name, quarter))
        if old.get('target') is not None and (name,quarter) not in existing:
            rows.append({'BD姓名':name,'季度':quarter,'直接营收目标':old['target']})
    return [r for r in rows if target_member_active(settings, r['BD姓名'], r['季度'])]


def target_quarters(settings, rows):
    return sorted(set(setting_payload(settings, TARGETS_KEY).get('quarters', [])) | {r['季度'] for r in rows})


def save_targets(db, settings, rows, version, *, quarter=None, memberships=None):
    payload = setting_payload(settings, TARGETS_KEY)
    quarters = set(target_quarters(settings, rows))
    if quarter:
        quarters.add(quarter)
    save_setting(db, TARGETS_KEY, json.dumps({**payload, 'sheet':'奖金汇总表',
        'columns':['BD姓名','季度','直接营收目标'], 'rows': rows, 'quarters':sorted(quarters),
        'memberships': memberships if memberships is not None else payload.get('memberships', {})}, ensure_ascii=False), version)


@app.get('/api/bonus-config/targets')
def get_targets(quarter: Quarter | None = None, user=Depends(current_user), db: Session=Depends(database)):
    settings = all_settings(db)
    rows = target_rows(db, settings)
    quarters = sorted(target_quarters(settings, rows), reverse=True)
    selected = quarter or (quarters[0] if quarters else f'{date.today().year}Q{(date.today().month-1)//3+1}')
    prior = previous_quarter(selected)
    visible = [{field: r.get(field) for field in ('BD姓名', '季度', '直接营收目标')}
               for r in rows if r['季度']==selected and (user.role!='bd' or r['BD姓名'].strip()==user.name.strip())]
    return {'quarter':selected,'quarters':quarters,'rows':visible,'version':settings[TARGETS_KEY].version if TARGETS_KEY in settings else 0,
            'can_edit':user.role in ('admin','superadmin'),'previous_quarter':prior,'can_copy':prior in quarters,
            'exists':selected in quarters,
            'available_names':known_names(db) if user.role in ('admin','superadmin') else []}


class TargetRow(StrictBody):
    owner: str = Field(min_length=1,max_length=100)
    target: Decimal | None = Field(default=None,gt=0,le=1000000000000,max_digits=18,decimal_places=2)


class TargetUpdate(VersionBody):
    rows: list[TargetRow] = Field(min_length=1,max_length=5000)


@app.put('/api/bonus-config/targets/{quarter}')
def put_targets(quarter: Quarter, body:TargetUpdate, user=Depends(admin), db:Session=Depends(database)):
    settings = all_settings(db)
    rows = target_rows(db,settings)
    if quarter not in target_quarters(settings, rows):
        raise HTTPException(409,'本季度尚未建立，请先沿袭上一季度目标')
    names = [r.owner.strip() for r in body.rows]
    if len(set(names))!=len(names) or any(r.owner!=r.owner.strip() for r in body.rows):
        raise HTTPException(422,'BD姓名重复或含有首尾空格')
    allowed = {r['BD姓名'] for r in rows if r['季度']==quarter}
    if set(names)-allowed:
        raise HTTPException(422,'请通过新增BD入口维护人员')
    if {r['BD姓名'] for r in rows if r['季度']==quarter}-set(names):
        raise HTTPException(422,'不能删除本季度已有BD目标，请保留原有姓名')
    originals = {r['BD姓名']: r for r in rows if r['季度'] == quarter}
    updated = [r for r in rows if r['季度'] != quarter]
    for row in body.rows:
        current = {**originals[row.owner], '直接营收目标': str(row.target) if row.target is not None else None}
        updated.append(current)
    save_targets(db,settings,updated,body.version,quarter=quarter)
    audit(db,user.username,f'修改{quarter}直接营收目标：{len(body.rows)}位BD')
    db.commit()
    return get_targets(quarter,user,db)


@app.post('/api/bonus-config/targets/{quarter}/inherit')
def inherit_targets(quarter:Quarter,body:VersionBody,user=Depends(admin),db:Session=Depends(database)):
    settings=all_settings(db)
    rows=target_rows(db,settings)
    if quarter in target_quarters(settings, rows):
        raise HTTPException(409,'本季度已有目标，不能重复沿袭覆盖')
    prior=previous_quarter(quarter)
    previous={r['BD姓名']:r.get('直接营收目标') for r in rows if r['季度']==prior}
    if prior not in target_quarters(settings, rows):
        raise HTTPException(409,f'请先建立{prior}目标')
    members=setting_payload(settings,TARGETS_KEY).get('memberships',{})
    names=sorted(name for name in set(known_names(db))|set(previous)|set(members) if target_member_active(settings,name,quarter))
    added=[{'BD姓名':name, '季度':quarter, '直接营收目标':previous.get(name)} for name in names]
    save_targets(db,settings,rows+added,body.version,quarter=quarter)
    audit(db,user.username,f'沿袭{prior}目标至{quarter}：{len(added)}位BD；未有原值的姓名保留待填写')
    db.commit()
    return get_targets(quarter,user,db)


class TargetMember(VersionBody):
    owner: str = Field(min_length=1,max_length=100)


@app.post('/api/bonus-config/targets/{quarter}/members')
def add_target_member(quarter:Quarter,body:TargetMember,user=Depends(admin),db:Session=Depends(database)):
    return change_target_member(quarter,body,user,db,True)


@app.delete('/api/bonus-config/targets/{quarter}/members')
def delete_target_member(quarter:Quarter,body:TargetMember,user=Depends(admin),db:Session=Depends(database)):
    return change_target_member(quarter,body,user,db,False)


def change_target_member(quarter,body,user,db,adding):
    name=body.owner.strip()
    if not name or name!=body.owner:
        raise HTTPException(422,'BD姓名不能为空或含首尾空格')
    settings=all_settings(db)
    rows=target_rows(db,settings)
    present=any(r['季度']==quarter and r['BD姓名']==name for r in rows)
    if adding and present:
        raise HTTPException(409,'该季度已存在此BD')
    if not adding and not present:
        raise HTTPException(404,'该季度不存在此BD')
    quarters=set(target_quarters(settings,rows))|{quarter}
    members=setting_payload(settings,TARGETS_KEY).get('memberships',{})
    events={q:v for q,v in members.get(name,{}).items() if q<quarter}
    if adding and not events and not any(r['BD姓名']==name and r['季度']<quarter for r in rows) and quarter>'2000Q1':
        events['2000Q1']=False
    events[quarter]=adding
    members={**members,name:events}
    if adding:
        existing={(r['BD姓名'],r['季度']) for r in rows}
        rows += [{'BD姓名':name,'季度':q,'直接营收目标':None} for q in sorted(quarters)
                 if q>=quarter and (name,q) not in existing]
    else:
        rows=[r for r in rows if r['BD姓名']!=name or r['季度']<quarter]
    # Preserve empty future quarters after removing their last member.
    payload=setting_payload(settings,TARGETS_KEY)
    save_setting(db,TARGETS_KEY,json.dumps({**payload,'sheet':'奖金汇总表',
        'columns':['BD姓名','季度','直接营收目标'],'rows':rows,'quarters':sorted(quarters),'memberships':members},ensure_ascii=False),body.version)
    audit(db,user.username,f'{"新增" if adding else "移除"}目标BD：{name}，自{quarter}及后续季度生效')
    db.commit()
    return get_targets(quarter,user,db)


@app.get('/api/bonus-config/plans')
def get_plans(year: Year | None=None,user=Depends(current_user),db:Session=Depends(database)):
    settings=all_settings(db)
    years=sorted([int(k[len(YEAR_PLAN_PREFIX):]) for k in settings if k.startswith(YEAR_PLAN_PREFIX)],reverse=True)
    selected=year or (years[0] if years else date.today().year)
    from backend.bonus_rules import order_year
    records=list(iter_orders(owner=user.name.strip() if user.role=='bd' else None))
    payment_years=sorted({y for r in records if (y:=order_year(r['values'])) is not None})
    missing_years=[y for y in payment_years if year_plan_key(y) not in settings]
    key=year_plan_key(selected)
    rows=[dict(r) for r in setting_payload(settings,key).get('rows',[])]
    from collections import Counter
    configured={r['所购服务'] for r in rows}
    missing_services=Counter(r['values'].get('付费项目','') for r in records if order_year(r['values'])==selected and r['values'].get('付费项目','') not in configured|{'团队VIP'})
    return {'year':selected,'years':years,'rows':rows,'version':settings[key].version if key in settings else 0,
            'exists':key in settings,'can_edit':user.role in ('admin','superadmin'),'previous_year':selected-1,'next_year':selected+1,'can_copy_next':year_plan_key(selected+1) in settings,'can_copy':year_plan_key(selected-1) in settings,'payment_years':payment_years,'missing_years':missing_years,'missing_services':[{'service':s,'count':n} for s,n in missing_services.most_common()]}


class ServiceRow(StrictBody):
    service:str=Field(min_length=1,max_length=200)
    enabled:StrictBool | None


class PlanUpdate(VersionBody):
    rows:list[ServiceRow]=Field(min_length=1,max_length=5000)


@app.put('/api/bonus-config/plans/{year}')
def put_plan(year:Year,body:PlanUpdate,user=Depends(admin),db:Session=Depends(database)):
    settings=all_settings(db)
    key=year_plan_key(year)
    names=[r.service.strip() for r in body.rows]
    if len(set(names))!=len(names) or any(r.service!=r.service.strip() for r in body.rows):
        raise HTTPException(422,'奖金来源名称重复或含有首尾空格')
    if '团队VIP' in names:
        raise HTTPException(422,'团队VIP使用独立金额公式，请通过是否计发提成的齿轮维护')
    original={r['所购服务'] for r in setting_payload(settings,key).get('rows',[])}
    if original-set(names):
        raise HTTPException(422,'不能删除已有奖金来源，可将是否计入提成范围设为否')
    rows=[{'所购服务':r.service,'是否计入提成范围':None if r.enabled is None else '是' if r.enabled else '否'} for r in body.rows]
    save_setting(db,key,json.dumps({'year':year,'rows':rows},ensure_ascii=False),body.version)
    audit(db,user.username,f'修改{year}年奖金方案：{len(rows)}项来源')
    db.commit()
    return get_plans(year,user,db)


@app.post('/api/bonus-config/plans/{year}/inherit')
def inherit_plan(year:Year,body:VersionBody,user=Depends(admin),db:Session=Depends(database),source_year:Year|None=None):
    settings=all_settings(db)
    key=year_plan_key(year)
    if key in settings:
        raise HTTPException(409,'本年度已有方案，不能重复沿袭覆盖')
    if body.version!=0:
        raise HTTPException(409,'年份版本已变化，请重新加载')
    source=source_year if source_year is not None else year-1
    if source not in (year-1,year+1):
        raise HTTPException(422,'请选择相邻年份方案')
    previous=setting_payload(settings,year_plan_key(source))
    if not previous.get('rows'):
        raise HTTPException(409,f'请先建立{source}年奖金方案')
    save_setting(db,key,json.dumps({'year':year,'rows':previous['rows']},ensure_ascii=False),0)
    audit(db,user.username,f'沿袭{source}年奖金方案至{year}年：{len(previous["rows"])}项来源')
    db.commit()
    return get_plans(year,user,db)


@app.get('/api/bonus-config/constants')
def get_constants(user=Depends(current_user),db:Session=Depends(database)):
    from backend.sales_formulas import global_parameters
    settings=all_settings(db)
    return {'parameters':global_parameters(settings),'version':settings[GLOBAL_KEY].version if GLOBAL_KEY in settings else 0,'can_edit':user.role in ('admin','superadmin')}


class ConstantUpdate(VersionBody):
    parameters:dict=Field(min_length=1,max_length=10)


@app.put('/api/bonus-config/constants')
def put_constants(body:ConstantUpdate,user=Depends(admin),db:Session=Depends(database)):
    from backend.sales_formulas import PeriodInputs,global_parameters
    settings=all_settings(db)
    if set(body.parameters)-set(COMMON_FIELDS) or any(v is None or isinstance(v,bool) for v in body.parameters.values()):
        raise HTTPException(422,'只能修改已列出的公共常数，不能为空或布尔值')
    try:
        updated=PeriodInputs.model_validate({**global_parameters(settings),**body.parameters}).model_dump(mode='json')
    except ValidationError as exc:
        raise HTTPException(422,'金额必须非负，提点必须在0至100之间') from exc
    updated.pop('target',None)
    save_setting(db,GLOBAL_KEY,json.dumps(updated,ensure_ascii=False),body.version)
    audit(db,user.username,'修改公共常数：'+','.join(body.parameters))
    db.commit()
    return get_constants(user,db)
