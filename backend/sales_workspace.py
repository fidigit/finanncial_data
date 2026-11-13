"""Sales source previews. Historical workbook samples never overwrite live orders."""
import json
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from backend.bonus_rules import PLAN_KEY, TARGETS_KEY, GLOBAL_KEY, setting_payload, shared_service_rule, YEAR_PLAN_PREFIX
from backend.app import app, current_user, database, ROOT, commission_snapshot, SystemSetting

SOURCE_TITLES = {
    'splits': '拆分订单表', 'targets': '奖金汇总表（姓名、季度目标）',
    'services': '奖金方案', 'orders': 'C 订单号',
    'segmentation': 'Z 是否适用分段计算', 'constants': '公共常数：门槛、各档提点',
}
CONSTANTS = [
    ('团队VIP金额下限', '1680元', '⑧ 是否计发提成', 'R → S'),
    ('同BD奖金计算基数合计门槛', '30000元', '⑮ 适用提点', 'X / 汇总G'),
    ('续费提点', '3%', '⑮ 适用提点', 'X → Y / AA'),
    ('自拓目标内提点', '10%', '⑮ 适用提点', 'X / AA'),
    ('自拓超额提点', '15%', '⑮ 适用提点', 'X / AA'),
    ('市场推荐目标内提点', '8%', '⑮ 适用提点', 'X / AA'),
    ('市场推荐超额提点', '13%', '⑮ 适用提点', 'X / AA'),
    ('协会/合伙人目标内提点', '5%', '⑮ 适用提点', 'X / AA'),
    ('协会/合伙人超额提点', '8%', '⑮ 适用提点', 'X / AA'),
]

@app.get('/api/sales-workspace/sources/{kind}')
def source_preview(kind: str, user=Depends(current_user), db: Session = Depends(database)):
    if kind not in SOURCE_TITLES:
        raise HTTPException(404, '输入源头不存在')
    settings = {s.key:s for s in db.scalars(select(SystemSetting))}
    active = kind == 'constants' or (PLAN_KEY if kind == 'services' else TARGETS_KEY if kind == 'targets' else '') in settings
    if kind == 'constants':
        from backend.sales_formulas import global_parameters
        params = global_parameters(settings)
        keys = ['vip_minimum','threshold','renewal_rate','self_rate','self_excess','market_rate','market_excess','partner_rate','partner_excess']
        columns = ['参数', '当前生效值', '配置入口', '引用节点']
        data = {'sheet': '销售原表公式中的固定值', 'columns': columns,
                'rows': [dict(zip(columns, (row[0], str(params[key]) + ('元' if key in ('vip_minimum','threshold') else '%'), row[2], row[3]))) for key,row in zip(keys,CONSTANTS)]}
    else:
        path = ROOT / 'data' / 'sales-source-samples.json'
        samples = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        data = setting_payload(settings, PLAN_KEY if kind == 'services' else TARGETS_KEY if kind == 'targets' else '', samples.get(kind, {'sheet': SOURCE_TITLES[kind], 'columns': [], 'rows': []}))
        annual = kind == 'services' and any(k.startswith(YEAR_PLAN_PREFIX) for k in settings)
        if annual:
            from backend.bonus_config import get_plans
            plan = get_plans(None, user, db)
            data = {'sheet':f'{plan["year"]}年奖金方案','columns':['所购服务','是否计入提成范围'],'rows':plan['rows']}
        if kind == 'services' and active and not annual:
            data = {**data, 'rows': [{**r, '是否计入提成范围': '是' if shared_service_rule(settings, r['所购服务']).get('enabled') is True else '否' if shared_service_rule(settings, r['所购服务']).get('enabled') is False else '按全局VIP金额下限判断'} for r in data['rows']]}
        if user.role not in ('admin', 'superadmin'):
            scoped = commission_snapshot(db, user, category='sales', page_size=1000000)
            names = {r['values'].get('BD姓名', '').strip() for r in scoped['rows']}
            data = {**data, 'rows': [r for r in data['rows'] if 'BD姓名' not in r or r['BD姓名'] in names]}
    return {**data, 'kind': kind, 'title': SOURCE_TITLES[kind], 'read_only': True,
            'sample': not active, 'active': active, 'note': ('已接入实际计算：按订单付款年份读取对应年度方案，适用于全部BD；团队VIP按全局金额下限判断，单笔人工确认优先。' if kind == 'services' else '已接入实际计算：直接营收目标按BD姓名及季度严格匹配；不把历史季度目标套用于其他季度，已配置目标优先。' if kind == 'targets' else '当前全局生效参数，适用全部BD和全部季度；可通过表头齿轮设置。') if active else '原表历史样例预览；不覆盖当前订单。手动维护入口将在后续开放。'}
