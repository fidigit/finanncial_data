import os
import tempfile
import csv
from pathlib import Path
import pytest
from contextlib import contextmanager

# Isolate all persistent effects from developer or production data.
temporary = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(temporary.name) / 'test.db').as_posix()
os.environ['DEMO_MODE'] = 'true'
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
        row = snapshot['rows'][0]
        assert row['service'] in snapshot['pending_services']
        assert client.put('/api/commission-data/service-rule', json={'service': row['service'], 'enabled': True, 'note': '已确认该服务计发'}).status_code == 200
        updated = client.get('/api/commission-data').json()
        assert row['service'] not in updated['pending_services']
        assert updated['rows'][0]['enabled'] is True
        payload = {'record_key': row['record_key'], 'version': 0, 'enabled': False, 'shared_bd': '测试合作BD', 'allocation_ratio': '0.5', 'bonus_basis': '12.34', 'market_bd': '测试市场BD', 'confirmed_rate': '0.03', 'bonus': '0.37', 'is_paid': False, 'is_refunded': None, 'note': '本单人工确认测试'}
        assert client.put('/api/commission-data/confirmation', json=payload).status_code == 200
        confirmed = client.get('/api/commission-data').json()['rows'][0]
        assert confirmed['enabled'] is False and confirmed['note'] == payload['note']
        assert confirmed['bonus_basis'] == '12.34' and confirmed['bonus'] == '0.37'
        assert confirmed['is_paid'] is False and confirmed['is_refunded'] is None
        assert client.put('/api/commission-data/confirmation', json=payload).status_code == 409
        assert client.put('/api/commission-data/confirmation', json={**payload, 'version': 1, 'allocation_ratio': '1.1'}).status_code == 422
        assert client.put('/api/commission-data/service-rule', json={'service': '不存在的服务', 'enabled': True, 'note': '测试'}).status_code == 422
