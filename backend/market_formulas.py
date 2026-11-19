"""Market commission calculation shared by the table and workbook exports."""
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from backend.app import commission_snapshot
from backend.bonus_config import all_settings, market_rates
from backend.bonus_rules import order_year, shared_service_rule
from backend.commission_data import project_row, record_key, refund_key, with_display_note
from backend.sales_formulas import decimal, effective_target, global_parameters

CENT = Decimal('0.01')
ZERO = Decimal(0)


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def market_basis(values):
    amount = decimal(values.get('订单金额'))
    share = decimal(values.get('_share_amount'))
    if amount is None:
        return None, None
    if not values.get('_source_id'):
        return None, None
    if share is None or (not amount and share) or (amount and not ZERO <= share / amount <= 1):
        return None, None
    # The source share equals amount × the unrounded ratio.
    return share / amount if amount else Decimal(1), money(share)


def percent(rate):
    return format((rate * 100).normalize(), 'f') + '%'


def text_number(value):
    return str(value) if value is not None else None


def classify(values):
    value = values.get('直接/间接收入', '').strip()
    return {'直接收入': '直接营收', '间接收入': '间接营收',
            '直接营收': '直接营收', '间接营收': '间接营收'}.get(value, '待确认')


def payment_time(values):
    try:
        return datetime.fromisoformat(values.get('付费时间', '')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def calculate_market(group, threshold, rates):
    cumulative = ZERO
    reached = False
    for paid, row in sorted(group, key=lambda item: (item[0] or datetime.max, item[1]['row_id'])):
        trace = row['calculation']
        basis, channel = decimal(row['bonus_basis']), trace['channel']
        direct = channel == '直接营收'
        eligible = row['enabled']
        purchase = row['purchase_type']
        referral = trace['referral']
        before = cumulative
        if direct and eligible is True and basis is not None and paid:
            cumulative += basis
        was_reached = reached
        reached = reached or (threshold is not None and cumulative >= threshold)
        trace.update(before=str(before), target=text_number(threshold), over_target=reached if threshold else None)
        row['revenue_total'] = str(cumulative) if paid else None
        rate, bonus, label = None, None, '待确认'
        if eligible is False:
            rate, bonus, label = ZERO, money(ZERO), '0%（不计提）'
        elif eligible is None:
            trace['problems'].append('计提资格待确认')
        elif basis is None:
            trace['problems'].append('分摊金额待确认')
        elif channel == '待确认':
            trace['problems'].append('直接／间接营收待确认')
        elif purchase == '首购' and direct:
            rate = rates['direct_referral' if referral else 'direct_no_referral']
        elif purchase == '首购' and not referral:
            rate = rates['indirect_first']
        elif purchase == '首购':
            trace['problems'].append('间接首购有转介绍，提点待确认')
        elif purchase == '续费' and not direct:
            trace['problems'].append('间接续费提点待确认')
        elif purchase == '续费' and (threshold is None or not paid):
            trace['problems'].append('直接营收目标待配置' if threshold is None else '付款时间待确认')
        elif purchase == '续费':
            low, high = rates['renewal_low'], rates['renewal_high']
            if was_reached:
                rate = high
            elif basis > 0 and cumulative > threshold:
                low_basis = threshold - before
                high_basis = basis - low_basis
                raw_bonus = low_basis * low + high_basis * high
                bonus = money(raw_bonus)
                rate = raw_bonus / basis
                label = f'{percent(low)} / {percent(high)}'
                trace.update(inside_basis=str(low_basis), excess_basis=str(high_basis), crossing=True)
            else:
                rate = low
        else:
            trace['problems'].append('首购／续费待确认')
        if rate is not None and bonus is None:
            bonus = money(basis * rate)
            label = percent(rate)
        row.update(confirmed_rate=text_number(rate), bonus=text_number(bonus), rate_display=label)


def market_response(db, user, page, page_size, search, quarter, owner):
    snapshot = commission_snapshot(db, user, category='market', page_size=1000000)
    all_rows = snapshot['rows']
    settings = all_settings(db)
    vip_minimum = global_parameters(settings)['vip_minimum']
    rates = {key: Decimal(value) / 100 for key, value in market_rates(settings).items()}
    peers = defaultdict(set)
    for raw in all_rows:
        values = raw['values']
        if values.get('订单号'):
            peers[(values['订单号'], values.get('付费项目'))].add(values.get('BD姓名', '').strip())
    groups, calculated, rules = defaultdict(list), {}, {}
    for raw in all_rows:
        values = raw['values']
        service = values.get('付费项目', '')
        rule = shared_service_rule(settings, service, values.get('订单金额'), vip_minimum, order_year(values))
        rules[service] = rule
        saved = settings.get(record_key(raw))
        confirmation = {**json.loads(saved.value), 'version': saved.version} if saved else None
        row = project_row(raw, rule, confirmation, refund_key(values.get('订单号', '')) in settings)
        ratio, basis = market_basis(values)
        name, period = row['owner'].strip(), row['quarter']
        shared = peers[(row['order_no'], service)] - {name, ''}
        market_bd = values.get('_market_name', '').strip()
        if market_bd in ('无', '测试', 'null', 'None'):
            market_bd = ''
        channel = classify(values)
        row.update(allocation_ratio=text_number(ratio), bonus_basis=text_number(basis),
                   shared_bd=('、'.join(sorted(shared)) or '共享订单') if ratio is not None and ratio < 1 else '',
                   market_bd=market_bd or row['market_bd'], market_pending=row['market_pending'] and not market_bd,
                   calculation={'channel': channel, 'referral': any(label in row['referral'] for label in ('协会推荐', '合伙人推荐')),
                                'problems': [], 'overrides': ['计提资格'] if confirmation and isinstance(confirmation.get('enabled'), bool) else []})
        groups[(name, period)].append((payment_time(values), row))
        calculated[row['row_id']] = row
    for (name, period), group in groups.items():
        calculate_market(group, decimal(effective_target(settings, name, period)), rates)
    needle = search.strip().casefold()
    selected = [raw for raw in all_rows
                if (not quarter or raw['values'].get('季度') == quarter)
                and (not owner or raw['values'].get('BD姓名') == owner)
                and (not needle or any(needle in value.casefold() for value in raw['values'].values()))]
    visible = selected[(page - 1) * page_size:page * page_size]
    return {'rows': [with_display_note(calculated[raw['row_id']]) for raw in visible],
            'total': len(selected), 'options': snapshot['options'],
            'pending_services': [], 'rules': rules, 'can_edit': user.role in ('admin', 'superadmin'),
            'can_edit_note': True}
