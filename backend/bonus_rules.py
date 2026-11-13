"""Shared, persisted workbook rules. Order data and targets keep their own scope."""
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

PLAN_KEY = 'bonus_service_plan_2025'
TARGETS_KEY = 'bonus_revenue_targets'
GLOBAL_KEY = 'bonus_global_parameters'
YEAR_PLAN_PREFIX = 'bonus_service_plan_year_'


def year_plan_key(year):
    return YEAR_PLAN_PREFIX + str(year)


def order_year(values):
    # Payment time is authoritative; a missing/invalid date is never guessed from today.
    from datetime import datetime
    try:
        return datetime.fromisoformat(values.get('付费时间', '')).year
    except (ValueError, TypeError):
        return None


def source_samples_path():
    return Path(os.getenv('BONUS_SOURCE_SAMPLES_PATH', str(Path(__file__).resolve().parent.parent / 'data/sales-source-samples.json')))


def initialize_rule_sources(db):
    from backend.app import SystemSetting, audit
    path = source_samples_path()
    samples = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    for kind, key in [('services', PLAN_KEY), ('targets', TARGETS_KEY)]:
        if db.get(SystemSetting, key) or not samples.get(kind, {}).get('rows'):
            continue
        data = samples[kind]
        rows, seen = [], {}
        for original in data['rows']:
            row = dict(original)
            if kind == 'services':
                name = str(row.get('所购服务') or '').strip()
                flag = str(row.get('是否计入提成范围') or '').strip()
                if not name or flag not in ('是', '否'):
                    raise ValueError('2025年奖金方案存在无效服务或计提资格，未导入')
                identity, value = name, flag
                row = {'所购服务': name, '是否计入提成范围': flag}
            else:
                name, quarter = str(row.get('BD姓名') or '').strip(), str(row.get('季度') or '').strip()
                try:
                    amount = Decimal(str(row.get('直接营收目标')))
                except InvalidOperation as exc:
                    raise ValueError('直接营收目标不是有效金额') from exc
                if not name or not quarter or not amount.is_finite() or amount <= 0:
                    raise ValueError('直接营收目标缺少BD、季度或有效金额')
                identity, value = (name, quarter), str(amount)
            if identity in seen:
                if seen[identity] != value:
                    raise ValueError('规则源含有冲突的重复记录，未导入')
                continue
            seen[identity] = value
            rows.append(row)
        payload = {**data, 'rows': rows}
        db.add(SystemSetting(key=key, value=json.dumps(payload, ensure_ascii=False), version=1))
        audit(db, 'system', f'启用规则源：{data["sheet"]}，{len(rows)}条；服务规则适用全部BD及季度，目标严格匹配BD和季度')
    db.commit()
    # One-time migration. Keep the old source for backup, never overwrite an edited year.
    legacy = db.get(SystemSetting, PLAN_KEY)
    if legacy and not db.get(SystemSetting, year_plan_key(2025)):
        from backend.commission_data import service_key
        data = json.loads(legacy.value)
        rows = []
        for row in data.get('rows', []):
            override = db.get(SystemSetting, service_key(row['所购服务']))
            enabled = json.loads(override.value).get('enabled') if override else None
            rows.append({**row, **({'是否计入提成范围': '是' if enabled else '否'} if enabled is not None else {})})
        db.add(SystemSetting(key=year_plan_key(2025), value=json.dumps({'year': 2025, 'rows': rows}, ensure_ascii=False), version=1))
        audit(db, 'system', f'奖金方案按年迁移：保留2025年{len(rows)}项服务，其他年份等待沿袭或维护')
        db.commit()


def setting_payload(settings, key, default=None):
    setting = settings.get(key)
    return json.loads(setting.value) if setting else (default if default is not None else {})


def shared_service_rule(settings, service, amount=None, vip_minimum='1680', year=None):
    from backend.commission_data import service_key
    if service == '团队VIP':
        try:
            number = Decimal(str(amount))
            enabled = number >= Decimal(str(vip_minimum)) if number.is_finite() else None
        except (InvalidOperation, ValueError, TypeError):
            enabled = None
        return {'enabled': enabled, 'note': f'全局规则：团队VIP订单金额达到{vip_minimum}元计提'}
    annual = any(key.startswith(YEAR_PLAN_PREFIX) for key in settings)
    if annual:
        if year is None:
            return {'enabled': None, 'issue': 'invalid_payment_year', 'note': '付款时间无效，无法匹配奖金方案年份'}
        if year_plan_key(year) not in settings:
            return {'enabled': None, 'issue': 'missing_year_plan', 'note': f'缺少{year}年奖金方案，请在奖金方案中选择{year}年并沿袭上一年'}
        plan = setting_payload(settings, year_plan_key(year))
        row = next((r for r in plan.get('rows', []) if r['所购服务'] == service), None)
        return {'enabled': row['是否计入提成范围'] == '是', 'note': f'来源：{year}年奖金方案'} if row else {'enabled': None, 'issue': 'missing_service', 'note': f'{year}年奖金方案未配置服务：{service}，请新增该服务并设置是否计提'}
    override = setting_payload(settings, service_key(service))
    if override:
        return override
    plan = setting_payload(settings, PLAN_KEY)
    row = next((r for r in plan.get('rows', []) if r['所购服务'] == service), None)
    return {'enabled': row['是否计入提成范围'] == '是', 'note': '来源：2025年奖金方案（全BD、全季度）'} if row else {}


def source_target(settings, owner, quarter):
    row = target_entry(settings, owner, quarter)
    return row.get('直接营收目标') if row else None


def target_entry(settings, owner, quarter):
    data = setting_payload(settings, TARGETS_KEY)
    return next((r for r in data.get('rows', []) if r['BD姓名'] == owner and r['季度'] == quarter), None)
