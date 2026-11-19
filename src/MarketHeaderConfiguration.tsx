import { useEffect, useState } from 'react';
import { Alert, Button, InputNumber, Popover, Spin, Tag } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { api } from './api';

const formulas: Record<string, string[]> = {
  '是否计发提成': ['团队 VIP：订单金额达到团队 VIP 订单收款金额下限，计提。', '其他服务：按付款年份和所购服务匹配奖金方案。单笔人工确认优先。'],
  '分摊比例': ['MySQL 个人分摊金额 ÷ 订单金额。', '共享订单按订单号和所购服务识别，同一订单可以有多位 BD。'],
  '奖金计算基数': ['订单金额 × 完整分摊比例，四舍五入到分。MySQL 已给出个人分摊金额时直接取该金额。'],
  '累计营收': ['按市场 BD 和季度、付款时间排序，累计确认计提的直接营收基数，包含首购和续费。', '累计以整个季度为准，搜索和分页只影响展示。'],
  '适用提点（分段提点）': [
    '直接首购：按协会／合伙人转介绍选提点。间接首购无转介绍时使用间接首购提点。',
    '直接续费：使用销售与市场共用的奖金汇总表，取本 BD、本季度的直接营收目标作为二段门槛。跨线订单按门槛前后分别计提，达标后的直接续费保持高档。',
    '间接首购有转介绍、间接续费及缺失配置的订单显示待确认。奖金按各段基数 × 对应提点求和。',
  ],
};
const rateFields = [
  ['direct_referral', '直接首购 · 有转介绍'],
  ['direct_no_referral', '直接首购 · 无转介绍'],
  ['indirect_first', '间接首购 · 无转介绍'],
  ['renewal_low', '直接续费 · 门槛内'],
  ['renewal_high', '直接续费 · 达标后'],
];
type Parameters = { parameters: Record<string, string>; version: number; can_edit: boolean };
type MarketTrace = {
  owner: string; quarter: string; rate_display?: string;
  calculation?: { channel?: string; referral?: boolean; target?: string | null; before?: string;
    crossing?: boolean; inside_basis?: string; excess_basis?: string; problems: string[] };
};

export function MarketHeaderConfiguration({ title, example, onSaved }: {
  title: string; example?: MarketTrace; onSaved: () => void;
}) {
  const [panel, setPanel] = useState<'formula' | 'parameters'>();
  const [data, setData] = useState<Parameters>();
  const [draft, setDraft] = useState<Record<string, number | null>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const vip = title === '是否计发提成';
  const fields = vip ? [['vip_minimum', '团队 VIP 订单收款金额下限']] : title === '适用提点（分段提点）' ? rateFields : [];
  const path = vip ? '/bonus-config/constants' : '/bonus-config/market-rates';
  const hasFields = fields.length > 0;
  useEffect(() => {
    const changed = () => setRevision(value => value + 1);
    window.addEventListener('bonus-rules-changed', changed);
    return () => window.removeEventListener('bonus-rules-changed', changed);
  }, []);
  useEffect(() => {
    if (!panel || !hasFields) return;
    let active = true;
    setLoading(true); setError(''); setData(undefined);
    api<Parameters>(path).then(result => {
      if (!active) return;
      setData(result);
      setDraft(Object.fromEntries(Object.entries(result.parameters).map(([key, value]) => [key, Number(value)])));
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [panel, hasFields, path, revision]);

  async function save() {
    if (!data?.can_edit || busy || loading || fields.some(([key]) => draft[key] == null)) return;
    const parameters = Object.fromEntries(fields.map(([key]) => [key, draft[key]]));
    setBusy(true); setError('');
    try {
      await api(path, { method: 'PUT', body: JSON.stringify(vip ? { version: data.version, parameters } : { version: data.version, ...parameters }) });
      setPanel(undefined);
      onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const trace = example?.calculation;
  function changePanel(kind: 'formula' | 'parameters', open: boolean) {
    if (!busy) setPanel(current => open ? kind : current === kind ? undefined : current);
  }
  return <div className="formula-column-title"><span>{title}</span><div className="sales-header-gears">
    {hasFields && <Popover trigger="click" placement="bottomRight" autoAdjustOverflow={false} arrow={false}
      open={panel === 'parameters'} onOpenChange={open => changePanel('parameters', open)}
      classNames={{ root: 'sales-parameter-popover' }} styles={{ container: { padding: 0 } }}
      content={<div className="sales-parameter-viewport">
        <div className="sales-parameter-scope">{vip ? '销售和市场共用' : '市场全部 BD · 全部季度'}</div>
        {error && <div className="sales-parameter-error">{error}</div>}
        <Spin spinning={loading}>
          {fields.map(([key, label]) => <label key={key} style={{ display: 'block', marginBottom: 8 }}>{label}
            <InputNumber aria-label={label} style={{ width: '100%' }} value={draft[key]} min={0}
              max={vip ? 1000000000000 : 100} precision={vip ? 2 : 4} addonAfter={vip ? '元' : '%'}
              disabled={!data?.can_edit || busy} onChange={value => setDraft(previous => ({ ...previous, [key]: value }))}
              onPressEnter={save} />
          </label>)}
          {data?.can_edit && <Button size="small" type="primary" loading={busy} disabled={fields.some(([key]) => draft[key] == null)} onClick={save}>保存参数</Button>}
        </Spin>
      </div>}>
      <button type="button" className="sales-parameter-gear" aria-label={title + '参数配置'}><SettingOutlined /></button>
    </Popover>}
    <Popover trigger="click" placement="bottomRight" autoAdjustOverflow={false} arrow={false}
      open={panel === 'formula'} onOpenChange={open => changePanel('formula', open)}
      classNames={{ root: 'sales-formula-popover' }} styles={{ container: { padding: 0 } }}
      content={<div className="sales-formula-viewport">
        <div className="sales-rule-heading"><strong>{title} · 市场计算规则</strong><Tag color="blue">固定公式</Tag></div>
        {formulas[title].map(line => <p key={line}>{line}</p>)}
        {error && <Alert type="error" title={error} />}
        {hasFields && <Spin spinning={loading}>{data && fields.map(([key, label]) => <p key={key}>{label} · {data.parameters[key]}{vip ? ' 元' : '%'}</p>)}</Spin>}
        {title === '适用提点（分段提点）' && example && trace && <>
          <p><strong>计算样例 · {example.owner} · {example.quarter}</strong></p>
          <p>营收分类 · {trace.channel}　协会／合伙人转介绍 · {trace.referral ? '是' : '否'}</p>
          <p>本单前累计 · {trace.before ?? '待确认'}　直接营收目标 · {trace.target ?? '待配置'}</p>
          {trace.crossing && <p>门槛内基数 · {trace.inside_basis}　达标后基数 · {trace.excess_basis}</p>}
          <p>结果 · {example.rate_display}{trace.problems.length ? ' · ' + trace.problems.join('、') : ''}</p>
        </>}
      </div>}>
      <button type="button" className="sales-blue-gear" aria-label={title + '公式'}><SettingOutlined /></button>
    </Popover>
  </div></div>;
}
