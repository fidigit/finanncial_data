import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Empty, Form, Input, Modal, Select, Space, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { api, money } from './api';
import { SalesSourceEntries, SalesHeaderConfiguration } from './SalesConfiguration';
import BonusImport from './BonusImport';
import BonusTableView, { downloadBonus } from './BonusTableView';

type RecordRow = {
  market_recommended?: boolean | null; rate_display?: string; calculation?: { problems: string[]; overrides: string[] };
  row_id: number; record_key: string; order_no: string; quarter: string; owner: string; company: string;
  paid_date: string; service: string; purchase_type: string; order_amount: string; enabled: boolean | null;
  rule_note: string; rule_issue?: string; shared_bd: string; allocation_ratio: string | null; bonus_basis: string | null;
  market_bd: string; market_pending: boolean; referral: string; revenue_total: string | null;
  confirmed_rate: string | null; bonus: string | null; is_paid: boolean | null; is_refunded: boolean | null;
  note: string; source_bonus: string; version: number; confirmation: Record<string, unknown>;
};
type Snapshot = { rows: RecordRow[]; total: number; options: { quarters: string[]; owners: string[]; projects: string[] }; pending_services: string[]; can_edit: boolean; can_edit_note: boolean; rules: Record<string, { enabled: boolean; note: string }> };
const flag = (value: boolean | null, pending = '待确认') => value === null ? <Tag color="warning">{pending}</Tag> : <Tag color={value ? 'success' : 'default'}>{value ? '是' : '否'}</Tag>;
const amount = (value: string | null) => value === null ? <span className="subtext">待确认</span> : money(value);
const optionalText = (value: string) => value || <span className="reference-empty">—</span>;

export default function CommissionDataTable({ category }: { category: 'sales' | 'market' }) {
  const { message } = App.useApp();
  const [data, setData] = useState<Snapshot | null>(null);
  const [query, setQuery] = useState({ page: 1, page_size: 20, search: '', quarter: '', owner: '' });
  const [search, setSearch] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [record, setRecord] = useState<RecordRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [rowForm] = Form.useForm();
  const sequence = useRef(0);
  useEffect(() => { const changed=()=>setRefresh(v=>v+1); window.addEventListener('bonus-rules-changed',changed); return ()=>window.removeEventListener('bonus-rules-changed',changed); }, []);
  const rulesSaved=()=>window.dispatchEvent(new Event('bonus-rules-changed'));
  useEffect(() => {
    const current = ++sequence.current;
    setLoading(true); setError('');
    api<Snapshot>('/commission-data?' + new URLSearchParams(Object.entries({ ...query, category }).map(([k, v]) => [k, String(v)]))).then(result => {
      if (current === sequence.current) setData(result);
    }).catch(e => { if (current === sequence.current) { setData(null); setError(e.message); } }).finally(() => { if (current === sequence.current) setLoading(false); });
    return () => { sequence.current++; };
  }, [query, refresh, category]);
  function edit(row: RecordRow) {
    rowForm.resetFields();
    rowForm.setFieldsValue({ note: row.note || '' });
    setRecord(row);
  }
  const textColumn = (title: string, field: keyof RecordRow, width = 120) => ({ title, dataIndex: field, key: field, width, ellipsis: true, render: (value: string) => <Tooltip title={value}>{optionalText(value)}</Tooltip> });
  const columns: ColumnsType<RecordRow> = [
    { title: '订单信息', children: [
      { ...textColumn('季度', 'quarter', 100), fixed: 'start' }, { ...textColumn('BD姓名', 'owner', 110), fixed: 'start' },
      textColumn('付款公司', 'company', 280), textColumn('付款时间', 'paid_date', 160), textColumn('所购服务', 'service', 200), textColumn('首购/续费', 'purchase_type', 105),
      { title: '订单金额', dataIndex: 'order_amount', width: 130, align: 'right', render: value => value ? money(value) : '—' },
      { title: '是否计发提成', width: 155, render: (_, r) => <Tooltip title={r.rule_note || r.note || '请先设置该服务是否计发提成'}>{flag(r.enabled, r.rule_issue==='missing_year_plan'?'缺年度方案':r.rule_issue==='invalid_payment_year'?'付款时间异常':'待设置规则')}</Tooltip> },
    ] },
    { title: '确认基数', children: [textColumn('共享订单', 'shared_bd', 160), { title: '分摊比例', dataIndex: 'allocation_ratio', width: 125, align: 'right', render: value => value === null ? '待确认' : `${Number(value) * 100}%` }, { title: '奖金计算基数', dataIndex: 'bonus_basis', width: 150, align: 'right', render: amount }] },
    { title: '确认提点（结合首购/续费）', children: [
      { title: '市场渠道', width: 165, render: (_, r) => category === 'sales' ? flag(r.market_recommended ?? null) : r.market_bd || (r.market_pending ? <Tag color="warning">待补市场BD姓名</Tag> : '—') },
      textColumn('转介绍', 'referral', 170),
      { title: '累计营收', width: 150, render: (_, r) => category === 'sales' ? amount(r.revenue_total) : <Tooltip title="累计周期、计提范围、重复订单与退款口径确认后计算"><span className="subtext">待确认累计口径</span></Tooltip> },
      { title: '适用提点（分段提点）', width: 185, render: (_, r) => category === 'sales' ? <span>{r.rate_display || '待配置'}</span> : r.confirmed_rate === null ? <span className="subtext">待确认分段提点</span> : <Tooltip title="人工确认提点，尚未执行分段规则引擎">{Number(r.confirmed_rate) * 100}%</Tooltip> },
    ] },
    { title: '奖金', width: 150, align: 'right', render: (_, r) => category === 'sales' ? <Tooltip title={r.calculation?.problems.join('；') || '公式结果；人工覆盖会另行标注'}><div>{amount(r.bonus)}{!!r.calculation?.overrides.includes('奖金') && <Tag color="blue">人工</Tag>}</div></Tooltip> : <Tooltip title={`来源奖金：${r.source_bonus || '空'}；本列为人工确认奖金，未自动计发`}>{amount(r.bonus)}</Tooltip> },
    { title: '是否发放', dataIndex: 'is_paid', width: 110, render: value => flag(value) },
    { title: '是否退款', dataIndex: 'is_refunded', width: 110, render: value => flag(value) },
    { title: '备注', width: 260, render: (_, r) => <div><div style={{ whiteSpace: 'pre-wrap' }}>{r.note || <span className="subtext">暂无备注</span>}</div>{data?.can_edit_note && <Button type="link" size="small" onClick={() => edit(r)}>确认 / 修改</Button>}</div> },
  ];
  function decorated(items: ColumnsType<RecordRow>): ColumnsType<RecordRow> {
    return items.map(column => {
      if ('children' in column) return { ...column, children: decorated(column.children) };
      if (category !== 'sales' || !['是否计发提成', '分摊比例', '奖金计算基数', '累计营收', '适用提点（分段提点）'].includes(String(column.title))) return column;
      return { ...column, key: String(column.title), title: <SalesHeaderConfiguration title={String(column.title)} context={data?.rows[0]} onSaved={rulesSaved} /> };
    });
  }
  return <Card className="reference-data-card commission-data-card" title={category === 'sales' ? '销售奖金表' : '市场奖金表'} extra={<Space><Button loading={exporting} onClick={async () => { setExporting(true); try { await downloadBonus(category, query); } catch(e) { message.error((e as Error).message); } finally { setExporting(false); } }}>导出 XLSX</Button><BonusImport kind={category}/>{category === 'market' && <SalesSourceEntries onlyServices />}<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRefresh(v => v + 1)}>刷新明细</Button></Space>}>
    {error && <Alert type="error" showIcon title={error} />}
    <div className="reference-filters"><Input.Search aria-label="搜索提成确认明细" style={{ width: 290 }} placeholder="搜索订单、付款公司或BD" allowClear value={search} onChange={e => { setSearch(e.target.value); if (!e.target.value) setQuery(q => ({ ...q, search: '', page: 1 })); }} onSearch={value => setQuery(q => ({ ...q, search: value, page: 1 }))} />
      <Select aria-label="提成确认季度" allowClear placeholder="全部季度" style={{ width: 140 }} value={query.quarter || undefined} onChange={value => setQuery(q => ({ ...q, quarter: value || '', page: 1 }))} options={(data?.options.quarters || []).map(value => ({ value, label: value }))} />
      <Select aria-label="提成确认BD" allowClear showSearch placeholder="全部BD" style={{ width: 150 }} value={query.owner || undefined} onChange={value => setQuery(q => ({ ...q, owner: value || '', page: 1 }))} options={(data?.options.owners || []).map(value => ({ value, label: value }))} />
      <div className={category === 'sales' ? 'sales-source-controls' : undefined}><Button onClick={() => { setSearch(''); setQuery(q => ({ ...q, search: '', quarter: '', owner: '', page: 1 })); }}>重置</Button>
      {category === 'sales' && <SalesSourceEntries />}</div>
    </div>
    <BonusTableView<RecordRow> size="small" bordered rowKey="record_key" columns={decorated(columns)} dataSource={data?.rows || []} loading={loading} scroll={{ x: 3050, y: 480 }} pagination={{ current: query.page, pageSize: query.page_size, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: total => `共 ${total.toLocaleString()} 条`, onChange: (page, page_size) => setQuery(q => ({ ...q, page: page_size === q.page_size ? page : 1, page_size })) }} locale={{ emptyText: <Empty description="当前条件下暂无记录" /> }} />
    <Modal title="订单提成确认" width={560} open={!!record} onCancel={() => setRecord(null)} confirmLoading={saving} okText="保存备注" onOk={async () => {
      if (!record) return;
      try {
        const values = await rowForm.validateFields(); setSaving(true);
        await api('/commission-data/note', { method: 'PUT', body: JSON.stringify({ record_key: record.record_key, version: record.version, note: values.note || '' }) });
        message.success('备注已保存'); setRecord(null); setRefresh(v => v + 1);
      } catch (e) { if (e instanceof Error) message.error(e.message); } finally { setSaving(false); }
    }}><Form form={rowForm} layout="vertical"><Form.Item name="note" label="备注"><Input.TextArea aria-label="订单备注" rows={6} maxLength={4000} showCount placeholder="填写备注，也可以清空原有内容" /></Form.Item></Form></Modal>
  </Card>;
}
