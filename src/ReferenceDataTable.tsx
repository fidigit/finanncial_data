import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Empty, Input, Select, Space, Switch, Table, Tag, Tooltip } from 'antd';
import { DatabaseOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from './api';

type Row = { row_id: number; values: Record<string, string> };
type Snapshot = {
  columns: string[]; rows: Row[]; total: number; source_total: number; source_name: string;
  duplicate_order_rows: number; options: { quarters: string[]; owners: string[]; projects: string[]; ownerships: string[] };
  access_scope: 'self' | 'all'; policy_version: number;
};
type Policy = { self_only: boolean; version: number; can_manage: boolean };
const moneyFields = new Set(['订单金额', '营收金额', '奖金金额']);
const widths: Record<string, number> = { '季度': 105, 'BD姓名': 105, '运营姓名': 110, '付费时间': 180, '付费项目': 155, '业务id信息': 310, '订单号': 310, '付款户名': 170, '订单来源补充': 190, '直接/间接收入': 145, '有/无归属BD': 135 };

export default function ReferenceDataTable() {
  const { message } = App.useApp();
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState({ page: 1, page_size: 20, search: '', quarter: '', owner: '', project: '', ownership: '' });
  const [searchInput, setSearchInput] = useState('');
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [policySaving, setPolicySaving] = useState(false);
  const policyVersion = useRef<number | null>(null);
  useEffect(() => {
    let active = true;
    const readPolicy = async () => {
      try {
        const result = await api<Policy>('/reference-data/policy');
        if (!active) return;
        if (policyVersion.current !== null && policyVersion.current !== result.version) {
          setData(null); setQuery(q => ({ ...q, page: 1 }));
        }
        policyVersion.current = result.version; setPolicy(result);
      } catch { /* Data queries enforce the current policy even when status polling fails. */ }
    };
    readPolicy();
    const timer = window.setInterval(readPolicy, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    const current = ++sequence.current;
    setLoading(true); setError('');
    const params = new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)]));
    api<Snapshot>(`/reference-data?${params}`).then(result => {
      if (current === sequence.current) setData(result);
    }).catch(e => {
      if (current === sequence.current) { setError(e.message); setData(null); }
    }).finally(() => { if (current === sequence.current) setLoading(false); });
    return () => { sequence.current++; };
  }, [query, refresh]);
  const filter = (key: string, value: string | undefined) => setQuery(q => ({ ...q, [key]: value || '', page: 1 }));
  return <Card className="reference-data-card" title={<Space><DatabaseOutlined /><span>业务参考数据</span><Tag color="blue">CSV 样例</Tag></Space>} extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRefresh(v => v + 1)}>刷新数据</Button>}>
    <div className="reference-intro"><div>来源：<strong>{data?.source_name || '参考数据.csv'}</strong><span>可见记录 {data?.source_total.toLocaleString() ?? '—'} 行</span><span>{data?.columns.length ?? 18} 个字段</span>{data && <span>{data.access_scope === 'self' ? '仅本人账单' : '全部账单'}</span>}</div><p>按原始文件展示，奖金比例与金额保留源值。本表独立筛选，暂未联动下方演示奖金及其他模块。</p></div>
    <div className="reference-filters"><Input.Search allowClear value={searchInput} placeholder="搜索订单、BD、企业或任意字段" aria-label="搜索参考数据" style={{ width: 290 }} onChange={event => { const value = event.target.value; setSearchInput(value); if (!value) filter('search', ''); }} onSearch={value => filter('search', value)} enterButton="搜索" />
      {([
        ['quarter', 'quarters', '全部季度', 130], ['owner', 'owners', '全部 BD', 150],
        ['project', 'projects', '全部付费项目', 170],
      ] as const).map(([key, optionKey, placeholder, width]) => <Select key={key} aria-label={placeholder} allowClear showSearch optionFilterProp="label" style={{ width }} placeholder={placeholder} value={query[key] || undefined} onChange={value => filter(key, value)} options={(data?.options[optionKey] || []).map(value => ({ value, label: value }))} />)}
      <div className="reference-scope-controls">
        <Select aria-label="全部归属状态" allowClear style={{ width: 150 }} placeholder="全部归属状态" value={query.ownership || undefined} onChange={value => filter('ownership', value)} options={(data?.options.ownerships || []).map(value => ({ value, label: value }))} />
        {policy?.can_manage && <Tooltip title={policy.self_only ? '关闭后BD可查看全部账单' : '开启后BD仅可查看本人账单'}><span className="reference-scope-switch-slot"><Switch className="reference-scope-switch" aria-label="BD仅查看本人账单" checked={policy.self_only} loading={policySaving} disabled={policySaving} onChange={async checked => {
          setPolicySaving(true);
          try {
            const result = await api<Policy>('/reference-data/policy', { method: 'PUT', body: JSON.stringify({ self_only: checked, version: policy.version }) });
            policyVersion.current = result.version; setPolicy(result); setData(null); setQuery(q => ({ ...q, page: 1 }));
            message.success(checked ? '已开启：BD仅可查看本人账单' : '已关闭：BD可查看全部账单');
          } catch (e) {
            message.error((e as Error).message);
            api<Policy>('/reference-data/policy').then(result => { policyVersion.current = result.version; setPolicy(result); }).catch(() => {});
          } finally { setPolicySaving(false); }
        }} /></span></Tooltip>}
        <Button className="reference-reset" onClick={() => { setSearchInput(''); setQuery({ page: 1, page_size: query.page_size, search: '', quarter: '', owner: '', project: '', ownership: '' }); }}>重置</Button>
      </div>
    </div>
    {error && <Alert type="error" showIcon title={error} action={<Button onClick={() => setRefresh(v => v + 1)}>重试</Button>} />}
    <Table<Row> rowKey="row_id" dataSource={data?.rows || []} loading={loading} size="small" scroll={{ x: 2940, y: 480 }}
      columns={(data?.columns || []).map((name, index) => ({
        title: name, key: name, width: widths[name] || 130, fixed: index < 2 ? 'start' as const : undefined,
        align: moneyFields.has(name) || name === '奖金比例' ? 'right' as const : undefined,
        render: (_: unknown, row: Row) => {
          const value = row.values[name];
          if (!value) return <span className="reference-empty">—</span>;
          if (name === '有/无归属BD') return <Tag color={value === '无归属' ? 'warning' : 'default'}>{value}</Tag>;
          if (moneyFields.has(name) || name === '奖金比例') return <span className="reference-number">{value}</span>;
          return <Tooltip title={value}><span className="reference-cell">{value}</span></Tooltip>;
        },
      }))}
      pagination={{ current: query.page, pageSize: query.page_size, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: total => `筛选结果 ${total.toLocaleString()} 条`, onChange: (page, page_size) => setQuery(q => ({ ...q, page: page_size === q.page_size ? page : 1, page_size })) }}
      locale={{ emptyText: <Empty description={error ? '暂时无法读取参考数据' : '当前筛选条件下暂无记录'} /> }} />
    <div className="reference-footnote">空值显示为“—”；订单号重复保留，按原始数据行区分。后续接入 MySQL 时可替换数据读取层。</div>
  </Card>;
}
