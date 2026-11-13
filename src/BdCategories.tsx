import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Select, Space, Tag } from 'antd';
import { api } from './api';

type Categories = { mapping: Record<string, string>; names: string[]; version: number };
export default function BdCategories({ onSaved }: { onSaved: () => void }) {
  const { message } = App.useApp();
  const [data, setData] = useState<Categories>();
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  function load() { api<Categories>('/bd-categories').then(setData).catch(e => setError(e.message)); }
  useEffect(load, []);
  return <Card title="BD身份归类器" className="reference-data-card" extra={<Button onClick={load}>重新加载</Button>}>
    <p className="subtext">初始为随机临时归类，请按实际岗位调整。归类影响全部历史订单在销售/市场奖金表中的位置；不会修改账号登录权限。</p>
    {error && <Alert type="error" title={error} />}
    <div className="bd-category-grid">{data?.names.map(name => <Space key={name}><Tag>{name}</Tag><Select aria-label={`${name}身份`} style={{ width: 110 }} value={data.mapping[name] || 'unassigned'} options={[{ value: 'sales', label: '销售' }, { value: 'market', label: '市场' }, { value: 'unassigned', label: '待归类' }]} onChange={value => setData({ ...data, mapping: { ...data.mapping, [name]: value } })} /></Space>)}</div>
    <Button type="primary" loading={saving} disabled={!data} onClick={async () => { if (!data) return; setSaving(true); try { await api('/bd-categories', { method: 'PUT', body: JSON.stringify({ mapping: data.mapping, version: data.version }) }); message.success('身份归类已保存'); load(); onSaved(); } catch (e) { message.error((e as Error).message); } finally { setSaving(false); } }}>保存归类</Button>
  </Card>;
}
