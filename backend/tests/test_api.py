import os
import tempfile
import csv
import json
from decimal import Decimal
from pathlib import Path
import pytest
from contextlib import contextmanager

# Isolate all persistent effects from developer or production data.
temporary = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(temporary.name) / 'test.db').as_posix()
os.environ['DEMO_MODE'] = 'true'
# Never seed test databases from developer business workbook caches.
os.environ['BONUS_SOURCE_SAMPLES_PATH'] = str(Path(temporary.name) / 'empty-source.json')
os.environ.pop('BD_ALLOWED_SOURCE_HOSTS', None)
# Tests run from GitHub without any real customer export or account database.
fixture_file = Path(temporary.name) / '参考数据.csv'
fixture_columns = ['季度', 'BD姓名', '运营姓名', '付费时间', '付费项目', '订单金额', '首购/续费', '业务id信息', '营收金额', '奖金比例', '奖金金额', '支付方式', '付款户名', '订单来源', '订单来源补充', '直接/间接收入', '订单号', '有/无归属BD']
fixture_owners = [''] * 1248
for fixture_name, fixture_count in [('何卫', 307), ('余飞', 1), ('周政', 288), ('屈敬东', 504), ('崔赵鹏', 47), ('曾德康', 505), ('杨红星', 447), ('贺庆锋', 613)]:
    fixture_owners.extend([fixture_name] * fixture_count)
with fixture_file.open('w', encoding='utf-8-sig', newline='') as fixture_stream:
    fixture_writer = csv.DictWriter(fixture_stream, fieldnames=fixture_columns)
    fixture_writer.writeheader()
    for fixture_index, fixture_owner in enumerate(fixture_owners):
        fixture_record = {key: '' for key in fixture_columns}
        fixture_record.update({'季度': '2026Q4', 'BD姓名': fixture_owner, '付费时间': '2026-10-25 19:57:20', '付费项目': ['收费系统户数', '短信', '团队VIP'][fixture_index % 3], '订单金额': '27.43', '营收金额': '27.43', '首购/续费': '首购', '业务id信息': '测试企业（虚构）', '奖金比例': '0.1', '奖金金额': '2.74', '订单号': f'TEST-{fixture_index if fixture_index < 3494 else fixture_index - 3494}', '有/无归属BD': '有归属' if fixture_owner else '无归属'})
        fixture_writer.writerow(fixture_record)
os.environ['REFERENCE_CSV_PATH'] = str(fixture_file)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app import Bonus, User, app, engine, hash_password, initialize


def sales_case(amount='20000', *, target='260000', threshold='0', enabled=True, purchase='首购', row_id=1, variables=None, confirmation=None, date='2026-07-01 10:00:00'):
    from backend.sales_formulas import PeriodInputs, OrderInputs
    from backend.commission_data import project_row
    raw = {'row_id': row_id, 'values': {'BD姓名': '销售甲', '季度': '2026Q3', '订单金额': amount, '付费项目': '收费系统户数', '首购/续费': purchase, '付费时间': date}}
    return {'row': project_row(raw, {'enabled': enabled}, confirmation), 'period': PeriodInputs(target=target, threshold=threshold).model_dump(mode='json'), 'variables': {**OrderInputs().model_dump(mode='json'), **(variables or {})}, 'rule': {'enabled': enabled}, 'source': '', 'paid_at': date}


def test_sales_cross_target_and_full_quarter_gate():
    from backend.sales_formulas import calculate_sales
    rows = calculate_sales([sales_case('250000', row_id=1), sales_case('20000', row_id=2)])
    assert Decimal(rows[1]['bonus']) == Decimal('2500.00')
    assert rows[1]['rate_display'] == '10.0% / 15.00%'
    assert rows[1]['calculation']['inside_basis'] == '10000.00'
    assert rows[1]['calculation']['crossing'] is True
    # Exactly reaching target stays at base rate; gate is inclusive and retroactive to all rows.
    rows = calculate_sales([sales_case('15000', target='30000', threshold='30000'), sales_case('15000', target='30000', threshold='30000', row_id=2)])
    assert all(Decimal(r['bonus']) == 1500 for r in rows)
    assert rows[1]['calculation']['crossing'] is False
    assert Decimal(calculate_sales([sales_case('29999.99', threshold='30000')])[0]['bonus']) == 0


def test_sales_missing_values_and_ineligible_accumulation():
    from backend.sales_formulas import calculate_sales
    rows = calculate_sales([sales_case('100', target='150', enabled=False), sales_case('100', target='150', row_id=2)])
    assert Decimal(rows[0]['bonus']) == 0 and Decimal(rows[1]['bonus']) == Decimal('12.5')
    assert calculate_sales([sales_case(target=None)])[0]['bonus'] is None
    assert calculate_sales([sales_case(enabled=None)])[0]['bonus'] is None
    rows = calculate_sales([sales_case('bad'), sales_case(row_id=2)])
    assert all(r['revenue_total'] is None and r['bonus'] is None for r in rows)
    rows = calculate_sales([sales_case(date='bad'), sales_case(row_id=2)])
    assert all(r['revenue_total'] is None for r in rows)
    item = sales_case(variables={'shared_names': '销售乙'})
    assert calculate_sales([item])[0]['bonus_basis'] is None


def test_sales_channels_split_renewal_and_manual_priority():
    from backend.sales_formulas import calculate_sales
    for channel, expected in [('self', '10'), ('market', '8'), ('partner', '5')]:
        row = calculate_sales([sales_case('100', variables={'channel': channel})])[0]
        assert Decimal(row['bonus']) == Decimal(expected)
    row = calculate_sales([sales_case('100', target=None, purchase='续费')])[0]
    assert Decimal(row['bonus']) == 3
    row = calculate_sales([sales_case('100.01', variables={'split_amount': '1', 'split_total': '2'})])[0]
    assert row['bonus_basis'] == '50.01'
    row = calculate_sales([sales_case('100', variables={'refund_amount': '25'}, confirmation={'bonus': '77.00'})])[0]
    assert row['bonus'] == '77.00' and row['is_refunded'] is True and '奖金' in row['calculation']['overrides']
    item = sales_case('100'); item['row']['service'] = '团队VIP'; item['rule'] = {}
    assert calculate_sales([item])[0]['enabled'] is False
    item = sales_case('1680'); item['row']['service'] = '团队VIP'; item['rule'] = {}
    assert calculate_sales([item])[0]['enabled'] is True


def test_sales_inputs_scope_recalculation_and_market_isolation(business_accounts):
    with client_as() as manager:
        cats = manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories', json={'mapping': {**cats['mapping'], '何卫': 'sales', '周政': 'market'}, 'version': cats['version']})
        market_before = manager.get('/api/commission-data?category=market').json()
        row = manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        query = {'owner': '何卫', 'quarter': row['quarter'], 'record': row['record_key']}
        config = manager.get('/api/sales-formulas/inputs', params=query).json()
        payload = {**query, 'version': config['period_version'], 'note': '测试季度目标', 'period': {**config['period'], 'target': '100', 'threshold': '0'}}
        assert manager.put('/api/sales-formulas/inputs/period', json=payload).status_code == 200
        assert manager.put('/api/sales-formulas/inputs/period', json=payload).status_code == 409
        assert manager.put('/api/sales-formulas/service', json={**query, 'enabled': True, 'version': config['service_version'], 'note': '测试销售专属规则'}).status_code == 200
        response = manager.get('/api/commission-data?category=sales&owner=何卫').json()
        first = response['rows'][0]
        assert first['bonus'] is not None
        filtered = manager.get('/api/commission-data', params={'category': 'sales', 'owner': '何卫', 'search': first['order_no']}).json()['rows'][0]
        assert first['bonus'] == filtered['bonus'] and first['revenue_total'] == filtered['revenue_total']
        names, exported = workbook_sheets(manager.get('/api/bonus-export/sales', params={'owner': '何卫', 'quarter': row['quarter']}).content)
        assert names == ['何卫']
        exported_bonus = exported[0][1][15].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v').text
        assert Decimal(exported_bonus) == Decimal(first['bonus'])
        assert manager.get('/api/commission-data?category=market').json()['total'] == market_before['total']
        bad = {**query, 'version': 0, 'note': '测试无效变量', 'variables': {'split_amount': 2, 'split_total': 1}}
        assert manager.put('/api/sales-formulas/inputs/order', json=bad).status_code == 422
    with client_as('何卫', 'Test-only-password!') as bd:
        assert bd.get('/api/sales-formulas/inputs', params=query).status_code == 200
        assert bd.get('/api/sales-formulas/inputs', params={**query, 'owner': '周政'}).status_code == 404
        assert bd.put('/api/sales-formulas/inputs/period', json=payload).status_code == 403
        assert bd.put('/api/sales-formulas/service', json={**query, 'enabled': True, 'version': 0, 'note': '越权'}).status_code == 403


def workbook_sheets(content):
    import io
    import zipfile
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        names = [node.attrib['name'] for node in ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', ns)]
        rows = [ET.fromstring(archive.read(f'xl/worksheets/sheet{i}.xml')).findall('s:sheetData/s:row', ns) for i in range(1, len(names)+1)]
        return names, rows


def test_v2_classification_and_export_scope(business_accounts):
    with client_as() as manager:
        snapshot = manager.get('/api/bd-categories').json()
        mapping = {**snapshot['mapping'], '何卫': 'sales', '周政': 'market', '余飞': 'sales'}
        payload = {'mapping': mapping, 'version': snapshot['version']}
        assert manager.put('/api/bd-categories', json=payload).status_code == 200
        assert manager.put('/api/bd-categories', json=payload).status_code == 409
        policy = manager.get('/api/reference-data/policy').json()
        assert manager.put('/api/reference-data/policy', json={'self_only': False, 'version': policy['version']}).status_code == 200
        sales = manager.get('/api/commission-data?category=sales').json()
        assert '周政' not in sales['options']['owners']
        assert manager.get('/api/commission-data?category=sales&owner=周政').json()['total'] == 0
        exported = manager.get('/api/bonus-export/sales?owner=何卫')
        names, rows = workbook_sheets(exported.content)
        assert names == ['何卫'] and len(rows[0]) == 308
    with client_as('何卫', 'Test-only-password!') as bd:
        assert bd.get('/api/bd-categories').status_code == 403
        assert bd.put('/api/bd-categories', json=payload).status_code == 403
        assert bd.get('/api/commission-data?category=sales').json()['total'] == 307
        assert bd.get('/api/commission-data?category=market').json()['total'] == 0
        assert bd.get('/api/commission-data?owner=周政').json()['total'] == 0
        names, rows = workbook_sheets(bd.get('/api/bonus-export/sales').content)
        assert names == ['何卫'] and len(rows[0]) == 308
        names, _ = workbook_sheets(bd.get('/api/bonus-export/market?owner=周政').content)
        assert names == ['无数据']
    with client_as('梁梓珊', 'Test-only-password!') as special:
        assert special.get('/api/bd-categories').status_code == 200
    with client_as() as manager:
        policy = manager.get('/api/reference-data/policy').json()
        manager.put('/api/reference-data/policy', json={'self_only': True, 'version': policy['version']})


def test_v2_meetings_permissions_validation_and_conflict(business_accounts):
    payload = dict(owner='何卫', meeting_date='2026-11-11', meeting_type='研讨会', location='广州', companies=6, attendees=12, friend_rate='95', registrations=3, leads=5, bonus='200.00', qualified=True, note='人工确认', follow_up='已联系', is_paid=False)
    with client_as() as manager:
        response = manager.post('/api/meetings', json=payload)
        assert response.status_code == 200
        record_id = response.json()['id']
        assert manager.post('/api/meetings', json={**payload, 'owner': '周政'}).status_code == 200
        assert manager.post('/api/meetings', json={**payload, 'friend_rate': 101}).status_code == 422
        assert manager.post('/api/meetings', json={**payload, 'owner': '不存在'}).status_code == 422
        assert manager.put('/api/meetings/'+record_id, json={**payload, 'version': 1, 'bonus': '300.00'}).status_code == 200
        assert manager.put('/api/meetings/'+record_id, json={**payload, 'version': 1}).status_code == 409
        names, _ = workbook_sheets(manager.get('/api/bonus-export/meetings').content)
        assert set(names) == {'何卫', '周政'}
    with client_as('何卫', 'Test-only-password!') as bd:
        rows = bd.get('/api/meetings').json()['rows']
        assert len(rows) == 1 and rows[0]['owner'] == '何卫' and rows[0]['bonus'] == '300.00'
        assert bd.get('/api/meetings?owner=周政').json()['total'] == 0
        assert bd.post('/api/meetings', json=payload).status_code == 403
        assert bd.put('/api/meetings/'+record_id, json={**payload, 'version': 2}).status_code == 403
        names, rows = workbook_sheets(bd.get('/api/bonus-export/meetings').content)
        assert names == ['何卫'] and len(rows[0]) == 2


def test_v2_workbook_names_and_literal_formula():
    from backend.bonus_v2 import workbook_bytes
    data = workbook_bytes([{'owner': 'A/B', 'note': '=HYPERLINK("https://example.com")'}, {'owner': 'A?B', 'note': '<>&'}, {'owner': 'a/b', 'note': 'text'}], [('owner', '姓名'), ('note', '备注')])
    names, rows = workbook_sheets(data)
    assert len(set(n.casefold() for n in names)) == 3
    assert all(len(n) <= 31 and '/' not in n and '?' not in n for n in names)
    assert all(cell.attrib['t'] == 'inlineStr' for group in rows for row in group for cell in row)

HEADERS = {'X-Requested-With': 'BD-Workbench'}


@pytest.fixture(scope='session', autouse=True)
def cleanup_database():
    yield
    engine.dispose()
    temporary.cleanup()


@contextmanager
def client_as(username='admin', password='Demo2026!'):
    with TestClient(app, headers=HEADERS) as client:
        result = client.post('/api/login', json={'username': username, 'password': password})
        assert result.status_code == 200
        yield client


def test_personal_scope_detail_and_export():
    with client_as('bd.lin') as lin, client_as('bd.zhou') as zhou:
        left = lin.get('/api/bonuses').json()
        right = zhou.get('/api/bonuses').json()
        assert len(left) == len(right) == 24
        assert {r['owner'] for r in left} == {'林晨'}
        assert {r['owner'] for r in right} == {'周宁'}
        assert not {r['id'] for r in left} & {r['id'] for r in right}
        assert lin.get(f"/api/bonuses/{right[0]['id']}").status_code == 404
        assert lin.get('/api/bonuses/999999').status_code == 404
        exported = lin.get('/api/bonuses/export?period=2026-10').text
        assert '林晨' in exported and '周宁' not in exported
        assert len(lin.get('/api/bonuses?period=2026-10').json()) == 6


def test_ignored_owner_parameter_cannot_expand_scope():
    with client_as('bd.lin') as client:
        result = client.get('/api/bonuses?owner_id=3&role=admin').json()
        assert all(r['owner'] == '林晨' for r in result)


def test_admin_personal_scope_is_not_global():
    with client_as() as client:
        assert len(client.get('/api/bonuses').json()) == 48
        assert client.get('/api/bonuses?personal=true').json() == []


def test_admin_endpoints_are_not_available_to_bd():
    with client_as('bd.lin') as client:
        for path in ['/sources', '/datasets', '/audit', '/users', '/sources/1/metadata']:
            assert client.get('/api' + path).status_code == 403
        assert client.post('/api/sources/1/test').status_code == 403
        assert client.post('/api/settlements/preview').status_code == 403


def test_cookie_flags_and_logout():
    with client_as() as client:
        response = client.post('/api/login', json={'username': 'admin', 'password': 'Demo2026!'})
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/me').status_code == 401


def test_csrf_and_unauthenticated_requests():
    with TestClient(app) as client:
        assert client.post('/api/login', json={'username': 'admin', 'password': 'Demo2026!'}).status_code == 403
        assert client.get('/api/bonuses').status_code == 401


def test_theme_is_saved_per_user():
    with client_as('bd.lin') as lin, client_as('bd.zhou') as zhou:
        original = zhou.get('/api/me').json()['theme']
        assert lin.put('/api/me/theme', json={'theme': 'green'}).json()['theme'] == 'green'
        assert lin.get('/api/me').json()['theme'] == 'green'
        assert zhou.get('/api/me').json()['theme'] == original
        assert lin.put('/api/me/theme', json={'theme': 'unregistered'}).status_code == 422
    with client_as('bd.lin') as lin:
        assert lin.get('/api/me').json()['theme'] == 'green'


def test_source_configuration_no_secret_and_validation():
    with client_as() as client:
        payload = {'name': 'test-mysql', 'kind': 'mysql', 'host': 'read.internal', 'database': 'sales', 'credential_ref': 'BD_SOURCE_TEST'}
        created = client.post('/api/sources', json=payload)
        assert created.status_code == 201
        record = created.json()
        assert not record['credential_configured']
        assert 'password' not in record and 'access_key' not in record
        assert client.post('/api/sources', json=payload).status_code == 409
        assert client.post('/api/sources', json={**payload, 'name': 'bad-env', 'credential_ref': 'DATABASE_URL'}).status_code == 422
        assert client.post('/api/sources', json={**payload, 'name': 'bad-host', 'host': 'host;DROP TABLE users'}).status_code == 422
        assert client.post(f"/api/sources/{record['id']}/test").status_code == 422


def test_credentials_are_not_leaked_or_connected_without_approval(monkeypatch):
    with client_as() as client:
        payload = {'name': 'credential-boundary', 'kind': 'mysql', 'host': 'never-connect.internal', 'database': 'sales', 'credential_ref': 'BD_SOURCE_BOUNDARY'}
        source = client.post('/api/sources', json=payload).json()
        monkeypatch.setenv('BD_SOURCE_BOUNDARY', '{"username":"reader","password":"highly-sensitive-secret"}')
        listing = client.get('/api/sources').text
        assert 'highly-sensitive-secret' not in listing and '"password"' not in listing
        result = client.post(f"/api/sources/{source['id']}/test")
        assert result.status_code == 422
        assert 'BD_ALLOWED_SOURCE_HOSTS' in result.text
        monkeypatch.setenv('BD_ALLOWED_SOURCE_HOSTS', 'never-connect.internal')
        monkeypatch.delenv('BD_SOURCE_BOUNDARY')
        assert '凭证引用尚未' in client.post(f"/api/sources/{source['id']}/test").json()['detail']


def test_dataset_is_a_draft_and_validated():
    with client_as() as client:
        source = client.post('/api/sources', json={'name': 'mapping-source', 'kind': 'mysql', 'host': 'db.internal', 'database': 'business', 'credential_ref': 'BD_SOURCE_MAPPING'}).json()
        payload = {'name': 'orders-draft', 'source_id': source['id'], 'table_name': 'orders', 'target': 'orders', 'primary_key': 'order_id', 'owner_field': 'bd_id', 'mapping': {'order_no': 'order_id'}}
        response = client.post('/api/datasets', json=payload)
        assert response.status_code == 201 and '未启用同步' in response.json()['status']
        assert client.post('/api/datasets', json=payload).status_code == 409
        assert client.post('/api/datasets', json={**payload, 'name': 'bad-dataset', 'mapping': {'order_no': 'id;DROP'}}).status_code == 422
        assert client.post('/api/datasets', json={**payload, 'name': 'bad-source', 'source_id': 99999}).status_code == 404


def test_unconfirmed_rules_block_settlement():
    with client_as() as client:
        response = client.post('/api/settlements/preview')
        assert response.status_code == 409
        assert '尚未确认' in response.json()['detail']


def test_deactivated_account_loses_existing_session():
    with client_as() as admin, client_as('bd.zhou') as zhou:
        user_id = zhou.get('/api/me').json()['id']
        assert admin.put(f'/api/users/{user_id}/active', json={'active': False}).status_code == 200
        assert zhou.get('/api/bonuses').status_code == 401
        assert admin.put(f'/api/users/{user_id}/active', json={'active': True}).status_code == 200
        admin_id = admin.get('/api/me').json()['id']
        assert admin.put(f'/api/users/{admin_id}/active', json={'active': False}).status_code == 409


def test_account_creation_and_password_hashing():
    with client_as() as client:
        payload = {'username': 'new.bd', 'name': '新增商务', 'password': 'A-long-test-password!', 'role': 'bd'}
        response = client.post('/api/users', json=payload)
        assert response.status_code == 201 and 'password' not in response.json()
        assert client.post('/api/users', json=payload).status_code == 409
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.username == 'new.bd'))
            assert user.password != payload['password'] and ':' in user.password
        assert client.post('/api/users', json={**payload, 'username': 'weak.bd', 'password': '123'}).status_code == 422


def test_month_validation_and_decimal_balances():
    with client_as() as client:
        assert client.get('/api/bonuses?period=2026-99').status_code == 422
        with Session(engine) as db:
            for row in db.scalars(select(Bonus)):
                assert row.paid <= row.accrued
        assert client.get('/api/health').json()['status'] == 'ok'


def test_reference_data_permissions_and_fixture_file():
    with client_as('bd.lin') as client:
        result = client.get('/api/reference-data').json()
        assert result['rows'] == [] and result['source_total'] == 0
        assert result['options']['owners'] == []
    with client_as() as client:
        response = client.get('/api/reference-data?page_size=20')
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot['source_name'] == '参考数据.csv'
        assert snapshot['source_total'] == 3960
        assert len(snapshot['columns']) == 18
        assert len(snapshot['rows']) == 20
        assert snapshot['rows'][0]['values']['订单金额'] == '27.43'
        assert snapshot['rows'][0]['values']['BD姓名'] == ''
        assert snapshot['duplicate_order_rows'] == 466
        assert client.get('/api/reference-data?page_size=101').status_code == 422


def test_reference_filter_pagination_and_missing_file(monkeypatch, tmp_path):
    import csv
    sample = tmp_path / 'fixture.csv'
    with sample.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['季度', 'BD姓名', '付费项目', '订单金额', '订单号', '有/无归属BD'])
        writer.writerows([['2026Q4', '甲', '短信', '1.00', 'DUP', '有归属'], ['2026Q4', '甲', '短信', '2.00', 'DUP', '有归属'], ['2026Q3', '', '收费', '0.00', 'OTHER', '无归属']])
    monkeypatch.setenv('REFERENCE_CSV_PATH', str(sample))
    with client_as() as client:
        first = client.get('/api/reference-data?quarter=2026Q4&owner=甲&project=短信&page_size=1').json()
        second = client.get('/api/reference-data?quarter=2026Q4&owner=甲&project=短信&page_size=1&page=2').json()
        assert first['total'] == 2 and len(first['rows']) == 1
        assert first['rows'][0]['row_id'] != second['rows'][0]['row_id']
        assert second['rows'][0]['values']['订单金额'] == '2.00'
        assert client.get('/api/reference-data?ownership=无归属').json()['total'] == 1
        assert client.get('/api/reference-data?search=OTHER').json()['total'] == 1
        assert client.get('/api/reference-data?search=不存在').json()['rows'] == []
        monkeypatch.setenv('REFERENCE_CSV_PATH', str(tmp_path / 'missing.csv'))
        assert client.get('/api/reference-data').status_code == 404


@pytest.fixture
def business_accounts():
    initialize()
    with Session(engine) as db:
        for name in ['何卫', '余飞', '周政', '屈敬东', '崔赵鹏', '曾德康', '杨红星', '贺庆锋', '梁梓珊']:
            if not db.scalar(select(User.id).where(User.username == name)):
                db.add(User(username=name, name=name, role='superadmin' if name == '梁梓珊' else 'bd', password=hash_password('Test-only-password!')))
        db.commit()


def test_chinese_account_api_accepts_initial_pinyin_password():
    with client_as() as client:
        response = client.post('/api/users', json={'username': '测试中文', 'name': '测试中文', 'password': 'ceshizhongwen', 'role': 'bd'})
        assert response.status_code == 201
    with client_as('测试中文', 'ceshizhongwen') as client:
        assert client.get('/api/me').json()['username'] == '测试中文'


def test_every_bd_only_sees_own_reference_data(business_accounts):
    expected = {'何卫': 307, '余飞': 1, '周政': 288, '屈敬东': 504, '崔赵鹏': 47, '曾德康': 505, '杨红星': 447, '贺庆锋': 613}
    for name, count in expected.items():
        with client_as(name, 'Test-only-password!') as client:
            result = client.get('/api/reference-data').json()
            assert result['total'] == result['source_total'] == count
            assert result['access_scope'] == 'self'
            assert result['options']['owners'] == [name]
            assert all(r['values']['BD姓名'] == name for r in result['rows'])
            other = '周政' if name != '周政' else '何卫'
            assert client.get('/api/reference-data', params={'owner': other}).json()['total'] == 0
            assert client.get('/api/reference-data', params={'search': other}).json()['source_total'] == count


def test_scope_policy_superadmin_and_admin_account_global_switch(business_accounts):
    with client_as('梁梓珊', 'Test-only-password!') as root, client_as('何卫', 'Test-only-password!') as bd, client_as() as normal:
        original = root.get('/api/reference-data/policy').json()
        assert original['can_manage'] and original['self_only']
        payload = {'self_only': False, 'version': original['version']}
        assert bd.put('/api/reference-data/policy', json=payload).status_code == 403
        assert normal.get('/api/reference-data/policy').json()['can_manage']
        assert not bd.get('/api/reference-data/policy').json()['can_manage']
        disabled = root.put('/api/reference-data/policy', json=payload)
        assert disabled.status_code == 200
        try:
            all_rows = bd.get('/api/reference-data').json()
            assert all_rows['total'] == all_rows['source_total'] == 3960
            assert all_rows['access_scope'] == 'all'
            assert len(all_rows['options']['owners']) == 8
            assert bd.get('/api/reference-data?ownership=无归属').json()['total'] == 1248
            assert root.put('/api/reference-data/policy', json=payload).status_code == 409
            super_id = root.get('/api/me').json()['id']
            assert normal.put(f'/api/users/{super_id}/active', json={'active': False}).status_code == 403
        finally:
            current = root.get('/api/reference-data/policy').json()
            assert root.put('/api/reference-data/policy', json={'self_only': True, 'version': current['version']}).status_code == 200
        assert bd.get('/api/reference-data').json()['total'] == 307
        assert any('全部账单' in r['action'] for r in root.get('/api/audit').json())
        current = normal.get('/api/reference-data/policy').json()
        assert normal.put('/api/reference-data/policy', json={'self_only': True, 'version': current['version']}).status_code == 200


def test_other_admin_accounts_do_not_gain_scope_switch_permission():
    with client_as() as root:
        assert root.post('/api/users', json={'username': 'other.admin', 'name': '其他管理员', 'password': 'Other-admin-test!', 'role': 'admin'}).status_code == 201
    with client_as('other.admin', 'Other-admin-test!') as other:
        policy = other.get('/api/reference-data/policy').json()
        assert not policy['can_manage']
        assert other.put('/api/reference-data/policy', json={'self_only': False, 'version': policy['version']}).status_code == 403


def test_password_change_verifies_current_and_revokes_all_sessions():
    with client_as() as admin:
        assert admin.post('/api/users', json={'username': 'password.test', 'name': '改密测试', 'password': 'Original-test-password!', 'role': 'bd'}).status_code == 201
    with client_as('password.test', 'Original-test-password!') as first, client_as('password.test', 'Original-test-password!') as second:
        body = {'current_password': 'wrong', 'new_password': 'New-test-password!', 'confirm_password': 'New-test-password!'}
        assert first.put('/api/me/password', json=body).status_code == 400
        body['current_password'] = 'Original-test-password!'
        assert first.put('/api/me/password', json={**body, 'confirm_password': 'Different-password!'}).status_code == 422
        assert first.get('/api/me').status_code == 200
        assert first.put('/api/me/password', json=body).status_code == 200
        assert first.get('/api/me').status_code == 401
        assert second.get('/api/me').status_code == 401
        assert second.post('/api/login', json={'username': 'password.test', 'password': 'Original-test-password!'}).status_code == 401
    with client_as('password.test', 'New-test-password!') as client:
        assert client.get('/api/me').json()['username'] == 'password.test'
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.username == 'password.test'))
            assert 'New-test-password!' not in user.password


def test_commission_projection_company_date_and_sources():
    from backend.commission_data import project_row
    row = {'row_id': 2, 'values': {'付款户名': '优先公司', '业务id信息': '备用公司', '付费时间': '2026-10-25 19:57:20', '订单来源': '市场同事推荐', '订单来源补充': '', '奖金金额': '2.74'}}
    result = project_row(row)
    assert result['company'] == '优先公司'
    assert result['paid_date'] == '2026年10月25日'
    assert result['market_pending'] and result['market_bd'] == ''
    assert result['enabled'] is None and result['bonus'] is None
    row['values']['付款户名'] = ' '
    row['values']['订单来源'] = '协会推荐'
    assert project_row(row)['company'] == '备用公司'
    assert project_row(row)['referral'] == '协会推荐'
    assert project_row(row, {'enabled': True}, {'enabled': False, 'note': '本单例外'})['enabled'] is False


def test_commission_scope_and_admin_only_edits(business_accounts):
    with client_as('何卫', 'Test-only-password!') as bd:
        result = bd.get('/api/commission-data').json()
        assert result['total'] == 307 and not result['can_edit']
        assert all(row['owner'] == '何卫' for row in result['rows'])
        assert result['options']['owners'] == ['何卫']
        assert bd.get('/api/commission-data?owner=周政').json()['total'] == 0
        assert bd.put('/api/commission-data/service-rule', json={'service': '短信', 'enabled': True, 'note': '测试'}).status_code == 403
        assert bd.put('/api/commission-data/confirmation', json={'record_key': result['rows'][0]['record_key'], 'version': 0, 'note': '测试'}).status_code == 403


def test_commission_service_rules_confirmation_and_conflict():
    with client_as() as client:
        snapshot = client.get('/api/commission-data').json()
        assert snapshot['total'] == 3960 and snapshot['can_edit']
        row = next(r for r in snapshot['rows'] if r['service'] in snapshot['pending_services'])
        assert row['service'] in snapshot['pending_services']
        assert client.put('/api/commission-data/service-rule', json={'service': row['service'], 'enabled': True, 'note': '已确认该服务计发'}).status_code == 200
        updated = client.get('/api/commission-data').json()
        assert row['service'] not in updated['pending_services']
        assert next(r for r in updated['rows'] if r['record_key']==row['record_key'])['enabled'] is True
        payload = {'record_key': row['record_key'], 'version': 0, 'enabled': False, 'shared_bd': '测试合作BD', 'allocation_ratio': '0.5', 'bonus_basis': '12.34', 'market_bd': '测试市场BD', 'confirmed_rate': '0.03', 'bonus': '0.37', 'is_paid': False, 'is_refunded': None, 'note': '本单人工确认测试'}
        assert client.put('/api/commission-data/confirmation', json=payload).status_code == 200
        confirmed = next(r for r in client.get('/api/commission-data').json()['rows'] if r['record_key']==row['record_key'])
        assert confirmed['enabled'] is False and confirmed['note'] == payload['note']
        assert confirmed['bonus_basis'] == '12.34' and confirmed['bonus'] == '0.37'
        assert confirmed['is_paid'] is False and confirmed['is_refunded'] is None
        assert client.put('/api/commission-data/confirmation', json=payload).status_code == 409
        assert client.put('/api/commission-data/confirmation', json={**payload, 'version': 1, 'allocation_ratio': '1.1'}).status_code == 422
        assert client.put('/api/commission-data/service-rule', json={'service': '不存在的服务', 'enabled': True, 'note': '测试'}).status_code == 422


def test_sales_source_samples_are_scoped_and_do_not_change_orders(business_accounts, monkeypatch, tmp_path):
    import json
    from backend import sales_workspace
    (tmp_path / 'data').mkdir()
    sample = {'sheet': '原表样例', 'columns': ['BD姓名', '订单号'], 'rows': [
        {'BD姓名': '何卫', '订单号': 'SAMPLE-HE'}, {'BD姓名': '周政', '订单号': 'SAMPLE-ZHOU'}]}
    (tmp_path / 'data' / 'sales-source-samples.json').write_text(json.dumps({k: sample for k in ['splits', 'targets', 'orders', 'segmentation', 'services']}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(sales_workspace, 'ROOT', tmp_path)
    with client_as() as manager:
        classification = manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories', json={'mapping': {**classification['mapping'], '何卫': 'sales'}, 'version': classification['version']})
        before = manager.get('/api/commission-data?category=sales&owner=何卫').json()
        for kind in sales_workspace.SOURCE_TITLES:
            response = manager.get('/api/sales-workspace/sources/' + kind)
            assert response.status_code == 200 and response.json()['read_only'] is True
            assert response.json()['sample'] is (kind != 'constants')
        assert len(manager.get('/api/sales-workspace/sources/constants').json()['rows']) == 9
        assert manager.get('/api/sales-workspace/sources/unknown').status_code == 404
        after = manager.get('/api/commission-data?category=sales&owner=何卫').json()
        assert before == after
    with client_as('何卫', 'Test-only-password!') as bd:
        for kind in ['splits', 'targets', 'orders', 'segmentation']:
            rows = bd.get('/api/sales-workspace/sources/' + kind).json()['rows']
            assert rows and {row['BD姓名'] for row in rows} == {'何卫'}
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/sales-workspace/sources/targets').status_code == 401


def test_sales_hidden_eligibility_preserves_raw_rule_before_manual_override():
    from backend.sales_formulas import calculate_sales
    record = sales_case(enabled=False, confirmation={'enabled': True})
    row = calculate_sales([record])[0]
    assert row['enabled'] is True
    assert row['calculation']['service_eligible'] is False
    row = calculate_sales([sales_case()])[0]
    assert row['market_recommended'] is False



def test_editable_five_sales_formulas_change_real_downstream_results():
    from backend.sales_formulas import calculate_sales
    from backend.sales_expression import SPECS
    def run(column=None, expression=None, **kwargs):
        return calculate_sales([sales_case('100', **kwargs)], {column: expression} if column else None)[0]
    assert Decimal(run()['bonus']) == 10
    assert Decimal(run('J', '0.5')['bonus']) == 5
    assert Decimal(run('K', 'ROUND(H * J, 2) * 2')['bonus']) == 20
    assert run('S', '假')['enabled'] is False and Decimal(run('S', '假')['bonus']) == 0
    assert run('S', 'H >= 50', enabled=False)['enabled'] is True
    assert Decimal(run('T', '前序累计 + 本单计入基数 * 2', target='150')['bonus']) == Decimal('12.5')
    assert Decimal(run('X', '0.20')['bonus']) == 20
    crossed = calculate_sales([sales_case('100', target='150'), sales_case('100', target='150', row_id=2)], {'X': 'IF(V, 0.25, 0.12)'})
    assert Decimal(crossed[1]['bonus']) == Decimal('18.50')
    assert Decimal(crossed[1]['calculation']['segmented_bonus']) == Decimal('18.50')
    assert crossed[1]['rate_display'] == '12.00% / 25.00%'
    assert Decimal(run('X', '0.20', target=None)['bonus']) == 20
    assert run(target=None)['bonus'] is None
    assert run('K', 'H * 9', confirmation={'bonus_basis': '50'})['bonus_basis'] == '50'
    assert run('S', '假', confirmation={'enabled': True})['enabled'] is True
    row = run('J', '0.5', confirmation={'bonus': '123'})
    assert row['bonus'] == '123' and '奖金' in row['calculation']['overrides']
    assert set(SPECS) == {'S', 'J', 'K', 'T', 'X'}


@pytest.mark.parametrize('column,expression', [
    ('K', '__import__("os").system("echo invalid")'), ('K', 'H.__class__'),
    ('K', '[H for x in [1]]'), ('K', '2 ** 10000'), ('K', 'open("file")'),
    ('K', 'X * H'), ('T', 'T + K'), ('S', 'K > 0'), ('X', 'AA'),
    ('X', 'Y'), ('K', 'eval("1")'), ('K', '(lambda: 1)()'),
    ('K', 'ROUND(H, digits=2)'), ('K', '1e100000'), ('K', 'H' * 2001),
    ('K', '[' * 100 + '0' + ']' * 100),
])
def test_formula_language_rejects_code_cycles_and_unbounded_expressions(column, expression):
    from backend.sales_expression import parse_formula, FormulaError
    with pytest.raises(FormulaError): parse_formula(column, expression)


def test_formula_decimal_lazy_branches_validation_and_missing_values():
    from backend.sales_expression import evaluate_formula, FormulaError
    assert evaluate_formula('K', 'ROUND(1.005, 2)', {}) == Decimal('1.01')
    assert evaluate_formula('K', '0.1 + 0.2', {}) == Decimal('0.3')
    assert evaluate_formula('K', 'IF(真, 3, 1 / 0)', {}) == 3
    assert evaluate_formula('K', 'COALESCE(H, 5)', {'H': None}) == 5
    assert evaluate_formula('K', 'H * 2', {'H': None}) is None
    assert evaluate_formula('S', 'IF(H > 1, "是", "否")', {'H': Decimal(2)}) is True
    assert evaluate_formula('S', 'AND(假, 空值)', {}) is False
    assert evaluate_formula('S', 'OR(真, 空值)', {}) is True
    for column, expression in [('J', '2'), ('X', '-0.1'), ('S', '1'), ('K', '-1'), ('K', '1 / 0'), ('K', 'ROUND(1, 9)'), ('K', '"text" * 2')]:
        with pytest.raises(FormulaError): evaluate_formula(column, expression, {})


def test_all_fixed_formulas_reject_free_rewrites_and_ignore_legacy_text(business_accounts):
    from backend.app import SystemSetting
    from backend.sales_formulas import setting_key
    with client_as() as manager:
        definitions = manager.get('/api/sales-formulas/definitions').json()['definitions']
        assert {item['column'] for item in definitions} == {'S','J','K','T','X'}
        for item in definitions:
            assert item['editor_mode'] in ('fixed','fixed_parameters') and item['custom'] is False
            for method in ['put','post']:
                url='/api/sales-formulas/definitions/'+item['column']+('/preview' if method=='post' else '')
                assert getattr(manager,method)(url,json={'expression':'0','version':item['version']}).status_code==422
        before=manager.get('/api/commission-data?category=sales').json()
        key=setting_key('formula','K')
        with Session(engine) as db:
            assert db.get(SystemSetting,key) is None
            db.add(SystemSetting(key=key,value='{"expression":"H * 2"}',version=1));db.commit()
        try:
            assert manager.get('/api/commission-data?category=sales').json()==before
            k=next(item for item in manager.get('/api/sales-formulas/definitions').json()['definitions'] if item['column']=='K')
            assert k['expression']==k['default_expression'] and k['custom'] is False
        finally:
            with Session(engine) as db:
                db.delete(db.get(SystemSetting,key));db.commit()
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/sales-formulas/definitions').status_code==401


@pytest.mark.parametrize('amount,minimum,expected', [('1679.99','1680',False),('1680','1680',True),('1680','2000',False),('2000','2000',True)])
def test_fixed_eligibility_expands_vip_threshold(amount, minimum, expected):
    from backend.sales_formulas import calculate_sales
    item = sales_case(amount)
    item['row']['service'] = '团队VIP'; item['rule'] = {}
    item['period']['vip_minimum'] = minimum
    row = calculate_sales([item])[0]
    assert row['enabled'] is expected
    assert row['calculation']['service_eligible'] is expected


def test_fixed_eligibility_non_vip_lookup_missing_amount_and_manual_priority():
    from backend.sales_formulas import calculate_sales
    from backend.sales_expression import SPECS
    assert SPECS['S']['default'] != 'R' and '所购服务' in SPECS['S']['default']
    for rule in [True, False, None]:
        item = sales_case(enabled=rule)
        assert calculate_sales([item])[0]['enabled'] is rule
    item = sales_case('bad'); item['row']['service'] = '团队VIP'
    assert calculate_sales([item])[0]['enabled'] is None
    item = sales_case('100', confirmation={'enabled': True}); item['row']['service'] = '团队VIP'
    row = calculate_sales([item])[0]
    assert row['enabled'] is True and row['calculation']['service_eligible'] is False


def test_fixed_eligibility_api_locks_rule_and_previews_global_parameter(business_accounts):
    with client_as() as manager:
        cats = manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories', json={'mapping': {**cats['mapping'], '何卫':'sales'}, 'version': cats['version']})
        definitions = manager.get('/api/sales-formulas/definitions').json()['definitions']
        fixed = next(item for item in definitions if item['column'] == 'S')
        others = [item for item in definitions if item['column'] != 'S']
        assert fixed['editor_mode'] == 'fixed_parameters' and fixed['editable_parameters'] == ['vip_minimum']
        assert '订单金额' in fixed['expression'] and '服务规则查询结果' in fixed['expression']
        for method in ['put', 'post']:
            url = '/api/sales-formulas/definitions/S' + ('/preview' if method == 'post' else '')
            assert getattr(manager, method)(url, json={'expression':'真','version':fixed['version']}).status_code == 422
        records = manager.get('/api/commission-data', params={'category':'sales','owner':'何卫','search':'团队VIP','page_size':100}).json()['rows']
        chosen = next(row for row in records if not row['confirmation'])
        query = {'owner':'何卫','quarter':chosen['quarter'],'record':chosen['record_key']}
        inputs = manager.get('/api/sales-formulas/inputs',params=query).json()
        period = {**inputs['period'],'target':'100000','threshold':'0','vip_minimum':'20'}
        assert manager.put('/api/sales-formulas/inputs/period',json={**query,'period':period,'version':inputs['period_version'],'note':'VIP边界测试'}).status_code == 200
        inputs = manager.get('/api/sales-formulas/inputs',params=query).json()
        before = manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()
        row_before = next(row for row in before['rows'] if row['record_key'] == chosen['record_key'])
        assert row_before['enabled'] is True and Decimal(row_before['bonus']) > 0
        payload = {**query,'version':inputs['period_version'],'vip_minimum':'100'}
        preview = manager.post('/api/sales-formulas/eligibility/preview',json=payload)
        assert preview.status_code == 200 and preview.json()['valid'] and preview.json()['bonus_changed_count'] > 0
        assert preview.json()['total'] >= len(before['rows'])
        assert manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json() == before
        assert manager.post('/api/sales-formulas/eligibility/preview',json={**payload,'vip_minimum':-1}).status_code == 422
        assert manager.post('/api/sales-formulas/eligibility/preview',json={**payload,'version':inputs['period_version']+1}).status_code == 409
        assert manager.put('/api/sales-formulas/inputs/period',json={**query,'period':{**period,'vip_minimum':'100'},'version':inputs['period_version'],'note':'保存VIP金额下限'}).status_code == 200
        after = manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()
        row_after = next(row for row in after['rows'] if row['record_key'] == chosen['record_key'])
        assert row_after['enabled'] is False and Decimal(row_after['bonus']) == 0
        assert [item for item in manager.get('/api/sales-formulas/definitions').json()['definitions'] if item['column'] != 'S'] == others
        names,sheets = workbook_sheets(manager.get('/api/bonus-export/sales',params={'owner':'何卫'}).content)
        index = next(i for i,row in enumerate(after['rows']) if row['record_key'] == chosen['record_key'])
        assert Decimal(sheets[0][index+1][15].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v').text) == 0
    with client_as('何卫','Test-only-password!') as bd:
        assert bd.post('/api/sales-formulas/eligibility/preview',json=payload).status_code == 403



def test_fixed_rule_parameter_whitelist_preview_persistence_scope_and_export(business_accounts):
    with client_as() as manager:
        cats=manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales'},'version':cats['version']})
        records=manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()['rows']
        chosen=next(row for row in records if row['service']=='收费系统户数' and not row['confirmation'])
        query={'owner':'何卫','quarter':chosen['quarter'],'record':chosen['record_key']}
        inputs=manager.get('/api/sales-formulas/inputs',params=query).json()
        period={**inputs['period'],'target':'1000000','threshold':'0','self_rate':'10','include_ineligible':True}
        assert manager.put('/api/sales-formulas/inputs/period',json={**query,'period':period,'version':inputs['period_version'],'note':'固定参数测试准备'}).status_code==200
        assert manager.put('/api/sales-formulas/service',json={**query,'version':inputs['service_version'],'enabled':True,'note':'固定规则服务准备'}).status_code==200
        inputs=manager.get('/api/sales-formulas/inputs',params=query).json()
        before=manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()
        market=manager.get('/api/commission-data?category=market').json()
        body={**query,'version':inputs['period_version'],'parameters':{'self_rate':'20'},'note':'修改自拓目标内提点'}
        preview=manager.post('/api/sales-formulas/parameters/X/preview',json=body)
        assert preview.status_code==200 and preview.json()['valid'] and preview.json()['bonus_changed_count']>0
        assert preview.json()['total'] >= len(before['rows'])
        assert manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()==before
        saved=manager.put('/api/sales-formulas/parameters/X',json=body)
        assert saved.status_code==200,saved.text
        assert saved.json()['period']['vip_minimum']==inputs['period']['vip_minimum']
        assert saved.json()['period']['target']==inputs['period']['target']
        assert saved.json()['period']['include_ineligible'] is True
        assert manager.put('/api/sales-formulas/parameters/X',json=body).status_code==409
        version=saved.json()['version']
        for column,parameters in [('X',{'self_rate':101}),('X',{'threshold':-1}),('X',{'target':1}),('T',{'include_ineligible':'false'}),('T',{'renewal_rate':5}),('J',{'threshold':0}),('K',{'precision':3})]:
            assert manager.put('/api/sales-formulas/parameters/'+column,json={**body,'version':version,'parameters':parameters}).status_code==422
        assert manager.get('/api/sales-formulas/inputs',params=query).json()['period_version']==version
        after=manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()
        old=next(row for row in before['rows'] if row['record_key']==chosen['record_key'])
        new=next(row for row in after['rows'] if row['record_key']==chosen['record_key'])
        assert Decimal(new['bonus'])==Decimal(old['bonus'])*2
        assert new['bonus_basis']==old['bonus_basis']
        assert manager.get('/api/commission-data?category=market').json()==market
        _,sheets=workbook_sheets(manager.get('/api/bonus-export/sales',params={'owner':'何卫'}).content)
        index=next(i for i,row in enumerate(after['rows']) if row['record_key']==chosen['record_key'])
        assert Decimal(sheets[0][index+1][15].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v').text)==Decimal(new['bonus'])
        restore=manager.put('/api/sales-formulas/parameters/X',json={**body,'version':version,'parameters':{'self_rate':'10'}})
        assert restore.status_code==200
        assert manager.get('/api/commission-data',params={'category':'sales','owner':'何卫','page_size':100}).json()['rows']==before['rows']
    with client_as('何卫','Test-only-password!') as bd:
        assert bd.put('/api/sales-formulas/parameters/X',json=body).status_code==403
        assert bd.post('/api/sales-formulas/parameters/X/preview',json=body).status_code==403


def test_fixed_cumulative_scope_and_segmented_parameters_affect_downstream():
    from backend.sales_formulas import calculate_sales
    a=sales_case('100',enabled=False,threshold='150',target='1000')
    b=sales_case('100',row_id=2,threshold='150',target='1000')
    included=calculate_sales([a,b])
    assert included[1]['revenue_total']=='200.00' and Decimal(included[1]['bonus'])==10
    a=sales_case('100',enabled=False,threshold='150',target='1000');a['period']['include_ineligible']=False
    b=sales_case('100',row_id=2,threshold='150',target='1000');b['period']['include_ineligible']=False
    excluded=calculate_sales([a,b])
    assert Decimal(excluded[1]['revenue_total'])==100 and Decimal(excluded[1]['bonus'])==0
    a=sales_case('100',target='150');b=sales_case('100',row_id=2,target='150')
    for record in [a,b]:record['period'].update(self_rate='12',self_excess='25')
    crossed=calculate_sales([a,b])
    assert Decimal(crossed[1]['bonus'])==Decimal('18.5')
    assert crossed[1]['rate_display']=='12.00% / 25.00%'


@pytest.fixture
def isolated_rule_settings():
    from sqlalchemy import delete
    from backend.app import SystemSetting
    with Session(engine) as db:
        previous = [(r.key, r.value, r.version) for r in db.scalars(select(SystemSetting))]
        db.execute(delete(SystemSetting))
        db.commit()
    yield
    from backend.app import SystemSetting
    with Session(engine) as db:
        db.execute(delete(SystemSetting))
        db.add_all([SystemSetting(key=k,value=v,version=n) for k,v,n in previous])
        db.commit()


def test_global_service_source_parameters_targets_and_exports(business_accounts, isolated_rule_settings, monkeypatch, tmp_path):
    import importlib
    from backend.app import SystemSetting
    from backend.bonus_rules import PLAN_KEY, TARGETS_KEY, GLOBAL_KEY
    from backend.sales_formulas import setting_key
    module = importlib.import_module('backend.app')
    samples = tmp_path / 'rule-sources.json'
    samples.write_text(json.dumps({
        'services': {'sheet':'2025年奖金方案','columns':['所购服务','是否计入提成范围'],'rows':[
            {'所购服务':'收费系统户数','是否计入提成范围':'是'},
            {'所购服务':'不计提测试服务','是否计入提成范围':'否'}]},
        'targets': {'sheet':'奖金汇总表','columns':['BD姓名','季度','直接营收目标'],'rows':[
            {'BD姓名':'何卫','季度':'2026Q3','直接营收目标':260000},
            {'BD姓名':'屈敬东','季度':'2026Q3','直接营收目标':160000}]}
    },ensure_ascii=False),encoding='utf-8')
    monkeypatch.setenv('BONUS_SOURCE_SAMPLES_PATH', str(samples))
    raw=[]
    def add(owner,quarter,service,amount='1680'):
        index=len(raw)+1
        values={key:'' for key in fixture_columns}
        values.update({'季度':quarter,'BD姓名':owner,'付费时间':'2026-07-01 10:00:00' if quarter=='2026Q3' else '2026-10-01 10:00:00','付费项目':service,'订单金额':amount,'首购/续费':'续费','订单号':f'GLOBAL-{index}'})
        raw.append({'row_id':index,'values':values})
    for name in ['何卫','屈敬东']:
        for quarter in ['2026Q3','2026Q4']:
            add(name,quarter,'团队VIP')
    add('何卫','2026Q4','收费系统户数','4427.40')
    add('屈敬东','2026Q4','不计提测试服务','100')
    add('屈敬东','2026Q4','未知测试服务','100')
    add('周政','2026Q3','团队VIP')
    add('周政','2026Q4','收费系统户数','4427.40')
    add('周政','2026Q4','不计提测试服务','100')
    def query(page=1,page_size=20,search='',quarter='',owner='',allowed_owner=None,allowed_owners=None,**kwargs):
        base=[r for r in raw if (allowed_owner is None or r['values']['BD姓名']==allowed_owner) and (allowed_owners is None or r['values']['BD姓名'] in allowed_owners)]
        selected=[r for r in base if (not owner or r['values']['BD姓名']==owner) and (not quarter or r['values']['季度']==quarter) and (not search or search in str(r['values']))]
        return {'rows':selected[(page-1)*page_size:page*page_size],'total':len(selected),'options':{'owners':sorted({r['values']['BD姓名'] for r in base}),'quarters':sorted({r['values']['季度'] for r in base}),'projects':sorted({r['values']['付费项目'] for r in base})}}
    monkeypatch.setattr(module,'query_reference',query)
    with Session(engine) as db:
        db.add(SystemSetting(key='bd_categories',value=json.dumps({'何卫':'sales','屈敬东':'sales','周政':'market'}),version=1))
        # Old per-person constants must not leak into shared parameters; target is retained.
        db.add(SystemSetting(key=setting_key('period','屈敬东','2026Q4'),value=json.dumps({'target':'50000','vip_minimum':'9999','renewal_rate':'99'}),version=1))
        db.commit()
    with client_as() as manager:
        assert manager.post('/api/bonus-config/plans/2026/inherit',json={'version':0}).status_code==200
        def rows(kind='sales'):
            return manager.get('/api/commission-data',params={'category':kind,'page_size':100}).json()['rows']
        sales=rows();chosen=sales[0]
        assert next(r for r in sales if r['service']=='收费系统户数')['enabled'] is True
        assert next(r for r in sales if r['service']=='不计提测试服务')['enabled'] is False
        assert next(r for r in sales if r['service']=='未知测试服务')['enabled'] is None
        assert [r['enabled'] for r in rows('market')]==[True,True,False]
        inputs=[]
        for row in sales[:4]:
            context={'owner':row['owner'],'quarter':row['quarter'],'record':row['record_key']}
            config=manager.get('/api/sales-formulas/inputs',params=context).json()
            assert config['parameter_scope']=='global' and config['period']['vip_minimum']=='1680'
            inputs.append((context,config))
        assert [item[1]['period']['target'] for item in inputs]==[260000,None,160000,'50000']
        context,config=inputs[0]
        response=manager.put('/api/sales-formulas/parameters/X',json={**context,'version':config['period_version'],'parameters':{'threshold':'0'}})
        assert response.status_code==200,response.text
        initial=rows();assert all(Decimal(r['bonus'])==Decimal('50.4') for r in initial[:4])
        config=manager.get('/api/sales-formulas/inputs',params=context).json()
        rate_body={**context,'version':config['period_version'],'parameters':{'renewal_rate':'6'}}
        rate_saved=manager.put('/api/sales-formulas/parameters/X',json=rate_body)
        assert rate_saved.status_code==200,rate_saved.text
        assert all(Decimal(r['bonus'])==Decimal('100.8') for r in rows()[:4])
        for other,old in inputs:
            config=manager.get('/api/sales-formulas/inputs',params=other).json()
            assert config['period']['renewal_rate']=='6' and config['period']['target']==old['period']['target']
        assert manager.put('/api/sales-formulas/parameters/X',json={**rate_body,'version':rate_saved.json()['version'],'parameters':{'renewal_rate':'3'}}).status_code==200
        assert rows()==initial
        config=manager.get('/api/sales-formulas/inputs',params=context).json()
        body={**context,'version':config['period_version'],'parameters':{'vip_minimum':'2000'}}
        preview=manager.post('/api/sales-formulas/parameters/S/preview',json=body)
        assert preview.status_code==200 and preview.json()['total']==7
        changed=[r for r in preview.json()['rows'] if r['changed']]
        assert {(r['owner'],r['quarter']) for r in changed}=={(n,q) for n in ['何卫','屈敬东'] for q in ['2026Q3','2026Q4']}
        assert rows()==initial  # global trial never persists
        saved=manager.put('/api/sales-formulas/parameters/S',json=body)
        assert saved.status_code==200,saved.text
        assert manager.put('/api/sales-formulas/parameters/S',json=body).status_code==409
        after=rows();assert all(r['enabled'] is False and Decimal(r['bonus'])==0 for r in after[:4])
        assert [r['enabled'] for r in rows('market')]==[False,True,False]
        for context,old in inputs:
            new=manager.get('/api/sales-formulas/inputs',params=context).json()
            assert new['period']['vip_minimum']=='2000' and new['period']['target']==old['period']['target']
        names,sheets=workbook_sheets(manager.get('/api/bonus-export/sales').content)
        for sheet in sheets:
            vip=[r for r in sheet[1:] if r[4].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t').text=='团队VIP']
            assert vip and all(Decimal(r[15].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v').text)==0 for r in vip)
        for kind in ['services','targets','constants']:
            source=manager.get('/api/sales-workspace/sources/'+kind).json()
            assert source['active'] is True and source['sample'] is False
        samples.unlink()  # database owns the active rules after import
        assert rows()==after
    with client_as() as restarted:
        assert restarted.get('/api/commission-data?category=sales').json()['rows']==after
    with client_as('何卫','Test-only-password!') as bd:
        assert {r['owner'] for r in bd.get('/api/commission-data?category=sales').json()['rows']}=={'何卫'}
        assert bd.put('/api/sales-formulas/parameters/S',json=body).status_code==403
    with Session(engine) as db:
        persisted=json.loads(db.get(SystemSetting,GLOBAL_KEY).value)
        assert 'target' not in persisted and persisted['vip_minimum']=='2000'
        assert db.get(SystemSetting,PLAN_KEY) and db.get(SystemSetting,TARGETS_KEY)


def test_rule_source_rejects_conflicting_services_without_partial_import(isolated_rule_settings,monkeypatch,tmp_path):
    from backend.bonus_rules import initialize_rule_sources, PLAN_KEY
    from backend.app import SystemSetting
    source=tmp_path/'invalid-rules.json'
    source.write_text(json.dumps({'services':{'sheet':'2025年奖金方案','rows':[
        {'所购服务':'同一服务','是否计入提成范围':'是'},
        {'所购服务':'同一服务','是否计入提成范围':'否'}]}}),encoding='utf-8')
    monkeypatch.setenv('BONUS_SOURCE_SAMPLES_PATH',str(source))
    with Session(engine) as db:
        with pytest.raises(ValueError,match='冲突'):
            initialize_rule_sources(db)
        db.rollback()
        assert db.get(SystemSetting,PLAN_KEY) is None


@pytest.fixture
def v005_sources(isolated_rule_settings,monkeypatch,tmp_path):
    source=tmp_path/'v005-sources.json'
    source.write_text(json.dumps({
        'services':{'sheet':'2025年奖金方案','columns':['所购服务','是否计入提成范围'],'rows':[
            {'所购服务':'收费系统户数','是否计入提成范围':'是'},
            {'所购服务':'短信','是否计入提成范围':'否'}]},
        'targets':{'sheet':'奖金汇总表','columns':['BD姓名','季度','直接营收目标'],'rows':[
            {'BD姓名':'何卫','季度':'2026Q3','直接营收目标':60000},
            {'BD姓名':'屈敬东','季度':'2026Q3','直接营收目标':30000}]}
    },ensure_ascii=False),encoding='utf-8')
    monkeypatch.setenv('BONUS_SOURCE_SAMPLES_PATH',str(source))
    return source


def test_v005_targets_quarter_inheritance_edit_and_calculation(business_accounts,v005_sources):
    with client_as() as manager:
        initial=manager.get('/api/bonus-config/targets').json()
        assert initial['quarter']=='2026Q3' and len(initial['rows'])==2
        empty=manager.get('/api/bonus-config/targets?quarter=2026Q4').json()
        assert empty['rows']==[] and empty['can_copy'] and empty['previous_quarter']=='2026Q3'
        result=manager.post('/api/bonus-config/targets/2026Q4/inherit',json={'version':empty['version']})
        assert result.status_code==200,result.text
        copied=result.json()
        assert {r['BD姓名'] for r in copied['rows']} >= {'何卫','屈敬东','余飞','周政','崔赵鹏','曾德康','杨红星','贺庆锋'}
        assert next(r for r in copied['rows'] if r['BD姓名']=='何卫')['直接营收目标']==60000
        assert next(r for r in copied['rows'] if r['BD姓名']=='余飞')['直接营收目标'] is None
        assert manager.post('/api/bonus-config/targets/2026Q4/inherit',json={'version':copied['version']}).status_code==409
        body={'version':copied['version'],'rows':[{'owner':r['BD姓名'],'target':'90000' if r['BD姓名']=='何卫' else r['直接营收目标']} for r in copied['rows']]}
        saved=manager.put('/api/bonus-config/targets/2026Q4',json=body)
        assert saved.status_code==200,saved.text
        assert manager.put('/api/bonus-config/targets/2026Q4',json=body).status_code==409
        cats=manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales'},'version':cats['version']})
        row=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        config=manager.get('/api/sales-formulas/inputs',params={'owner':'何卫','quarter':'2026Q4','record':row['record_key']}).json()
        assert Decimal(config['period']['target'])==90000
        previous=manager.get('/api/bonus-config/targets?quarter=2026Q3').json()
        assert next(r for r in previous['rows'] if r['BD姓名']=='何卫')['直接营收目标']==60000
        version=saved.json()['version']
        next_year=manager.post('/api/bonus-config/targets/2027Q1/inherit',json={'version':version})
        assert next_year.status_code==200 and next_year.json()['previous_quarter']=='2026Q4'
        assert all(r['季度']=='2027Q1' for r in next_year.json()['rows'])
        assert next(r for r in next_year.json()['rows'] if r['BD姓名']=='何卫')['直接营收目标']=='90000'
        assert manager.post('/api/bonus-config/targets/2027Q3/inherit',json={'version':next_year.json()['version']}).status_code==409
        assert manager.get('/api/bonus-config/targets?quarter=2026Q5').status_code==422
        invalid={**body,'version':next_year.json()['version'],'rows':[{'owner':'何卫','target':-1}]}
        assert manager.put('/api/bonus-config/targets/2026Q4',json=invalid).status_code==422
    with client_as('何卫','Test-only-password!') as bd:
        visible=bd.get('/api/bonus-config/targets?quarter=2026Q4').json()
        assert not visible['can_edit'] and {r['BD姓名'] for r in visible['rows']}=={'何卫'}
        assert bd.put('/api/bonus-config/targets/2026Q4',json=body).status_code==403
        assert bd.post('/api/bonus-config/targets/2027Q2/inherit',json={'version':0}).status_code==403


def test_v005_annual_plan_edit_new_service_year_isolation_and_inheritance(business_accounts,v005_sources):
    from backend.bonus_rules import shared_service_rule,order_year
    from backend.bonus_config import all_settings
    with client_as() as manager:
        initial=manager.get('/api/bonus-config/plans').json()
        assert initial['year']==2025 and initial['exists'] and len(initial['rows'])==2
        empty=manager.get('/api/bonus-config/plans?year=2026').json()
        assert not empty['exists'] and empty['rows']==[] and empty['can_copy']
        assert manager.post('/api/bonus-config/plans/2027/inherit',json={'version':0}).status_code==409
        inherited=manager.post('/api/bonus-config/plans/2026/inherit',json={'version':0})
        assert inherited.status_code==200,inherited.text
        current=inherited.json()
        assert current['rows']==initial['rows']
        assert manager.post('/api/bonus-config/plans/2026/inherit',json={'version':0}).status_code==409
        body={'version':current['version'],'rows':[{'service':r['所购服务'],'enabled':False} for r in current['rows']]+[{'service':'马克智能水电表','enabled':True}]}
        saved=manager.put('/api/bonus-config/plans/2026',json=body)
        assert saved.status_code==200,saved.text
        assert manager.put('/api/bonus-config/plans/2026',json=body).status_code==409
        assert manager.get('/api/bonus-config/plans?year=2025').json()['rows']==initial['rows']
        with Session(engine) as db:
            settings=all_settings(db)
            assert shared_service_rule(settings,'收费系统户数',year=2025)['enabled'] is True
            assert shared_service_rule(settings,'收费系统户数',year=2026)['enabled'] is False
            assert shared_service_rule(settings,'马克智能水电表',year=2026)['enabled'] is True
            assert shared_service_rule(settings,'马克智能水电表',year=2025)['issue']=='missing_service'
            assert shared_service_rule(settings,'收费系统户数',year=2027)['issue']=='missing_year_plan'
            assert order_year({'付费时间':'2026-10-25 10:00:00'})==2026
            assert order_year({'付费时间':'bad'}) is None
        # List and export must use the payment year, rather than latest available scheme.
        cats=manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales','周政':'market'},'version':cats['version']})
        sales=manager.get('/api/commission-data?category=sales&owner=何卫&search=收费系统户数&page_size=100').json()['rows']
        assert sales and all(r['enabled'] is False and Decimal(r['bonus'])==0 for r in sales)
        market=manager.get('/api/commission-data?category=market&owner=周政&search=收费系统户数').json()['rows']
        assert market and all(r['enabled'] is False for r in market)
        _,sheets=workbook_sheets(manager.get('/api/bonus-export/sales?owner=何卫&search=收费系统户数').content)
        assert all(Decimal(r[15].find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v').text)==0 for r in sheets[0][1:])
        version=saved.json()['version']
        assert manager.put('/api/bonus-config/plans/2026',json={'version':version,'rows':[{'service':'收费系统户数','enabled':True}]*2}).status_code==422
        assert manager.put('/api/bonus-config/plans/2026',json={'version':version,'rows':[{'service':'收费系统户数','enabled':'是'}]}).status_code==422
        inherited_next=manager.post('/api/bonus-config/plans/2027/inherit',json={'version':0})
        assert inherited_next.status_code==200 and inherited_next.json()['rows']==saved.json()['rows']
    with client_as('何卫','Test-only-password!') as bd:
        assert not bd.get('/api/bonus-config/plans?year=2026').json()['can_edit']
        assert bd.put('/api/bonus-config/plans/2026',json=body).status_code==403
        assert bd.post('/api/bonus-config/plans/2028/inherit',json={'version':0}).status_code==403


def test_v005_constants_share_storage_and_version_with_gears(business_accounts,v005_sources):
    with client_as() as manager:
        cats=manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales'},'version':cats['version']})
        row=manager.get('/api/commission-data?category=sales&owner=何卫&search=团队VIP').json()['rows'][0]
        query={'owner':'何卫','quarter':row['quarter'],'record':row['record_key']}
        initial=manager.get('/api/bonus-config/constants').json()
        body={'version':initial['version'],'parameters':{'vip_minimum':'100','renewal_rate':'6'}}
        saved=manager.put('/api/bonus-config/constants',json=body)
        assert saved.status_code==200,saved.text
        gear=manager.get('/api/sales-formulas/inputs',params=query).json()
        assert gear['period']['vip_minimum']=='100' and gear['period']['renewal_rate']=='6'
        assert gear['period_version']==saved.json()['version']
        assert manager.put('/api/bonus-config/constants',json=body).status_code==409
        restored=manager.put('/api/sales-formulas/parameters/S',json={**query,'version':gear['period_version'],'parameters':{'vip_minimum':'1680'}})
        assert restored.status_code==200,restored.text
        now=manager.get('/api/bonus-config/constants').json()
        assert now['parameters']['vip_minimum']=='1680' and now['parameters']['renewal_rate']=='6'
        for bad in [{'renewal_rate':101},{'vip_minimum':-1},{'target':100},{'renewal_rate':None},{'renewal_rate':True},{'expression':'1+1'}]:
            assert manager.put('/api/bonus-config/constants',json={'version':now['version'],'parameters':bad}).status_code==422
    with client_as('何卫','Test-only-password!') as bd:
        assert not bd.get('/api/bonus-config/constants').json()['can_edit']
        assert bd.put('/api/bonus-config/constants',json=body).status_code==403


@pytest.fixture
def v006_accounts(business_accounts,isolated_rule_settings):
    with client_as() as manager:
        cats=manager.get('/api/bd-categories').json()
        assert manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales','周政':'market'},'version':cats['version']}).status_code==200
    yield


def patch_xlsx(content,updates):
    import io,zipfile
    from xml.etree import ElementTree as ET
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as src,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            raw=src.read(name)
            if name in updates:
                root=ET.fromstring(raw)
                for ref,value in updates[name].items():
                    cell=root.find('.//{'+ns+'}c[@r="'+ref+'"]')
                    assert cell is not None
                    for child in list(cell):cell.remove(child)
                    if isinstance(value,str) and value.startswith('='):
                        cell.set('t','n');ET.SubElement(cell,'{'+ns+'}f').text=value[1:];ET.SubElement(cell,'{'+ns+'}v').text='1'
                    elif isinstance(value,(int,float)):
                        cell.set('t','n');ET.SubElement(cell,'{'+ns+'}v').text=str(value)
                    else:
                        cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,'{'+ns+'}is'),'{'+ns+'}t').text='' if value is None else value
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            dst.writestr(name,raw)
    return out.getvalue()


def export_one(client,kind='sales',owner='何卫'):
    from urllib.parse import unquote
    row=client.get('/api/commission-data',params={'category':kind,'owner':owner,'page_size':1}).json()['rows'][0]
    result=client.get('/api/bonus-export/'+kind,params={'owner':owner,'search':row['order_no']})
    assert result.status_code==200,result.text
    filename=unquote(result.headers['content-disposition'].split("filename*=UTF-8''")[1])
    return result,filename,row


def test_v006_protected_workbook_styles_validation_and_unique_versions(v006_accounts,monkeypatch):
    from backend import bonus_transfer
    import io,zipfile
    from xml.etree import ElementTree as ET
    monkeypatch.setattr(bonus_transfer,'export_second',lambda:'20261112-120000')
    with client_as() as manager:
        first,name,row=export_one(manager)
        assert name.endswith('_20261112-120000_v1.xlsx')
        with zipfile.ZipFile(io.BytesIO(first.content)) as book:
            ns={'m':bonus_transfer.MAIN}
            sheet=ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            assert sheet.find('m:sheetProtection',ns).get('sheet')=='1'
            assert sheet.find('m:sheetViews/m:sheetView/m:pane',ns).get('ySplit')=='1'
            for ref,style in [('A2','1'),('P2','1'),('S2','1'),('Q2','2'),('R2','2'),('Q1','3')]:
                assert sheet.find('.//m:c[@r="'+ref+'"]',ns).get('s')==style
            validation=sheet.find('m:dataValidations/m:dataValidation',ns)
            assert validation.get('type')=='list' and validation.get('allowBlank')=='0' and validation.get('errorStyle')=='stop'
            assert validation.find('m:formula1',ns).text=='"是,否,待确认"'
            styles=ET.fromstring(book.read('xl/styles.xml'))
            assert styles.find('m:fonts',ns)[1].find('m:color',ns).get('rgb')=='FF595959'
            assert styles.find('m:fills',ns)[0].find('m:patternFill',ns).get('patternType')=='none'
            assert styles.find('m:cellXfs',ns)[1].get('fillId')=='0'
            assert styles.find('m:cellXfs',ns)[3].get('fillId')=='0'
            xfs=styles.find('m:cellXfs',ns)
            assert xfs[1].find('m:protection',ns).get('locked')=='1' and xfs[2].find('m:protection',ns).get('locked')=='0'
            assert b'BDExport' in book.read('docProps/custom.xml')
        second,_,_=export_one(manager)
        assert second.headers['x-export-version']=='20261112-120000_v2'
        third,_,_=export_one(manager,kind='market',owner='周政')
        assert third.headers['x-export-version']=='20261112-120000_v3'
        meeting=manager.get('/api/bonus-export/meetings')
        assert 'x-export-version' not in meeting.headers
        assert manager.get('/api/bonus-import/latest').json()['suffix']=='20261112-120000_v3'
        monkeypatch.setattr(bonus_transfer,'export_second',lambda:'20261112-120001')
        next_second,_,_=export_one(manager)
        assert next_second.headers['x-export-version']=='20261112-120001_v1'


def test_v006_note_preloads_generated_text_and_preserves_other_confirmation_fields(v006_accounts):
    with client_as() as manager:
        row=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        assert row['note']  # Initial calculation/rule text is now the actual editable note.
        payload={'record_key':row['record_key'],'version':0,'note':'原有人工依据','is_paid':True,'is_refunded':False,'bonus_basis':'12.34','confirmed_rate':'0.05','bonus':'0.62'}
        assert manager.put('/api/commission-data/confirmation',json=payload).status_code==200
        row=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        before={key:row[key] for key in ['bonus_basis','confirmed_rate','bonus','is_paid','is_refunded']}
        assert '原有人工依据' in row['note']
        body={'record_key':row['record_key'],'version':row['version'],'note':'在原有内容上修改\n补充说明'}
        assert manager.put('/api/commission-data/note',json=body).status_code==200
        updated=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        assert updated['note']==body['note'] and {key:updated[key] for key in before}==before
        assert manager.put('/api/commission-data/note',json=body).status_code==409
        assert manager.put('/api/commission-data/note',json={**body,'version':updated['version'],'note':''}).status_code==200
        cleared=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        assert cleared['note']==''
        assert manager.put('/api/commission-data/note',json={**body,'version':cleared['version'],'is_paid':False}).status_code==422
        foreign=manager.get('/api/commission-data?category=market&owner=周政').json()['rows'][0]
    with client_as('何卫','Test-only-password!') as bd:
        own=bd.get('/api/commission-data?category=sales').json()['rows'][0]
        assert bd.put('/api/commission-data/note',json={'record_key':own['record_key'],'version':own['version'],'note':'本人备注'}).status_code==200
        assert bd.put('/api/commission-data/note',json={'record_key':foreign['record_key'],'version':foreign['version'],'note':'越权'}).status_code==409


@pytest.mark.parametrize('kind,owner',[('sales','何卫'),('market','周政')])
def test_v006_roundtrip_preview_commit_only_status_and_no_replay(v006_accounts,kind,owner):
    with client_as() as manager:
        exported,filename,original=export_one(manager,kind,owner)
        edited=patch_xlsx(exported.content,{'xl/worksheets/sheet1.xml':{'Q2':'是','R2':'否'}})
        url='/api/bonus-import/'+kind
        preview=manager.post(url+'/preview',params={'filename':filename},content=edited)
        assert preview.status_code==200,preview.text
        assert preview.json()['changed_count']==1
        before=manager.get('/api/commission-data',params={'category':kind,'owner':owner}).json()['rows'][0]
        assert before['is_paid'] is None and before['is_refunded'] is None
        result=manager.post(url,params={'filename':filename},content=edited)
        assert result.status_code==200,result.text
        after=manager.get('/api/commission-data',params={'category':kind,'owner':owner}).json()['rows'][0]
        assert after['is_paid'] is True and after['is_refunded'] is False
        for key in ['owner','order_amount','bonus_basis','confirmed_rate','bonus','note']:
            assert after[key]==before[key]
        assert manager.post(url,params={'filename':filename},content=edited).status_code==409
        assert manager.get('/api/bonus-import/latest').json()['consumed'] is True


def test_v006_rejects_old_renamed_foreign_and_other_kind_files(v006_accounts):
    with client_as() as manager:
        old,old_name,row=export_one(manager)
        newest,new_name,_=export_one(manager)
        assert manager.post('/api/bonus-import/sales/preview',params={'filename':old_name},content=old.content).status_code==409
        assert manager.post('/api/bonus-import/sales/preview',params={'filename':new_name},content=old.content).status_code==409
        assert manager.post('/api/bonus-import/market/preview',params={'filename':new_name},content=newest.content).status_code==409
        # Exporting meetings must leave the latest protected version intact.
        manager.get('/api/bonus-export/meetings')
        assert manager.post('/api/bonus-import/sales/preview',params={'filename':new_name},content=newest.content).status_code==200
    with client_as('何卫','Test-only-password!') as bd:
        assert bd.post('/api/bonus-import/sales/preview',params={'filename':new_name},content=newest.content).status_code==409
        own,own_name,_=export_one(bd)
        assert bd.post('/api/bonus-import/sales/preview',params={'filename':own_name},content=newest.content).status_code==409
        edited=patch_xlsx(own.content,{'xl/worksheets/sheet1.xml':{'Q2':'是','R2':'待确认'}})
        result=bd.post('/api/bonus-import/sales',params={'filename':own_name},content=edited)
        assert result.status_code==200,result.text
        assert {r['owner'] for r in bd.get('/api/commission-data?category=sales').json()['rows']}=={'何卫'}


@pytest.mark.parametrize('updates',[
    {'A2':'2027Q1'},{'P2':99999},{'S2':'私改备注'},{'Q2':'已发放'},{'Q2':''},{'R2':1},{'Q2':'=1+1'},
])
def test_v006_rejects_locked_cells_invalid_flags_and_formulas(v006_accounts,updates):
    with client_as() as manager:
        exported,filename,row=export_one(manager)
        edited=patch_xlsx(exported.content,{'xl/worksheets/sheet1.xml':updates})
        result=manager.post('/api/bonus-import/sales',params={'filename':filename},content=edited)
        assert result.status_code==422,result.text
        assert manager.get('/api/bonus-import/latest').json()['consumed'] is False
        after=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        assert after['version']==0 and after['is_paid'] is None


def test_v006_atomic_validation_and_changes_after_export_require_new_file(v006_accounts):
    with client_as() as manager:
        result=manager.get('/api/bonus-export/sales?owner=何卫')
        from urllib.parse import unquote
        filename=unquote(result.headers['content-disposition'].split("filename*=UTF-8''")[1])
        edited=patch_xlsx(result.content,{'xl/worksheets/sheet1.xml':{'Q2':'是','R2':'否','Q3':'是','R3':'未知'}})
        assert manager.post('/api/bonus-import/sales',params={'filename':filename},content=edited).status_code==422
        before=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows']
        assert before[0]['version']==before[1]['version']==0
        valid=patch_xlsx(result.content,{'xl/worksheets/sheet1.xml':{'Q2':'是','R2':'否','Q3':'是','R3':'否'}})
        assert manager.post('/api/bonus-import/sales/preview',params={'filename':filename},content=valid).status_code==200
        assert manager.put('/api/commission-data/note',json={'record_key':before[1]['record_key'],'version':0,'note':'导出后另一位同事更新'}).status_code==200
        assert manager.post('/api/bonus-import/sales',params={'filename':filename},content=valid).status_code==409
        after=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows']
        assert after[0]['version']==0 and after[0]['is_paid'] is None and after[1]['is_paid'] is None
        assert manager.get('/api/bonus-import/latest').json()['consumed'] is False



def test_v006_concurrent_exports_allocate_unique_same_second_versions(v006_accounts,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend import bonus_transfer
    monkeypatch.setattr(bonus_transfer,'export_second',lambda:'20261112-180000')
    with client_as() as manager:
        row=manager.get('/api/commission-data?category=sales&owner=何卫').json()['rows'][0]
        def export(_):
            return manager.get('/api/bonus-export/sales',params={'owner':'何卫','search':row['order_no']})
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(export,range(3)))
        assert all(r.status_code==200 for r in responses),[(r.status_code,r.text[:200] if r.status_code!=200 else '') for r in responses]
        assert {r.headers['x-export-version'] for r in responses}=={'20261112-180000_v1','20261112-180000_v2','20261112-180000_v3'}
        assert manager.get('/api/bonus-import/latest').json()['suffix']=='20261112-180000_v3'


def test_v006_rejects_stale_calculations_and_unsafe_archives(v006_accounts):
    from backend.app import SystemSetting
    from backend.bonus_rules import GLOBAL_KEY
    import io,zipfile
    with client_as() as manager:
        exported,filename,row=export_one(manager)
        bad=manager.post('/api/bonus-import/sales/preview',params={'filename':filename},content=b'not a workbook')
        assert bad.status_code==422
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:z.writestr('../evil.xml','x')
        assert manager.post('/api/bonus-import/sales/preview',params={'filename':filename},content=archive.getvalue()).status_code==422
        # Changing an input used by an exported row invalidates that snapshot even if confirmation version is unchanged.
        with Session(engine) as db:
            key='commission_service_'+__import__('hashlib').sha256(row['service'].encode()).hexdigest()[:40]
            db.add(SystemSetting(key=key,value=json.dumps({'enabled':True,'note':'导出后变更服务规则'}),version=1))
            db.commit()
        edited=patch_xlsx(exported.content,{'xl/worksheets/sheet1.xml':{'Q2':'是','R2':'否'}})
        result=manager.post('/api/bonus-import/sales',params={'filename':filename},content=edited)
        assert result.status_code==409,result.text
        assert manager.get('/api/bonus-import/latest').json()['consumed'] is False



def test_missing_plan_and_missing_service_have_distinct_actionable_diagnostics(business_accounts,v005_sources):
    with client_as() as manager:
        cats=manager.get('/api/bd-categories').json()
        manager.put('/api/bd-categories',json={'mapping':{**cats['mapping'],'何卫':'sales','周政':'market'},'version':cats['version']})
        config=manager.get('/api/bonus-config/plans').json()
        assert config['year']==2025 and 2026 in config['missing_years']
        for kind,name in [('sales','何卫'),('market','周政')]:
            rows=manager.get('/api/commission-data',params={'category':kind,'owner':name,'search':'收费系统户数'}).json()['rows']
            assert rows and all(r['enabled'] is None and r['rule_issue']=='missing_year_plan' and '2026' in r['rule_note'] for r in rows)
        assert manager.post('/api/bonus-config/plans/2026/inherit',json={'version':0}).status_code==200
        assert 2026 not in manager.get('/api/bonus-config/plans').json()['missing_years']
        report=manager.get('/api/bonus-config/plans?year=2026').json()
        assert all(item['service']!='收费系统户数' for item in report['missing_services'])
        for kind,name in [('sales','何卫'),('market','周政')]:
            rows=manager.get('/api/commission-data',params={'category':kind,'owner':name,'search':'收费系统户数'}).json()['rows']
            assert rows and all(r['enabled'] is True and r['rule_issue']=='' for r in rows)
        from backend.bonus_config import all_settings
        from backend.bonus_rules import shared_service_rule
        with Session(engine) as db:
            settings=all_settings(db)
            missing=shared_service_rule(settings,'真正新增未维护服务',year=2026)
            assert missing['enabled'] is None and missing['issue']=='missing_service' and '2026' in missing['note']
            assert shared_service_rule(settings,'收费系统户数',year=None)['issue']=='invalid_payment_year'
