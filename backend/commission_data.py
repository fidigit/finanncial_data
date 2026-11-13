"""Commission confirmation projection. No unapproved financial calculations."""
import hashlib
import json
from datetime import datetime


def service_key(service):
    return 'commission_service_' + hashlib.sha256(service.encode()).hexdigest()[:40]


def record_key(row):
    identity = json.dumps(row['values'], ensure_ascii=False, sort_keys=True) + ':' + str(row['row_id'])
    return 'commission_record_' + hashlib.sha256(identity.encode()).hexdigest()[:40]


def project_row(row, rule=None, confirmation=None):
    values = row['values']
    confirmed = confirmation or {}
    enabled = confirmed.get('enabled')
    if enabled is None:
        enabled = rule.get('enabled') if rule else None
    try:
        paid_date = datetime.fromisoformat(values.get('付费时间', '')).strftime('%Y年%m月%d日')
    except ValueError:
        paid_date = values.get('付费时间', '')
    source = ' '.join([values.get('订单来源', ''), values.get('订单来源补充', '')])
    referral = '、'.join(x for x in ['协会推荐', '合伙人推荐', '客户推荐'] if x in source)
    return {
        'row_id': row['row_id'], 'record_key': record_key(row), 'order_no': values.get('订单号', ''),
        'quarter': values.get('季度', ''), 'owner': values.get('BD姓名', ''),
        'company': values.get('付款户名', '').strip() or values.get('业务id信息', ''),
        'paid_date': paid_date, 'service': values.get('付费项目', ''),
        'purchase_type': values.get('首购/续费', ''), 'order_amount': values.get('订单金额', ''),
        'enabled': enabled, 'rule_enabled': rule.get('enabled') if rule else None,
        'rule_note': rule.get('note', '') if rule else '', 'rule_issue': rule.get('issue', '') if rule else '',
        'shared_bd': confirmed.get('shared_bd', ''), 'allocation_ratio': confirmed.get('allocation_ratio'),
        'bonus_basis': confirmed.get('bonus_basis'),
        'market_bd': confirmed.get('market_bd', ''),
        'market_pending': '市场同事推荐' in source and not confirmed.get('market_bd'),
        'referral': referral, 'revenue_total': None, 'tier_rate': None,
        'confirmed_rate': confirmed.get('confirmed_rate'), 'bonus': confirmed.get('bonus'),
        'is_paid': confirmed.get('is_paid'), 'is_refunded': confirmed.get('is_refunded'),
        'note': confirmed.get('note', ''), 'source_bonus': values.get('奖金金额', ''),
        'version': confirmed.get('version', 0), 'confirmation': confirmed,
    }


def with_display_note(row):
    """Expose exactly the editable note shown on screen, including the initial generated text."""
    confirmed = row.get('confirmation', {})
    if 'note_override' in confirmed:
        row['note'] = confirmed['note_override']
    else:
        parts = [row.get('note') or row.get('rule_note', '')]
        calculation = row.get('calculation') or {}
        parts.extend(calculation.get('problems', []))
        if calculation.get('overrides'):
            parts.append('人工覆盖：' + '、'.join(calculation['overrides']))
        row['note'] = '\n'.join(str(p) for p in parts if p)
    return row
