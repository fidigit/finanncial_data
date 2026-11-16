"""Export/import private source configuration without replacing accounts or orders.

Standard library only. Stop the service before import. Import defaults to a dry run.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

FORMAT = 'bd-source-config-v1'
KINDS = {'splits', 'targets', 'services', 'orders', 'segmentation'}
TARGETS = 'bonus_revenue_targets'
LEGACY_PLAN = 'bonus_service_plan_2025'
CONSTANTS = 'bonus_global_parameters'
DEFAULTS = dict(vip_minimum='1680', threshold='30000', renewal_rate='3',
                self_rate='10', self_excess='15', market_rate='8', market_excess='13',
                partner_rate='5', partner_excess='8', include_ineligible=True)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def allowed(key):
    return key in (TARGETS, LEGACY_PLAN, CONSTANTS) or re.fullmatch(r'bonus_service_plan_year_20\d{2}', key) is not None


def read_db(path):
    if not path.is_file():
        raise ValueError('数据库不存在，拒绝创建空账号库：' + str(path))
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def numeric(value, minimum, maximum, nullable=False):
    if nullable and value is None:
        return
    if isinstance(value, bool):
        raise ValueError('金额或提点不能是布尔值')
    number = Decimal(str(value))
    if not number.is_finite() or number < minimum or number > maximum:
        raise ValueError('金额或提点超出范围')


def identity(key, row):
    if key == TARGETS:
        name, quarter = row.get('BD姓名'), row.get('季度')
        if not isinstance(name, str) or not name.strip() or name != name.strip() or not re.fullmatch(r'20\d{2}Q[1-4]', str(quarter)):
            raise ValueError('季度目标缺少有效姓名/季度')
        numeric(row.get('直接营收目标'), Decimal('0.0000001'), Decimal('1000000000000'), nullable=True)
        return name, quarter
    name = row.get('所购服务')
    if not isinstance(name, str) or not name.strip() or name != name.strip() or row.get('是否计入提成范围') not in ('是', '否', None):
        raise ValueError('奖金方案缺少有效服务名/是或否')
    return name


def validate_setting(key, value):
    if not allowed(key) or not isinstance(value, dict):
        raise ValueError('配置包含有不允许的设置：' + key)
    if key == CONSTANTS:
        if set(value) - set(DEFAULTS):
            raise ValueError('公共常数包含未知参数')
        for field, number in value.items():
            if field == 'include_ineligible':
                if type(number) is not bool:
                    raise ValueError('累计口径必须是布尔值')
            else:
                numeric(number, 0, 1000000000000 if field in ('vip_minimum', 'threshold') else 100)
        return
    if not isinstance(value.get('rows'), list):
        raise ValueError('配置缺少rows：' + key)
    if key.startswith('bonus_service_plan_year_') and value.get('year') != int(key[-4:]):
        raise ValueError('年度方案年份与设置键不一致')
    keys = [identity(key, row) for row in value['rows']]
    if len(keys) != len(set(keys)):
        raise ValueError('配置含有重复的姓名季度或服务：' + key)


def validate_payload(payload):
    if set(payload) != {'settings', 'samples'} or not isinstance(payload['settings'], dict):
        raise ValueError('配置包结构不正确')
    for key, value in payload['settings'].items():
        validate_setting(key, value)
    samples = payload['samples']
    if not isinstance(samples, dict) or set(samples) != KINDS:
        raise ValueError('配置包必须包含五类历史源头样例')
    for value in samples.values():
        if not isinstance(value, dict) or not isinstance(value.get('rows'), list) or not isinstance(value.get('columns'), list):
            raise ValueError('源头样例格式不正确')


def export_bundle(database, samples, output):
    source = json.loads(samples.read_text(encoding='utf-8'))
    with read_db(database) as db:
        db.execute('BEGIN')
        settings = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM system_settings') if allowed(key)}
    settings[CONSTANTS] = {**DEFAULTS, **settings.get(CONSTANTS, {})}
    # Fresh installations can seed initial sources even if this database predates initialization.
    for kind, key in [('targets', TARGETS), ('services', LEGACY_PLAN)]:
        if key not in settings:
            data = source[kind]
            deduped = {}
            for row in data['rows']:
                ident = identity(key, row)
                if ident in deduped and deduped[ident] != row:
                    raise ValueError('初始源头有冲突重复项')
                deduped[ident] = row
            settings[key] = {**data, 'rows': list(deduped.values())}
    if 'bonus_service_plan_year_2025' not in settings:
        settings['bonus_service_plan_year_2025'] = {'year': 2025, 'rows': settings[LEGACY_PLAN]['rows']}
    payload = {'settings': settings, 'samples': source}
    validate_payload(payload)
    envelope = {'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(canonical(payload)).hexdigest(), 'payload': payload}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'source-config.json').write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copy2(Path(__file__), output / 'import_source_config.py')
    return {key: len(value.get('rows', [])) if key != CONSTANTS else len(value) for key, value in settings.items()}


def load_bundle(path):
    envelope = json.loads(path.read_text(encoding='utf-8'))
    payload = envelope.get('payload')
    if envelope.get('format') != FORMAT or envelope.get('sha256') != hashlib.sha256(canonical(payload)).hexdigest():
        raise ValueError('配置包格式或SHA256校验失败，未导入')
    validate_payload(payload)
    return payload


def merge_setting(key, existing, incoming, prefer_package):
    if key == CONSTANTS:
        return {**existing, **incoming} if prefer_package else {**incoming, **existing}
    validate_setting(key, existing)
    rows = {identity(key, row): row for row in existing['rows']}
    for row in incoming['rows']:
        ident = identity(key, row)
        if prefer_package or ident not in rows:
            rows[ident] = row
    return {**incoming, **existing, 'rows': list(rows.values())}


def merge_samples(existing, incoming, prefer_package):
    merged = dict(existing)
    fields = {'splits': ('订单号', 'BD姓名'), 'targets': ('BD姓名', '季度'),
              'services': ('所购服务',), 'orders': ('订单号', 'BD姓名', '客户付款时间'),
              'segmentation': ('订单号', 'BD姓名')}
    for kind, value in incoming.items():
        if kind not in existing:
            merged[kind] = value
            continue
        old = existing[kind]
        rows = {}
        def row_key(row):
            parts = tuple(str(row.get(k) or '') for k in fields[kind])
            return parts if any(parts) else canonical(row)
        for row in old['rows']:
            rows[row_key(row)] = row
        for row in value['rows']:
            ident = row_key(row)
            if prefer_package or ident not in rows:
                rows[ident] = row
        merged[kind] = {**value, **old, 'rows': list(rows.values())}
    return merged


def import_bundle(bundle, project, database=None, apply=False, prefer_package=False):
    payload = load_bundle(bundle)
    project = project.resolve()
    database = (database or project / 'data/app.db').resolve()
    samples_path = project / 'data/sales-source-samples.json'
    env_db = os.getenv('DATABASE_URL', '')
    if env_db and (not env_db.startswith('sqlite:///') or Path(env_db[len('sqlite:///'):]).resolve() != database):
        raise ValueError('DATABASE_URL与目标SQLite不一致，拒绝写入错误账号库。请指定实际--database或使用原环境')
    env_samples = os.getenv('BONUS_SOURCE_SAMPLES_PATH', '')
    if env_samples and Path(env_samples).resolve() != samples_path:
        raise ValueError('当前预览固定读取项目data目录；请将BONUS_SOURCE_SAMPLES_PATH统一为项目/data/sales-source-samples.json')
    original = samples_path.read_bytes() if samples_path.exists() else None
    old_samples = json.loads(original) if original is not None else {}
    new_samples = merge_samples(old_samples, payload['samples'], prefer_package)
    with read_db(database) as db:
        current = {key: (json.loads(value), version) for key, value, version in db.execute('SELECT key,value,version FROM system_settings') if allowed(key)}
    changes, report = {}, []
    for key, incoming in payload['settings'].items():
        old, version = current.get(key, (None, 0))
        merged = incoming if old is None else merge_setting(key, old, incoming, prefer_package)
        validate_setting(key, merged)
        status = '新增' if old is None else '补齐/更新' if merged != old else '保留/无需变更'
        report.append(key + ': ' + status)
        if merged != old:
            changes[key] = (merged, version)
    sample_changed = new_samples != old_samples
    report.append('五类源头预览: ' + ('补齐/更新' if sample_changed else '无需变更'))
    result = {'apply': apply, 'settings_changed': len(changes), 'samples_changed': sample_changed,
              'policy': '配置包同名值优先' if prefer_package else '服务器已有值优先', 'details': report}
    if not apply or not (changes or sample_changed):
        return result
    backup = project / 'backups' / ('source-config-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, exist_ok=False)
    with read_db(database) as src, sqlite3.connect(backup / 'app.db') as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('备份完整性检查失败')
    if original is not None:
        (backup / 'sales-source-samples.json').write_bytes(original)
    (backup / 'import-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    staged = samples_path.with_suffix('.import-tmp')
    replaced = False
    try:
        with sqlite3.connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            for key, (value, expected_version) in changes.items():
                now = db.execute('SELECT value,version FROM system_settings WHERE key=?', (key,)).fetchone()
                expected = current.get(key)
                if (None if now is None else (json.loads(now[0]), now[1])) != expected:
                    raise ValueError('配置已被其他用户修改，请停止服务后重新预检')
                text = json.dumps(value, ensure_ascii=False)
                if expected is not None:
                    db.execute('UPDATE system_settings SET value=?,version=? WHERE key=?', (text, expected_version + 1, key))
                else:
                    db.execute('INSERT INTO system_settings(key,value,version) VALUES (?,?,1)', (key, text))
            if (samples_path.read_bytes() if samples_path.exists() else None) != original:
                raise ValueError('源头文件已变化，请停止服务后重试')
            if sample_changed:
                staged.write_text(json.dumps(new_samples, ensure_ascii=False, indent=2), encoding='utf-8')
                staged.replace(samples_path)
                replaced = True
    except BaseException:
        if replaced:
            if original is None:
                samples_path.unlink()
            else:
                samples_path.write_bytes(original)
        raise
    finally:
        staged.unlink(missing_ok=True)
    result['backup'] = str(backup)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('--database', required=True, type=Path)
    exp.add_argument('--samples', required=True, type=Path)
    exp.add_argument('--output', required=True, type=Path)
    imp = sub.add_parser('import')
    imp.add_argument('--input', type=Path, default=Path(__file__).with_name('source-config.json'))
    imp.add_argument('--project', required=True, type=Path)
    imp.add_argument('--database', type=Path)
    imp.add_argument('--apply', action='store_true')
    imp.add_argument('--prefer-package', action='store_true', help='显式使用包内同名值；不删除服务器额外配置')
    args = parser.parse_args()
    if args.command == 'export':
        result = export_bundle(args.database, args.samples, args.output)
    else:
        result = import_bundle(args.input, args.project, args.database, args.apply, args.prefer_package)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'import' and not args.apply:
        print('以上仅预检，未写入。确认后追加 --apply 正式导入。')


if __name__ == '__main__':
    main()
