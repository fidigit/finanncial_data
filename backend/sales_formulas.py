"""Fixed sales formulas with shared versioned parameters and BD-quarter targets."""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import (app, database, current_user, admin, SystemSetting, audit,
                         commission_snapshot, project_row, service_key, record_key, with_display_note)
from backend.bonus_v2 import save_setting
from backend.bonus_rules import GLOBAL_KEY, shared_service_rule, source_target, target_entry, order_year, YEAR_PLAN_PREFIX
from backend.sales_expression import SPECS, RULE_PARAMETERS, FormulaError, evaluate_formula, parse_formula


class PeriodInputs(BaseModel):
    target: Decimal | None = Field(default=None, gt=0, le=1000000000000)
    threshold: Decimal = Field(default=Decimal('30000'), ge=0, le=1000000000000)
    vip_minimum: Decimal = Field(default=Decimal('1680'), ge=0, le=1000000000000)
    include_ineligible: StrictBool = True
    self_rate: Decimal = Field(default=Decimal('10'), ge=0, le=100)
    self_excess: Decimal = Field(default=Decimal('15'), ge=0, le=100)
    market_rate: Decimal = Field(default=Decimal('8'), ge=0, le=100)
    market_excess: Decimal = Field(default=Decimal('13'), ge=0, le=100)
    partner_rate: Decimal = Field(default=Decimal('5'), ge=0, le=100)
    partner_excess: Decimal = Field(default=Decimal('8'), ge=0, le=100)
    renewal_rate: Decimal = Field(default=Decimal('3'), ge=0, le=100)


class OrderInputs(BaseModel):
    split_amount: Decimal | None = Field(default=None, ge=0, le=1000000000000)
    split_total: Decimal | None = Field(default=None, gt=0, le=1000000000000)
    shared_names: str = Field(default='', max_length=200)
    association: bool | None = None
    association_name: str = Field(default='', max_length=200)
    promotion_amount: Decimal | None = Field(default=None, ge=0, le=1000000000000)
    market_recommended: bool | None = None
    market_name: str = Field(default='', max_length=100)
    channel: Literal['auto', 'self', 'market', 'partner'] = 'auto'
    finance_time: datetime | None = None
    finance_service: str = Field(default='', max_length=200)
    finance_amount: Decimal | None = Field(default=None, ge=0, le=1000000000000)
    payment_method: str = Field(default='', max_length=100)
    refund_date: date | None = None
    refund_order: str = Field(default='', max_length=100)
    original_order_date: date | None = None
    refund_service: str = Field(default='', max_length=200)
    refund_amount: Decimal | None = Field(default=None, ge=0, le=1000000000000)
    special_note: str = Field(default='', max_length=1000)
    finance_note: str = Field(default='', max_length=1000)


PERIOD_FIELDS = [
    ('target', 'W 当季度目标（元）', 'number'), ('threshold', 'X 适用提点 · 公式常数（奖金计算基数合计下限，元）', 'number'),
    ('vip_minimum', 'R 所购服务是否计发提成 · 公式常数（团队VIP订单收款金额下限，元）', 'number'), ('include_ineligible', 'T 累计营收 / X 适用提点 · 计算口径（是否包含不计发提成订单）', 'boolean'),
    ('self_rate', 'X 适用提点 / AA 提成计算2 · 自拓、目标内（%）', 'number'), ('self_excess', 'X 适用提点 / AA 提成计算2 · 自拓、超额（%）', 'number'),
    ('market_rate', 'X 适用提点 / AA 提成计算2 · 市场推荐、目标内（%）', 'number'), ('market_excess', 'X 适用提点 / AA 提成计算2 · 市场推荐、超额（%）', 'number'),
    ('partner_rate', 'X 适用提点 / AA 提成计算2 · 协会/合伙人、目标内（%）', 'number'), ('partner_excess', 'X 适用提点 / AA 提成计算2 · 协会/合伙人、超额（%）', 'number'),
    ('renewal_rate', 'X 适用提点 · 续费（%）', 'number'),
]
ORDER_FIELDS = [
    ('split_amount', '数据源-市场+销售 拆分订单 · 当前BD姓名列（金额，元）', 'number'), ('split_total', '数据源-市场+销售 拆分订单 · I 总计（元）', 'number'),
    ('shared_names', 'I 业务备注（与其他BD进行拆分订单）', 'text'), ('association', 'L 是否存在协会或合伙人推荐的情况？（是/否）', 'tri'),
    ('association_name', 'M 协会/合伙人名称', 'text'), ('promotion_amount', 'N 协会/合伙人推广金额', 'number'),
    ('market_recommended', 'O 是否渠道来自市场（如有提成，销售按8%）', 'tri'), ('market_name', '市场渠道 · BD姓名（网页补充项，原表无独立列）', 'text'),
    ('channel', 'U 成单渠道', 'channel'), ('finance_time', 'AC 交易时间', 'datetime-local'),
    ('finance_service', 'AD 商品', 'text'), ('finance_amount', 'AF 财务复核-订单金额', 'number'),
    ('payment_method', 'AG 支付方式', 'text'), ('refund_date', 'AH 退款时间', 'date'),
    ('refund_order', 'AI 退款订单号', 'text'), ('original_order_date', 'AJ 订单所属时间', 'date'),
    ('refund_service', 'AK 退款商品服务', 'text'), ('refund_amount', 'AM 退款金额', 'number'),
    ('special_note', 'Q 特殊情况备注', 'text'), ('finance_note', 'AS 财务备注', 'text'),
]
FORMULAS = [
    {'field': 'enabled', 'title': '是否计发提成', 'expression': 'S人工确认优先；否则团队VIP：H >= VIP门槛；其他服务：查销售服务规则R。未知规则=待配置', 'variables': ['F所购服务、H订单金额', 'VIP门槛：全局参数，默认1680元', 'R服务规则：付款年份对应的奖金方案', 'S人工覆盖：确认/修改'], 'excel': 'R / S'},
    {'field': 'shared_bd', 'title': '共享订单', 'expression': '显示已确认参与人/拆单说明；不根据相似订单擅自推定分摊比例', 'variables': ['I共享参与人：订单变量', 'C订单号：来源只读；同订单多行保留'], 'excel': 'I / AO:AS（自动查重待数据源接入）'},
    {'field': 'allocation_ratio', 'title': '分摊比例', 'expression': 'J = 已确认比例优先；否则 本人分摊金额 / 分摊总金额；无拆分信息=100%；共享但缺分摊依据=待配置', 'variables': ['拆分表本人金额、分摊总额：订单变量', 'J直接确认比例：确认/修改（0–100%）', 'I共享参与人'], 'excel': 'J / 拆分订单表'},
    {'field': 'bonus_basis', 'title': '奖金计算基数', 'expression': 'K = ROUND(H × J, 2)；已有人工基数覆盖优先并标记', 'variables': ['H订单金额、J分摊比例', '人工基数覆盖：确认/修改，可清空恢复公式'], 'excel': 'K'},
    {'field': 'market_bd', 'title': '市场渠道', 'expression': '显示订单变量中的市场推荐BD姓名；O确认是否市场推荐，用于推导U渠道', 'variables': ['O是否市场推荐、市场BD姓名：订单变量', '来源订单渠道信息；单填姓名不自动确认推荐资格'], 'excel': 'O / U'},
    {'field': 'referral', 'title': '转介绍', 'expression': 'L为是时显示协会/合伙人及M名称；否则保留来源转介绍信息；客户推荐不自动套协会提点', 'variables': ['L是否协会/合伙人推荐、M名称：订单变量', 'U成单渠道：可明确确认；N推广金额仅核对'], 'excel': 'L / M / N / U'},
    {'field': 'revenue_total', 'title': '累计营收', 'expression': 'T = 同BD同季度按付款时间排序，截至本单的K累计；先计算全季度，再搜索/筛选/分页', 'variables': ['BD、季度、完整付款时间、K基数', '累计口径：默认包括不计提订单，保留来源重复行', '关闭包含不计提订单时，未知资格会阻断累计'], 'excel': 'T'},
    {'field': 'confirmed_rate', 'title': '适用提点（分段提点）', 'expression': '未计提或全季度基数<门槛：0；续费：续费率；首购：U渠道基础/超额率，跨档显示两段', 'variables': ['W季度目标按BD季度；起提门槛、各渠道提点为全局参数', 'S资格、G首购/续费、U渠道、T累计、K本单基数', 'V超额、Z跨档：后台自动计算，不手工赋值', '人工提点覆盖：确认/修改，可清空恢复公式'], 'excel': 'X / U / V / W / Z'},
    {'field': 'bonus', 'title': '奖金', 'expression': '目标内基数=min(K,max(W-本单前累计,0))；超额基数=K-目标内基数；AB=两段基数分别×提点之和；续费=K×续费率；不计提/未起提=0', 'variables': ['K、S、G、U、T、W、季度总基数、门槛、各提点', 'Y普通提成、AA分段提成、Z跨档：自动中间量', '人工奖金覆盖优先并标记，不自动发放；计算保留精度，页面显示2位'], 'excel': 'Y / Z / AA / AB'},
    {'field': 'is_refunded', 'title': '是否退款', 'expression': '人工确认优先；否则AM退款金额>0为是，明确为0则否，缺失为待确认；不自动冲减AB', 'variables': ['AH退款日期、AI订单号、AJ原订单时间、AK商品、AM金额：订单变量', 'AL退款期间由AH生成；发放状态仍为人工确认'], 'excel': 'AH:AM'},
]


def setting_key(kind, *parts):
    return 'sales_' + kind + '_' + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:40]


def decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def stored(settings, key, default):
    setting = settings.get(key)
    return json.loads(setting.value) if setting else default


def global_parameters(settings):
    defaults = PeriodInputs().model_dump(mode='json')
    return {key: value for key, value in {**defaults, **stored(settings, GLOBAL_KEY, {})}.items() if key in defaults and key != 'target'}


def effective_period(settings, owner, quarter):
    # Legacy per-BD constants remain archived but never override shared rules.
    old = stored(settings, setting_key('period', owner, quarter), {})
    entry = target_entry(settings, owner, quarter)
    target = entry.get('直接营收目标') if entry is not None else old.get('target')
    return {**global_parameters(settings), 'target': target}


def calculate_sales(records, expressions=None):
    """Execute the same five editable rules for list, preview and export."""
    expressions = {**{key: spec['default'] for key, spec in SPECS.items()}, **(expressions or {})}
    groups = defaultdict(list)
    def execute(item, column, context):
        try:
            return evaluate_formula(column, expressions[column], context)
        except FormulaError as exc:
            error = {'column': column, 'message': str(exc)}
            if error not in item['formula_errors']:
                item['formula_errors'].append(error)
                item['problems'].append(f"{column}公式：{exc}")
            return None
    for item in records:
        row, p, v = item['row'], item['period'], item['variables']
        c = row['confirmation']
        item['problems'], item['formula_errors'] = [], []
        problems = item['problems']
        amount = decimal(row['order_amount'])
        rule = item['rule']
        service_eligible = (amount >= decimal(p['vip_minimum']) if amount is not None else None) if row['service'] == '团队VIP' else rule.get('enabled')
        item['service_eligible'] = service_eligible
        context = {'A': row['owner'], 'C': row.get('order_no', ''), 'F': row['service'], 'G': row['purchase_type'], 'H': amount,
                   'R': service_eligible, '团队VIP金额下限': decimal(p['vip_minimum']),
                   '所购服务': row['service'], '订单金额': amount, '服务规则查询结果': rule.get('enabled')}
        row['enabled'] = c.get('enabled') if c.get('enabled') is not None else execute(item, 'S', context)
        context['S'] = row['enabled']
        row['market_recommended'] = v.get('market_recommended') if v.get('market_recommended') is not None else '市场同事推荐' in item['source']
        row['shared_bd'] = v.get('shared_names') or row['shared_bd']
        row['market_bd'] = v.get('market_name') or row['market_bd']
        row['market_pending'] = bool(v.get('market_recommended') or row['market_pending']) and not row['market_bd']
        if v.get('association') is True:
            row['referral'] = '协会/合伙人' + ('：' + v['association_name'] if v.get('association_name') else '')
        a, total = decimal(v.get('split_amount')), decimal(v.get('split_total'))
        split_ratio = None
        if a is not None and total is not None and total > 0 and a <= total:
            split_ratio = a / total
        elif a is None and total is None and not row['shared_bd']:
            split_ratio = Decimal(1)
        context.update({'拆分订单比例': split_ratio, '本人分摊金额': a, '订单分摊总金额': total, '存在共享信息': bool(row['shared_bd'])})
        ratio = decimal(c.get('allocation_ratio')) if c.get('allocation_ratio') is not None else execute(item, 'J', context)
        context['J'] = ratio
        context['分摊比例'] = ratio
        if ratio is None:
            problems.append('共享订单需补齐分摊金额/总额或确认比例')
        basis = decimal(c.get('bonus_basis')) if c.get('bonus_basis') is not None else execute(item, 'K', context)
        if basis is not None and basis < 0: basis = None
        if basis is None: problems.append('缺少有效订单金额或分摊依据')
        context['K'] = basis
        row['allocation_ratio'] = str(ratio) if ratio is not None else None
        row['bonus_basis'] = str(basis) if basis is not None else None
        row['note'] = '；'.join(filter(None, [row['note'], v.get('special_note'), v.get('finance_note')]))
        if c.get('is_refunded') is None and v.get('refund_amount') is not None:
            row['is_refunded'] = decimal(v['refund_amount']) > 0
        channel = v.get('channel', 'auto')
        if channel == 'auto':
            source, association, market = item['source'], v.get('association'), v.get('market_recommended')
            if association is True or (association is None and any(x in source for x in ('协会推荐', '合伙人推荐'))): channel = 'partner'
            elif market is True or (market is None and '市场同事推荐' in source): channel = 'market'
            elif '客户推荐' in source and association is None: channel = 'pending'
            else: channel = 'self'
        try:
            stamp = datetime.fromisoformat(item['paid_at'])
            if stamp.tzinfo is not None: raise ValueError('timezone not supported')
        except (ValueError, TypeError): stamp = None
        item.update(basis=basis, channel=channel, stamp=stamp, context=context)
        groups[(row['owner'].strip(), row['quarter'])].append(item)
    for (owner, quarter), group in groups.items():
        p = group[0]['period']
        bad_group = any(i['basis'] is None or i['stamp'] is None or (not p['include_ineligible'] and i['row']['enabled'] is None) for i in group) or not quarter
        def included(i): return i['basis'] if p['include_ineligible'] or i['row']['enabled'] else Decimal(0)
        quarter_total = None if bad_group else sum((included(i) for i in group), Decimal(0))
        accumulated = Decimal(0)
        for item in sorted(group, key=lambda i: (i['stamp'] or datetime.max, i['row']['row_id'])):
            row, basis, channel, context = item['row'], item['basis'], item['channel'], dict(item['context'])
            c, problems = row['confirmation'], item['problems']
            before = accumulated
            context.update({'前序累计': before, '本单计入基数': included(item) if not bad_group else None})
            accumulated = execute(item, 'T', context) if not bad_group else None
            target = decimal(p['target'])
            over_target = accumulated > target if accumulated is not None and target is not None else None
            base_parameter = decimal(p.get(channel + '_rate'))
            excess_parameter = decimal(p.get(channel + '_excess'))
            context.update({'T': accumulated, 'W': target, 'V': over_target,
                            'U': {'self': '自拓', 'market': '市场推荐', 'partner': '协会/合伙人', 'pending': '待确认'}[channel],
                            '季度基数合计': quarter_total, '起提门槛': decimal(p['threshold']),
                            '是否计发提成': row['enabled'], '购买性质': row['purchase_type'], '累计超过季度目标': over_target,
                            '续费提点': decimal(p['renewal_rate']) / 100,
                            '目标内提点': base_parameter / 100 if base_parameter is not None else None,
                            '超额提点': excess_parameter / 100 if excess_parameter is not None else None})
            rate = execute(item, 'X', context)
            bonus = inside = excess = segmented_bonus = None
            rate_label, crossing = '待配置', False
            if bad_group and rate != 0:
                rate = None
                problems.append('本季度存在无效金额/时间/资格，累计待核对')
            if rate is not None:
                bonus = basis * rate if basis is not None else Decimal(0) if rate == 0 else None
                if row['purchase_type'] in ('首购', '新客') and basis is not None and target is not None and accumulated is not None:
                    # AA uses T-W and K; modifications to T therefore affect this order too.
                    inside = min(basis, max(target - (accumulated - basis), Decimal(0)))
                    excess = basis - inside
                    crossing = inside > 0 and excess > 0
                    low = execute(item, 'X', {**context, 'V': False, '累计超过季度目标': False}) if inside else Decimal(0)
                    high = execute(item, 'X', {**context, 'V': True, '累计超过季度目标': True}) if excess else Decimal(0)
                    if low is not None and high is not None:
                        segmented_bonus = inside * low + excess * high
                        bonus = segmented_bonus
                        rate_label = f'{low * 100}% / {high * 100}%' if crossing else f'{rate * 100}%'
                    else:
                        bonus = None
                elif row['purchase_type'] not in ('首购', '新客', '续费') and expressions['X'] == SPECS['X']['default'] and rate != 0:
                    rate = bonus = None
                    problems.append('首购/续费类型未确认')
            if rate is None:
                if row['enabled'] is None: problems.append(row.get('rule_note') or '待配置服务计提规则或本单确认')
                elif target is None and row['purchase_type'] != '续费': problems.append('请配置该BD该季度的目标W')
                elif channel == 'pending': problems.append('客户推荐需确认计奖渠道U')
            overrides = [name for key, name in [('enabled', '计提资格'), ('allocation_ratio', '分摊比例'), ('bonus_basis', '基数'), ('confirmed_rate', '提点'), ('bonus', '奖金')] if c.get(key) is not None]
            manual_rate = decimal(c.get('confirmed_rate'))
            if manual_rate is not None:
                rate, rate_label = manual_rate, f'{manual_rate * 100}%（人工）'
                if row['enabled'] is True and quarter_total is not None and quarter_total >= decimal(p['threshold']) and basis is not None:
                    bonus = basis * rate
                elif row['enabled'] is False or (quarter_total is not None and quarter_total < decimal(p['threshold'])):
                    rate = bonus = Decimal(0)
                    rate_label = '0%（未满足计提条件）'
            if c.get('bonus') is not None: bonus = decimal(c['bonus'])
            if rate_label == '待配置' and rate is not None: rate_label = f'{rate * 100}%'
            row.update(revenue_total=str(accumulated) if accumulated is not None else None,
                       confirmed_rate=str(rate) if rate is not None else None, bonus=str(bonus) if bonus is not None else None, rate_display=rate_label,
                       calculation={'service_eligible': item['service_eligible'], 'channel': channel, 'quarter_total': str(quarter_total) if quarter_total is not None else None,
                                    'target': str(target) if target is not None else None, 'before': str(before) if before is not None and not bad_group else None,
                                    'inside_basis': str(inside) if inside is not None else None, 'excess_basis': str(excess) if excess is not None else None,
                                    'crossing': crossing, 'over_target': over_target,
                                    'ordinary_bonus': str(basis * rate) if basis is not None and rate is not None else None,
                                    'segmented_bonus': str(segmented_bonus) if segmented_bonus is not None else None,
                                    'problems': list(dict.fromkeys(problems)), 'overrides': overrides, 'formula_errors': item['formula_errors'],
                                    'custom_formulas': [key for key, expression in expressions.items() if expression != SPECS[key]['default']],
                                    'finance_difference': str(decimal(item['variables']['finance_amount']) - decimal(row['order_amount'])) if item['variables'].get('finance_amount') is not None and decimal(row['order_amount']) is not None else None,
                                    'refund_period': str(item['variables'].get('refund_date') or '')[:7],
                                    'payment_period': str(item['variables'].get('finance_time') or item['paid_at'])[:7]})
    return [i['row'] for i in records]


def sales_response(db, user, page, page_size, search, quarter, owner, expression_overrides=None, period_overrides=None, global_overrides=None):
    snapshot = commission_snapshot(db, user, category='sales', page_size=1000000)
    selected = commission_snapshot(db, user, category='sales', page=page, page_size=page_size, search=search, quarter=quarter, owner=owner)
    settings = {s.key: s for s in db.scalars(select(SystemSetting))}
    records, rules = [], {}
    for raw in snapshot['rows']:
        values = raw['values']
        name, period, service = values.get('BD姓名', '').strip(), values.get('季度', ''), values.get('付费项目', '')
        key = record_key(raw)
        confirmation_setting = settings.get(key)
        confirmation = {**json.loads(confirmation_setting.value), 'version': confirmation_setting.version} if confirmation_setting else None
        period_inputs = {**effective_period(settings, name, period), **(global_overrides or {}), **(period_overrides or {}).get((name, period), {})}
        rule = shared_service_rule(settings, service, values.get('订单金额'), period_inputs['vip_minimum'], order_year(values))
        if rule:
            rules[service] = rule
        row = project_row(raw, rule, confirmation)
        records.append({'row': row, 'period': period_inputs,
                        'variables': stored(settings, setting_key('order', key), OrderInputs().model_dump(mode='json')),
                        'rule': rule, 'source': ' '.join([values.get('订单来源', ''), values.get('订单来源补充', '')]), 'paid_at': values.get('付费时间', '')})
    # All rule structures are fixed; old free-expression drafts are retained but inactive.
    expressions = {key: spec['default'] for key, spec in SPECS.items()}
    calculated = {r['row_id']: r for r in calculate_sales(records, expressions)}
    return {'rows': [with_display_note(calculated[r['row_id']]) for r in selected['rows']], 'total': selected['total'], 'options': selected['options'],
            'pending_services': [s for s in selected['options']['projects'] if s != '团队VIP' and rules.get(s,{}).get('enabled') is None],
            'can_edit': user.role in ('admin', 'superadmin'), 'can_edit_note': True, 'rules': rules, 'formulas': FORMULAS}


def require_scope(db, user, owner, quarter, key=''):
    scoped = commission_snapshot(db, user, category='sales', page_size=1000000, owner=owner, quarter=quarter)
    rows = [r for r in scoped['rows'] if r['values'].get('BD姓名', '').strip() == owner and r['values'].get('季度') == quarter]
    if not rows:
        raise HTTPException(404, '该销售BD/季度不存在或无权限')
    if key and not any(record_key(r) == key for r in rows):
        raise HTTPException(404, '订单不存在、来源已变化或无权限')
    return rows


@app.get('/api/sales-formulas/inputs')
def get_inputs(owner: str = Query(min_length=1, max_length=100), quarter: str = Query(min_length=1, max_length=30), record: str = '', user=Depends(current_user), db: Session = Depends(database)):
    rows = require_scope(db, user, owner, quarter, record)
    settings = {s.key: s for s in db.scalars(select(SystemSetting))}
    rk = setting_key('order', record)
    chosen = next((r for r in rows if record_key(r) == record), None)
    period = effective_period(settings, owner, quarter)
    variables = stored(settings, rk, OrderInputs().model_dump(mode='json'))
    service = chosen['values'].get('付费项目', '') if chosen else ''
    sk = service_key(service)
    rule = shared_service_rule(settings, service, chosen['values'].get('订单金额') if chosen else None, period['vip_minimum'], order_year(chosen['values']) if chosen else None)
    trace = None
    if chosen:
        response = sales_response(db, user, 1, 1000000, '', quarter, owner)
        trace = next(r for r in response['rows'] if r['record_key'] == record)
    return {'owner': owner, 'quarter': quarter, 'period': period, 'period_version': settings[GLOBAL_KEY].version if GLOBAL_KEY in settings else 0, 'parameter_scope': 'global', 'target_scope': 'bd_quarter',
            'variables': variables, 'order_version': settings[rk].version if rk in settings else 0,
            'orders': [{'key': record_key(r), 'label': f"{r['values'].get('订单号') or '无订单号'} · 行{r['row_id']} · {r['values'].get('付费项目')}"} for r in rows],
            'source': chosen['values'] if chosen else {}, 'trace': trace, 'service': service, 'rule': rule,
            'service_version': settings[sk].version if sk in settings else 0,
            'period_fields': PERIOD_FIELDS, 'order_fields': ORDER_FIELDS, 'formulas': FORMULAS, 'can_edit': user.role in ('admin', 'superadmin')}


class SaveInputs(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    quarter: str = Field(min_length=1, max_length=30)
    record: str = Field(default='', max_length=80)
    version: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)
    period: PeriodInputs | None = None
    variables: OrderInputs | None = None


@app.put('/api/sales-formulas/inputs/{kind}')
def save_inputs(kind: Literal['period', 'order'], body: SaveInputs, user=Depends(admin), db: Session = Depends(database)):
    require_scope(db, user, body.owner, body.quarter, body.record)
    if not body.note.strip():
        raise HTTPException(422, '请填写修改依据')
    if kind == 'period':
        if body.period is None:
            raise HTTPException(422, '缺少季度参数')
        common = body.period.model_dump(mode='json')
        target = common.pop('target')
        save_setting(db, GLOBAL_KEY, json.dumps(common, ensure_ascii=False), body.version)
        target_key = setting_key('period', body.owner, body.quarter)
        old_target = db.get(SystemSetting, target_key)
        save_setting(db, target_key, json.dumps({**(json.loads(old_target.value) if old_target else {}), 'target': target}, ensure_ascii=False), old_target.version if old_target else 0)
        audit(db, user.username, f'修改全局奖金参数及{body.owner}/{body.quarter}直接营收目标；{body.note}'[:200])
        db.commit()
        return {'ok': True}
    else:
        if not body.record or body.variables is None:
            raise HTTPException(422, '请选择订单并填写变量')
        v = body.variables
        if v.split_amount is not None and v.split_total is not None and v.split_amount > v.split_total:
            raise HTTPException(422, '本人分摊金额不能大于订单分摊总金额')
        key, payload = setting_key('order', body.record), v
    save_setting(db, key, json.dumps({**payload.model_dump(mode='json'), '_change_note': body.note}, ensure_ascii=False), body.version)
    audit(db, user.username, f'销售公式{kind}：{body.owner}/{body.quarter}；{body.note}'[:200])
    db.commit()
    return {'ok': True}


class SalesServiceBody(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    quarter: str = Field(min_length=1, max_length=30)
    record: str = Field(min_length=1, max_length=80)
    enabled: bool
    version: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=500)


@app.put('/api/sales-formulas/service')
def save_sales_service(body: SalesServiceBody, user=Depends(admin), db: Session = Depends(database)):
    rows = require_scope(db, user, body.owner, body.quarter, body.record)
    raw = next(r for r in rows if record_key(r) == body.record)
    service = raw['values'].get('付费项目', '')
    if service == '团队VIP':
        raise HTTPException(422, '团队VIP按全局金额门槛判断；单笔例外请使用确认/修改')
    if not body.note.strip():
        raise HTTPException(422, '请填写规则依据')
    if db.scalar(select(SystemSetting.key).where(SystemSetting.key.like(YEAR_PLAN_PREFIX+'%')).limit(1)):
        raise HTTPException(409, '请在奖金方案中选择年份并维护本年度规则')
    save_setting(db, service_key(service), json.dumps({'enabled': body.enabled, 'note': body.note}, ensure_ascii=False), body.version)
    audit(db, user.username, f'全局服务规则：{service}；{body.note}'[:200])
    db.commit()
    return {'ok': True}


class FormulaEditBody(BaseModel):
    expression: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=0)
    note: str = Field(default='', max_length=500)


def formula_definition(db, column):
    if column not in SPECS:
        raise HTTPException(404, '公式列不存在')
    spec = SPECS[column]
    saved = db.get(SystemSetting, setting_key('formula', column))
    config = json.loads(saved.value) if saved else {}
    expression = spec['default']
    return {'column': column, 'title': spec['title'], 'expression': expression,
            'default_expression': spec['default'], 'version': saved.version if saved else 0,
            'variables': [{'name': name, 'description': description} for name, description in spec['variables'].items()],
            'result': spec['result'], 'custom': expression != spec['default'],
            'editor_mode': 'fixed_parameters' if RULE_PARAMETERS[column] else 'fixed',
            'editable_parameters': list(RULE_PARAMETERS[column]),
            'updated_by': config.get('actor'), 'updated_at': config.get('updated_at'), 'note': config.get('note', '')}


@app.get('/api/sales-formulas/definitions')
def formula_definitions(user=Depends(current_user), db: Session = Depends(database)):
    return {'definitions': [formula_definition(db, key) for key in SPECS],
            'can_edit': user.role in ('admin', 'superadmin'), 'scope': '公式及公共参数统一适用全部BD和季度；仅直接营收目标按BD、季度读取',
            'functions': [],
            'help': '计算结构固定，不接受自由公式改写。仅可修改每列声明的参数；分摊比例、奖金计算基数没有额外规则参数。公共参数全局保存，直接营收目标按BD和季度读取；单笔人工确认优先。'}


def trial_formula(db, user, column, expression):
    try:
        parse_formula(column, expression)
    except FormulaError as exc:
        raise HTTPException(422, str(exc)) from exc
    before = sales_response(db, user, 1, 1000000, '', '', '')['rows']
    after = sales_response(db, user, 1, 1000000, '', '', '', {column: expression})['rows']
    return compare_sales_rows(before, after, column)


def compare_sales_rows(before, after, column):
    fields = ['enabled', 'allocation_ratio', 'bonus_basis', 'revenue_total', 'rate_display', 'bonus']
    previous = {row['record_key']: row for row in before}
    old_errors = {(row['record_key'], e['column'], e['message']) for row in before for e in row['calculation']['formula_errors']}
    errors, changes = [], []
    changed_count = 0
    for row in after:
        old = previous[row['record_key']]
        changed = any(row.get(field) != old.get(field) for field in fields)
        changed_count += int(changed)
        for error in row['calculation']['formula_errors']:
            if error['column'] == column or (row['record_key'], error['column'], error['message']) not in old_errors:
                errors.append({'owner': row['owner'], 'row_id': row['row_id'], **error})
        changes.append({'row_id': row['row_id'], 'owner': row['owner'], 'quarter': row['quarter'], 'order_no': row['order_no'],
                        'changed': changed, 'before': {field: old.get(field) for field in fields},
                        'after': {field: row.get(field) for field in fields}, 'problems': row['calculation']['problems'],
                        'overrides': row['calculation']['overrides']})
    changes.sort(key=lambda row: not row['changed'])
    return {'valid': not errors, 'total': len(after), 'changed_count': changed_count,
            'bonus_changed_count': sum(row['before']['bonus'] != row['after']['bonus'] for row in changes),
            'new_error_count': len(errors), 'errors': errors[:10], 'rows': changes[:8]}


@app.post('/api/sales-formulas/definitions/{column}/preview')
def preview_formula(column: str, body: FormulaEditBody, user=Depends(admin), db: Session = Depends(database)):
    if column in SPECS and body.expression.strip() != SPECS[column]['default']:
        raise HTTPException(422, '本列使用固定的完整计算规则，仅可通过参数入口修改允许的参数')
    definition = formula_definition(db, column)
    if definition['version'] != body.version:
        raise HTTPException(409, '公式已被其他人修改，请重新加载')
    return trial_formula(db, user, column, body.expression.strip())


@app.put('/api/sales-formulas/definitions/{column}')
def save_formula(column: str, body: FormulaEditBody, user=Depends(admin), db: Session = Depends(database)):
    if column in SPECS and body.expression.strip() != SPECS[column]['default']:
        raise HTTPException(422, '本列使用固定的完整计算规则，仅可通过参数入口修改允许的参数')
    definition = formula_definition(db, column)
    if definition['version'] != body.version:
        raise HTTPException(409, '公式已被其他人修改，请重新加载')
    expression = body.expression.strip()
    result = trial_formula(db, user, column, expression)
    if not result['valid']:
        error = result['errors'][0]
        raise HTTPException(422, f"公式引入{result['new_error_count']}处运算错误：来源行{error['row_id']}，{error['column']}列，{error['message']}")
    payload = {'expression': expression, 'note': body.note.strip() or '蓝色齿轮修改公式',
               'actor': user.username, 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    save_setting(db, setting_key('formula', column), json.dumps(payload, ensure_ascii=False), body.version)
    audit(db, user.username, f"修改销售{column}公式：{expression}；{payload['note']}"[:200])
    db.commit()
    return {'ok': True, 'definition': formula_definition(db, column), 'preview': result}


class EligibilityTrialBody(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    quarter: str = Field(min_length=1, max_length=30)
    record: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=0)
    vip_minimum: Decimal = Field(ge=0, le=1000000000000)


@app.post('/api/sales-formulas/eligibility/preview')
def preview_eligibility_parameter(body: EligibilityTrialBody, user=Depends(admin), db: Session = Depends(database)):
    require_scope(db, user, body.owner, body.quarter, body.record)
    saved = db.get(SystemSetting, GLOBAL_KEY)
    if body.version != (saved.version if saved else 0):
        raise HTTPException(409, '参数已被其他人修改，请重新加载')
    before = sales_response(db, user, 1, 1000000, '', '', '')['rows']
    after = sales_response(db, user, 1, 1000000, '', '', '', global_overrides={'vip_minimum': str(body.vip_minimum)})['rows']
    return {**compare_sales_rows(before, after, 'S'), 'owner': body.owner, 'quarter': body.quarter}


class RuleParameterBody(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    quarter: str = Field(min_length=1, max_length=30)
    record: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=0)
    parameters: dict = Field(min_length=1, max_length=8)
    note: str = Field(default='', max_length=500)


def prepare_rule_parameters(db, user, column, body):
    if column not in RULE_PARAMETERS:
        raise HTTPException(404, '公式列不存在')
    allowed = set(RULE_PARAMETERS[column])
    if not allowed:
        raise HTTPException(422, '本列没有额外规则参数；请在输入源头维护订单和拆分金额')
    if set(body.parameters) - allowed or any(value is None for value in body.parameters.values()):
        raise HTTPException(422, '包含本列不允许修改的参数，或参数为空')
    require_scope(db, user, body.owner, body.quarter, body.record)
    key = GLOBAL_KEY
    saved = db.get(SystemSetting, key)
    if body.version != (saved.version if saved else 0):
        raise HTTPException(409, '参数已被其他人修改，请重新加载')
    previous = effective_period({s.key:s for s in db.scalars(select(SystemSetting))}, body.owner, body.quarter)
    try:
        updated = PeriodInputs.model_validate({**previous, **body.parameters}).model_dump(mode='json')
    except ValidationError as exc:
        raise HTTPException(422, '参数类型或范围无效：金额必须非负，提点为0～100，累计口径必须为是/否选项') from exc
    return key, updated


def trial_rule_parameters(db, user, column, body, period):
    before = sales_response(db, user, 1, 1000000, '', '', '')['rows']
    after = sales_response(db, user, 1, 1000000, '', '', '', global_overrides={k:v for k,v in period.items() if k != 'target'})['rows']
    return {**compare_sales_rows(before, after, column), 'owner': body.owner, 'quarter': body.quarter}


@app.post('/api/sales-formulas/parameters/{column}/preview')
def preview_rule_parameters(column: str, body: RuleParameterBody, user=Depends(admin), db: Session = Depends(database)):
    _, period = prepare_rule_parameters(db, user, column, body)
    return trial_rule_parameters(db, user, column, body, period)


@app.put('/api/sales-formulas/parameters/{column}')
def save_rule_parameters(column: str, body: RuleParameterBody, user=Depends(admin), db: Session = Depends(database)):
    key, period = prepare_rule_parameters(db, user, column, body)
    result = trial_rule_parameters(db, user, column, body, period)
    if not result['valid']:
        raise HTTPException(422, '本次参数引入计算错误，请核对源头数据')
    note = body.note.strip() or f'{SPECS[column]["title"]}固定公式参数设置'
    save_setting(db, key, json.dumps({**{k:v for k,v in period.items() if k != 'target'}, '_change_note': note}, ensure_ascii=False), body.version)
    audit(db, user.username, f'修改全局销售{column}固定公式参数（全部BD、全部季度）；{note}'[:200])
    db.commit()
    return {'ok': True, 'period': period, 'version': body.version + 1, 'preview': result}
