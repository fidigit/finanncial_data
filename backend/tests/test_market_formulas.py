from datetime import datetime
from decimal import Decimal

from backend.market_formulas import calculate_market, market_basis
from backend.bonus_config import MARKET_DEFAULTS


RATES = {name: Decimal(value) / 100 for name, value in MARKET_DEFAULTS.items()}


def order(row_id, basis, *, purchase='续费', channel='直接营收', referral=False, enabled=True):
    return (datetime(2026, 11, 1, row_id), {
        'row_id': row_id, 'purchase_type': purchase, 'bonus_basis': str(basis),
        'enabled': enabled, 'calculation': {'channel': channel, 'referral': referral, 'problems': []},
    })


def test_direct_renewal_crosses_threshold_and_keeps_high_rate():
    initial = order(1, 60, purchase='首购')
    excluded = order(2, 200, enabled=False)
    crossing = order(3, 80)
    adjustment = order(4, -60)
    last = order(5, 5)
    calculate_market([last, crossing, adjustment, initial, excluded], Decimal(100), RATES)
    assert initial[1]['bonus'] == '6.00'
    assert excluded[1]['revenue_total'] == '60'
    assert excluded[1]['bonus'] == '0.00'
    assert crossing[1]['rate_display'] == '3% / 5%'
    assert crossing[1]['bonus'] == '3.20'
    assert crossing[1]['calculation']['inside_basis'] == '40'
    assert crossing[1]['calculation']['excess_basis'] == '40'
    assert last[1]['revenue_total'] == '85'
    assert last[1]['rate_display'] == '5%'
    assert last[1]['bonus'] == '0.25'


def test_market_first_purchase_and_pending_rules():
    referral = order(1, 50, purchase='首购', referral=True)
    indirect = order(2, 100, purchase='首购', channel='间接营收')
    referral_indirect = order(3, 100, purchase='首购', channel='间接营收', referral=True)
    renewal_indirect = order(4, 100, channel='间接营收')
    renewal = order(5, 50)
    calculate_market([referral, indirect, referral_indirect, renewal_indirect, renewal], None, RATES)
    assert referral[1]['bonus'] == '2.50'
    assert indirect[1]['bonus'] == '2.00'
    assert indirect[1]['revenue_total'] == '50'
    assert referral_indirect[1]['bonus'] is None
    assert renewal_indirect[1]['bonus'] is None
    assert renewal[1]['revenue_total'] == '100'
    assert renewal[1]['bonus'] is None


def test_exact_threshold_upgrades_the_following_order():
    exact = order(1, 100)
    following = order(2, 100)
    calculate_market([following, exact], Decimal(100), RATES)
    assert exact[1]['bonus'] == '3.00'
    assert following[1]['bonus'] == '5.00'


def test_mysql_share_is_the_basis_without_rounding_ratio_or_double_splitting():
    ratio, basis = market_basis({'_source_id': '1', '订单金额': '300', '_share_amount': '100'})
    assert ratio == Decimal(1) / 3
    assert basis == Decimal('100.00')
    assert market_basis({'订单金额': '300'}) == (None, None)
    assert market_basis({'_source_id': '1', '订单金额': '300', '_share_amount': '301'}) == (None, None)


def test_market_api_saves_quarter_threshold_and_exports_same_calculation(tmp_path, monkeypatch):
    import csv
    import json
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.app import Base, SystemSetting, admin, app, current_user, database
    from backend.bonus_rules import TARGETS_KEY, year_plan_key
    from backend.bonus_transfer import read_workbook

    source = tmp_path / 'orders.csv'
    orders = [
        {'订单号': 'order-1', '付费时间': '2026-11-01', '订单金额': '60', '首购/续费': '首购'},
        {'订单号': 'order-2', '付费时间': '2026-11-02', '订单金额': '80', '首购/续费': '续费'},
    ]
    with source.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[*orders[0], '_source_id', '_share_amount', 'BD姓名', '季度', '付费项目', '直接/间接收入'])
        writer.writeheader()
        for number, row in enumerate(orders, 1):
            writer.writerow({**row, '_source_id': str(number), '_share_amount': row['订单金额'],
                             'BD姓名': '市场甲', '季度': '2026Q4', '付费项目': '测试服务', '直接/间接收入': '直接收入'})
    monkeypatch.setenv('REFERENCE_CSV_PATH', str(source))
    db_engine = create_engine('sqlite:///' + (tmp_path / 'market.db').as_posix())
    Base.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        for key, value in {
            'bd_categories': {'市场甲': 'market'},
            TARGETS_KEY: {'rows': [{'BD姓名': '市场甲', '季度': '2026Q4', '直接营收目标': '500', '市场二段提成门槛': '40'}]},
            year_plan_key(2026): {'rows': [{'所购服务': '测试服务', '是否计入提成范围': '是'}]},
        }.items():
            db.add(SystemSetting(key=key, value=json.dumps(value), version=1))
        db.commit()

    def test_db():
        with Session(db_engine) as db:
            yield db

    user = SimpleNamespace(id=1, name='管理员', username='admin', role='admin')
    monkeypatch.setitem(app.dependency_overrides, database, test_db)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: user)
    monkeypatch.setitem(app.dependency_overrides, admin, lambda: user)
    client = TestClient(app, headers={'X-Requested-With': 'BD-Workbench'})
    endpoint = '/api/bonus-config/targets/2026Q4'
    query = {'category': 'market', 'search': 'order-2'}
    before = client.get('/api/commission-data', params=query).json()['rows'][0]
    assert (before['calculation']['target'], before['rate_display']) == ('500', '3%')
    saved = client.put(endpoint, json={'version': 1, 'rows': [{'owner': '市场甲', 'target': '100'}]})
    assert saved.status_code == 200
    assert saved.json()['rows'][0] == {'BD姓名': '市场甲', '季度': '2026Q4', '直接营收目标': '100'}
    result = client.get('/api/commission-data', params=query).json()
    row = result['rows'][0]
    assert (row['revenue_total'], row['rate_display'], row['bonus']) == ('140.00', '3% / 5%', '3.20')
    response = client.get('/api/bonus-export/market', params={'search': 'order-2'})
    assert response.status_code == 200
    sheets, _ = read_workbook(response.content)
    assert sheets[0]['name'] == '奖金汇总表'
    exported = sheets[1]['matrix'][1]
    assert exported[14] == row['rate_display']
    assert exported[15] == Decimal(row['bonus'])
    rates_path = '/api/bonus-config/market-rates'
    rates = client.get(rates_path).json()
    saved_rates = client.put(rates_path, json={'version': rates['version'], **rates['parameters'], 'renewal_high': '7'})
    assert saved_rates.status_code == 200
    after = client.get('/api/commission-data', params={'category': 'market', 'search': 'order-2'}).json()['rows'][0]
    assert (after['rate_display'], after['bonus']) == ('3% / 7%', '4.00')
    db_engine.dispose()
