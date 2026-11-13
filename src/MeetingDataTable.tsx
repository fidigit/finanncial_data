import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api, money } from './api';
import BonusTableView, { downloadBonus } from './BonusTableView';

type Row = { id: string; version: number; owner: string; meeting_date: string; meeting_type: string; location: string; companies: number; attendees: number; friend_rate: string; registrations: number; leads: number; qualified: boolean | null; bonus: string | null; note: string; follow_up: string; is_paid: boolean | null };
const fields = [['owner','姓名'],['meeting_date','会议时间'],['meeting_type','会议类型'],['location','会议举办地点'],['companies','参会企业数'],['attendees','参会人数'],['friend_rate','好友通过率（≥90%）'],['registrations','六重报名数'],['leads','意向线索企业数（≥5）'],['qualified','是否达标'],['bonus','会议奖金'],['note','特殊情况备注'],['follow_up','会后联系'],['is_paid','还否发放奖金']];
const numeric = ['companies', 'attendees', 'friend_rate', 'registrations', 'leads', 'bonus'];
const flags = ['qualified', 'is_paid'];
const options = [{ value: 'pending', label: '待确认' }, { value: 'yes', label: '是' }, { value: 'no', label: '否' }];
export default function MeetingDataTable() {
  const { message } = App.useApp();
  const [data, setData] = useState<{ rows: Row[]; total: number; can_edit: boolean }>();
  const [query, setQuery] = useState({ page: 1, page_size: 20, search: '' });
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [editing, setEditing] = useState<Row | null | undefined>();
  const [owners, setOwners] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  useEffect(() => { let active = true; setLoading(true); api('/meetings?' + new URLSearchParams(Object.entries(query).map(([k,v]) => [k,String(v)]))).then(result => { if (active) { setData(result); setError(''); } }).catch(e => { if (active) { setError(e.message); setData(undefined); } }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [query, refresh]);
  function edit(row: Row | null) { form.resetFields(); form.setFieldsValue({ ...row, qualified: row?.qualified == null ? 'pending' : row.qualified ? 'yes' : 'no', is_paid: row?.is_paid == null ? 'pending' : row.is_paid ? 'yes' : 'no' }); setEditing(row); api<{name:string;role:string}[]>('/users').then(users => setOwners([...new Set(users.filter(u => u.role === 'bd').map(u => u.name))])).catch(e => message.error(e.message)); }
  const columns: ColumnsType<Row> = fields.map(([key, title]) => ({ title, dataIndex: key, width: key === 'note' || key === 'follow_up' ? 220 : 145, render: value => flags.includes(key) ? <Tag>{value == null ? '待确认' : value ? '是' : '否'}</Tag> : key === 'bonus' ? value == null ? '待确认' : money(value) : key === 'friend_rate' ? `${value}%` : value || (value === 0 ? 0 : '—') }));
  const actions = { title: '操作', key: 'action', width: 90, render: (_: unknown, row: Row) => <Button type="link" onClick={() => edit(row)}>修改</Button> };
  return <Card title="会议奖金明细" className="reference-data-card" extra={<Space>{data?.can_edit && <Button type="primary" onClick={() => edit(null)}>新增会议</Button>}<Button loading={exporting} onClick={async () => { setExporting(true); try { await downloadBonus('meetings', query); } catch(e) { message.error((e as Error).message); } finally { setExporting(false); } }}>导出 XLSX</Button><Button onClick={() => setRefresh(v => v+1)}>刷新</Button></Space>}>
    {error && <Alert type="error" title={error} />}
    <Input.Search style={{ maxWidth: 320, marginBottom: 16 }} placeholder="搜索姓名、会议类型或地点" allowClear onSearch={search => setQuery({ ...query, search, page: 1 })} />
    <BonusTableView<Row> bordered size="small" rowKey="id" loading={loading} columns={data?.can_edit ? [...columns, actions] : columns} dataSource={data?.rows || []} scroll={{ x: 2300, y: 480 }} pagination={{ current: query.page, pageSize: query.page_size, total: data?.total || 0, showSizeChanger: true, showTotal: total => `共 ${total} 条`, onChange: (page, page_size) => setQuery({ ...query, page: page_size !== query.page_size ? 1 : page, page_size }) }} />
    <Modal title={editing ? '修改会议奖金明细' : '新增会议奖金明细'} open={editing !== undefined} width={760} onCancel={() => setEditing(undefined)} confirmLoading={saving} onOk={async () => { try { const values = await form.validateFields(); setSaving(true); await api(editing ? `/meetings/${editing.id}` : '/meetings', { method: editing ? 'PUT' : 'POST', body: JSON.stringify({ ...values, version: editing?.version || 0, qualified: values.qualified === 'pending' ? null : values.qualified === 'yes', is_paid: values.is_paid === 'pending' ? null : values.is_paid === 'yes' }) }); setEditing(undefined); setRefresh(v => v+1); message.success('会议记录已保存'); } catch(e) { if(e instanceof Error) message.error(e.message); } finally { setSaving(false); } }}>
      <Form form={form} layout="vertical"><div className="form-grid">{fields.map(([key,label]) => <Form.Item key={key} name={key} label={label} rules={['note','follow_up','bonus',...flags].includes(key) ? [] : [{ required: true, message: `请填写${label}` }]}>{key === 'owner' ? <Select showSearch options={owners.map(value => ({value,label:value}))} /> : flags.includes(key) ? <Select options={options} /> : numeric.includes(key) ? <InputNumber min={0} max={key === 'friend_rate' ? 100 : undefined} precision={['bonus','friend_rate'].includes(key) ? 2 : 0} style={{width:'100%'}} /> : key === 'meeting_date' ? <Input type="date" /> : <Input maxLength={['note','follow_up'].includes(key) ? 1000 : key === 'location' ? 200 : 100} />}</Form.Item>)}</div></Form>
    </Modal>
  </Card>;
}
