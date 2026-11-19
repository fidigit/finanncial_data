import json
from decimal import Decimal
from types import SimpleNamespace

from backend.app import app  # Register the models before importing bonus modules.
from backend.bonus_rules import TARGETS_KEY
from backend.bonus_summary import ADJUSTMENTS_KEY, build_summary


def test_quarter_summary_counts_direct_market_revenue_and_applies_role_specific_meeting_rules():
    sales, market = '销售甲', '市场乙'
    values = {
        'bd_categories': {sales: 'sales', market: 'market'},
        TARGETS_KEY: {'rows': [
            {'BD姓名': sales, '季度': '2026Q3', '直接营收目标': '30000'},
            {'BD姓名': market, '季度': '2026Q3', '直接营收目标': '1500'},
        ]},
        ADJUSTMENTS_KEY: {'rows': [
            {'owner': sales, 'quarter': '2026Q3', 'daily': '-10.01', 'correction': '-4.339'},
        ]},
    }
    settings = {key: SimpleNamespace(value=json.dumps(value)) for key, value in values.items()}
    data = {
        'sales': [{'owner': sales, 'quarter': '2026Q3', 'bonus_basis': '30000', 'bonus': '3000'}],
        'market': [
            {'owner': market, 'quarter': '2026Q3', 'bonus_basis': '900', 'bonus': '90',
             'calculation': {'channel': '直接营收'}},
            {'owner': market, 'quarter': '2026Q3', 'bonus_basis': '400', 'bonus': '8',
             'calculation': {'channel': '间接营收'}},
        ],
        'meetings': [
            {'owner': sales, 'meeting_date': '2026-07-01', 'qualified': True, 'meeting_type': '参会会议'},
            *[{'owner': market, 'meeting_date': f'2026-07-0{d}', 'qualified': True, 'meeting_type': '专场会议'}
              for d in (1, 2, 3)],
            {'owner': market, 'meeting_date': '2026-10-01', 'qualified': True, 'meeting_type': '专场会议'},
        ],
    }
    summary = build_summary(data, settings, [])
    assert [row[0] for row in summary if row[0].startswith('统计周期：')] == ['统计周期：2026Q4', '统计周期：2026Q3']
    sales_q3 = next(row for row in summary if row[1] == sales)
    assert sales_q3[11] == 500
    assert sales_q3[14] == Decimal('3485.65')
    markets = [row for row in summary if row[1] == market]
    assert markets[0][11] == 0 and markets[1][11] == 3000
    assert markets[1][4] == Decimal('900') and markets[1][6] == Decimal('98')
    q3_team = summary[-1]
    assert q3_team[5] == Decimal('30900') / Decimal('31500')
    assert q3_team[14] == Decimal('6583.65')
