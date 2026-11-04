import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Empty, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined, SlidersOutlined } from '@ant-design/icons';
import { api, money } from './api';

type RecordRow = {
  row_id: number; record_key: string; order_no: string; quarter: string; owner: string; company: string;
  paid_date: string; service: string; purchase_type: string; order_amount: string; enabled: boolean | null;
  rule_note: string; shared_bd: string; allocation_ratio: string | null; bonus_basis: string | null;
  market_bd: string; market_pending: boolean; referral: string; revenue_total: string | null;
  confirmed_rate: string | null; bonus: string | null; is_paid: boolean | null; is_refunded: boolean | null;
  note: string; source_bonus: string; version: number; confirmation: Record<string, unknown>;
};
type Snapshot = { rows: RecordRow[]; total: number; options: { quarters: string[]; owners: string[]; projects: string[] }; pending_services: string[]; can_edit: boolean; rules: Record<string, { enabled: boolean; note: string }> };
const flag = (value: boolean | null, pending = '待确认') => value === null ? <Tag color="warning">{pending}</Tag> : <Tag color={value ? 'success' : 'default'}>{value ? '是' : '否'}</Tag>;
const amount = (value: string | null) => value === null ? <span className="subtext">待确认</span> : money(value);
const optionalText = (value: string) => value || <span className="reference-empty">—</span>;
const triOptions = [{ value: 'pending', label: '待确认' }, { value: 'yes', label: '是' }, { value: 'no', label: '否' }];
const tri = (value: unknown) => value === true ? 'yes' : value === false ? 'no' : 'pending';
const bool = (value: string) => value === 'yes' ? true : value === 'no' ? false : null;

export default function CommissionDataTable() {
  const { message } = App.useApp();
  const [data, setData] = useState<Snapshot | null>(null);
  const [query, setQuery] = useState({ page: 1, page_size: 20, search: '', quarter: '', owner: '' });
  const [search, setSearch] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [ruleOpen, setRuleOpen] = useState(false);
  const [record, setRecord] = useState<RecordRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [ruleForm] = Form.useForm();
  const [rowForm] = Form.useForm();
  const sequence = useRef(0);
  useEffect(() => { const timer = window.setInterval(() => setRefresh(v => v + 1), 15000); return () => window.clearInterval(timer); }, []);
  useEffect(() => {
    const current = ++sequence.current;
    setLoading(true); setError('');
    api<Snapshot>('/commission-data?' + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]))).then(result => {
      if (current === sequence.current) setData(result);
    }).catch(e => { if (current === sequence.current) { setData(null); setError(e.message); } }).finally(() => { if (current === sequence.current) setLoading(false); });
    return () => { sequence.current++; };
  }, [query, refresh]);
  function edit(row: RecordRow) {
    rowForm.resetFields();
    rowForm.setFieldsValue({ ...row.confirmation, enabled: tri(row.confirmation.enabled), is_paid: tri(row.is_paid), is_refunded: tri(row.is_refunded), allocation_ratio: row.allocation_ratio === null ? undefined : Number(row.allocation_ratio) * 100, confirmed_rate: row.confirmed_rate === null ? undefined : Number(row.confirmed_rate) * 100 });
    setRecord(row);
  }
  const textColumn = (title: string, field: keyof RecordRow, width = 120) => ({ title, dataIndex: field, key: field, width, ellipsis: true, render: (value: string) => <Tooltip title={value}>{optionalText(value)}</Tooltip> });
  const columns: ColumnsType<RecordRow> = [
    { title: '订单信息', children: [
      { ...textColumn('季度', 'quarter', 100), fixed: 'start' }, { ...textColumn('BD姓名', 'owner', 110), fixed: 'start' },
      textColumn('付款公司', 'company', 280), textColumn('付款时间', 'paid_date', 160), textColumn('所购服务', 'service', 200), textColumn('首购/续费', 'purchase_type', 105),
      { title: '订单金额', dataIndex: 'order_amount', width: 130, align: 'right', render: value => value ? money(value) : '—' },
      { title: '是否计发提成', width: 155, render: (_, r) => <Tooltip title={r.note || r.rule_note || '请先设置该服务是否计发提成'}>{flag(r.enabled, '待设置规则')}</Tooltip> },
    ] },
    { title: '确认基数', children: [textColumn('共享订单', 'shared_bd', 160), { title: '分摊比例', dataIndex: 'allocation_ratio', width: 125, align: 'right', render: value => value === null ? '待确认' : `${Number(value) * 100}%` }, { title: '奖金计算基数', dataIndex: 'bonus_basis', width: 150, align: 'right', render: amount }] },
    { title: '确认提点（结合首购/续费）', children: [
      { title: '市场渠道', width: 165, render: (_, r) => r.market_bd || (r.market_pending ? <Tag color="warning">待补市场BD姓名</Tag> : '—') },
      textColumn('转介绍', 'referral', 170),
      { title: '累计营收', width: 150, render: () => <Tooltip title="累计周期、计提范围、重复订单与退款口径确认后计算"><span className="subtext">待确认累计口径</span></Tooltip> },
      { title: '适用提点（分段提点）', width: 185, render: (_, r) => r.confirmed_rate === null ? <span className="subtext">待确认分段提点</span> : <Tooltip title="人工确认提点，尚未执行分段规则引擎">{Number(r.confirmed_rate) * 100}%</Tooltip> },
    ] },
    { title: '奖金', width: 150, align: 'right', render: (_, r) => <Tooltip title={`来源奖金：${r.source_bonus || '空'}；本列为人工确认奖金，未自动计发`}>{amount(r.bonus)}</Tooltip> },
    { title: '是否发放', dataIndex: 'is_paid', width: 110, render: value => flag(value) },
    { title: '是否退款', dataIndex: 'is_refunded', width: 110, render: value => flag(value) },
    { title: '备注', width: 260, render: (_, r) => <div><div style={{ whiteSpace: 'pre-wrap' }}>{r.note || r.rule_note || <span className="subtext">暂无备注</span>}</div>{data?.can_edit && <Button type="link" size="small" onClick={() => edit(r)}>确认 / 修改</Button>}</div> },
  ];
  return <Card className="reference-data-card commission-data-card" title="BD提成确认明细" extra={<Space>{data?.can_edit && <Button icon={<SlidersOutlined />} onClick={() => { ruleForm.resetFields(); setRuleOpen(true); }}>服务提成规则</Button>}<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRefresh(v => v + 1)}>刷新明细</Button></Space>}>
    <p className="subtext">来源：参考数据.csv；与上表采用相同的人员权限。付款公司优先取付款户名，缺失时取业务id信息；本表为人工确认区，未自动生成结算或付款。</p>
    {!!data?.pending_services.length && <Alert type="warning" showIcon title={`发现 ${data.pending_services.length} 个服务尚未设置是否计发提成`} description={data.can_edit ? '请通过“服务提成规则”逐项设置。以后出现新服务名也会自动提醒；未设置时不默认计发。' : '请联系管理员确认服务提成规则。'} />}
    {error && <Alert type="error" showIcon title={error} />}
    <div className="reference-filters"><Input.Search aria-label="搜索提成确认明细" style={{ width: 290 }} placeholder="搜索订单、付款公司或BD" allowClear value={search} onChange={e => { setSearch(e.target.value); if (!e.target.value) setQuery(q => ({ ...q, search: '', page: 1 })); }} onSearch={value => setQuery(q => ({ ...q, search: value, page: 1 }))} />
      <Select aria-label="提成确认季度" allowClear placeholder="全部季度" style={{ width: 140 }} value={query.quarter || undefined} onChange={value => setQuery(q => ({ ...q, quarter: value || '', page: 1 }))} options={(data?.options.quarters || []).map(value => ({ value, label: value }))} />
      <Select aria-label="提成确认BD" allowClear showSearch placeholder="全部BD" style={{ width: 150 }} value={query.owner || undefined} onChange={value => setQuery(q => ({ ...q, owner: value || '', page: 1 }))} options={(data?.options.owners || []).map(value => ({ value, label: value }))} />
      <Button onClick={() => { setSearch(''); setQuery(q => ({ ...q, search: '', quarter: '', owner: '', page: 1 })); }}>重置</Button>
    </div>
    <Table<RecordRow> size="small" bordered rowKey="record_key" columns={columns} dataSource={data?.rows || []} loading={loading} scroll={{ x: 3050, y: 480 }} pagination={{ current: query.page, pageSize: query.page_size, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: total => `共 ${total.toLocaleString()} 条`, onChange: (page, page_size) => setQuery(q => ({ ...q, page: page_size === q.page_size ? page : 1, page_size })) }} locale={{ emptyText: <Empty description="当前条件下暂无记录" /> }} />
    <Modal title="服务提成规则" open={ruleOpen} onCancel={() => setRuleOpen(false)} confirmLoading={saving} okText="保存规则" onOk={async () => {
      try { const values = await ruleForm.validateFields(); setSaving(true); await api('/commission-data/service-rule', { method: 'PUT', body: JSON.stringify(values) }); message.success('服务规则已保存'); setRuleOpen(false); setRefresh(v => v + 1); } catch (e) { if (e instanceof Error) message.error(e.message); } finally { setSaving(false); }
    }}><Form form={ruleForm} layout="vertical"><Form.Item name="service" label="所购服务" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" placeholder="选择服务（新服务标记为待设置）" options={(data?.options.projects || []).map(value => ({ value, label: `${value}${data?.rules[value] ? '' : ' · 待设置'}` }))} onChange={value => ruleForm.setFieldsValue({ enabled: data?.rules[value]?.enabled, note: data?.rules[value]?.note || '' })} /></Form.Item><Form.Item name="enabled" label="是否计发提成" rules={[{ required: true }]}><Select options={[{ value: true, label: '计发' }, { value: false, label: '不计发' }]} /></Form.Item><Form.Item name="note" label="规则备注" rules={[{ required: true, whitespace: true, message: '请填写设置依据或说明' }]}><Input.TextArea rows={3} maxLength={500} /></Form.Item></Form><Alert type="info" title="规则影响该服务全部记录；单笔自定义确认优先，原始CSV不被修改。" /></Modal>
    <Modal title="订单提成确认" width={680} open={!!record} onCancel={() => setRecord(null)} confirmLoading={saving} okText="保存确认" onOk={async () => {
      if (!record) return;
      try {
        const values = await rowForm.validateFields(); setSaving(true);
        await api('/commission-data/confirmation', { method: 'PUT', body: JSON.stringify({ ...values, record_key: record.record_key, version: record.version, enabled: bool(values.enabled), is_paid: bool(values.is_paid), is_refunded: bool(values.is_refunded), allocation_ratio: values.allocation_ratio == null ? null : (values.allocation_ratio / 100).toFixed(6), confirmed_rate: values.confirmed_rate == null ? null : (values.confirmed_rate / 100).toFixed(6) }) });
        message.success('确认信息已保存'); setRecord(null); setRefresh(v => v + 1);
      } catch (e) { if (e instanceof Error) message.error(e.message); } finally { setSaving(false); }
    }}><p className="subtext">订单：{record?.order_no} · 来源行 {record?.row_id}。修改保存在确认层，不覆盖原始记录。</p><Form form={rowForm} layout="vertical"><div className="form-grid">
      <Form.Item name="enabled" label="是否计发提成"><Select options={[{ value: 'pending', label: '使用服务规则' }, { value: 'yes', label: '本单计发' }, { value: 'no', label: '本单不计发' }]} /></Form.Item>
      <Form.Item name="shared_bd" label="共享订单（参与BD姓名）"><Input placeholder="无共享可留空；多人用逗号分隔" maxLength={200} /></Form.Item>
      <Form.Item name="allocation_ratio" label="分摊比例（%）"><InputNumber style={{ width: '100%' }} min={0} max={100} precision={4} /></Form.Item>
      <Form.Item name="bonus_basis" label="奖金计算基数（元）"><InputNumber style={{ width: '100%' }} precision={2} /></Form.Item>
      <Form.Item name="market_bd" label="市场渠道（市场BD姓名）"><Input maxLength={100} /></Form.Item>
      <Form.Item name="confirmed_rate" label="确认提点（%，结合首购/续费）"><InputNumber style={{ width: '100%' }} min={0} max={100} precision={4} /></Form.Item>
      <Form.Item name="bonus" label="奖金（元，人工确认）"><InputNumber style={{ width: '100%' }} precision={2} /></Form.Item>
      <Form.Item name="is_paid" label="是否发放"><Select options={triOptions} /></Form.Item>
      <Form.Item name="is_refunded" label="是否退款"><Select options={triOptions} /></Form.Item>
    </div><Form.Item name="note" label="修改备注 / 确认依据" rules={[{ required: true, whitespace: true, message: '请填写修改或确认依据' }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item></Form></Modal>
  </Card>;
}
