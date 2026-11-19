import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api, money } from './api';
import BonusTableView, { downloadBonus } from './BonusTableView';
import BonusImport from './BonusImport';

type Row = {
  id: string; version: number; employee_no: string; owner: string; meeting_date: string;
  meeting_type: string; location: string; companies: number; attendees: number;
  friend_rate: string; registrations: number; leads: number | null; qualified: boolean | null;
  bonus: string | null; bonus_formula?: boolean; note: string; follow_up: string;
  action_note: string; is_paid: boolean | null;
};
const fields = [
  ['employee_no', '工号'], ['owner', '姓名'], ['meeting_date', '会议时间'], ['meeting_type', '会议类型'],
  ['location', '会议举办地点'], ['companies', '参会企业数（≥30）'], ['attendees', '参会人数（无要求）'],
  ['friend_rate', '好友通过率（≥90%）'], ['registrations', '六重报名数'], ['leads', '意向线索企业数（≥5）'],
  ['qualified', '是否达标'], ['bonus', '会议奖金'], ['note', '特殊情况备注'], ['follow_up', '会后联系'],
];
const numeric = ['companies', 'attendees', 'friend_rate', 'registrations', 'leads', 'bonus'];
const optional = ['employee_no', 'leads', 'qualified', 'bonus', 'note', 'follow_up'];
const options = [{ value: 'yes', label: '是' }, { value: 'no', label: '否' }, { value: 'pending', label: '待确认' }];
const selection = (value?: boolean | null) => value == null ? 'pending' : value ? 'yes' : 'no';
const statusValue = (value: string) => value === 'pending' ? null : value === 'yes';
const statusTag = (value: boolean | null) => <Tag color={value == null ? 'warning' : value ? 'success' : 'default'}>{value == null ? '待确认' : value ? '是' : '否'}</Tag>;

export default function MeetingDataTable() {
  const { message } = App.useApp();
  const [data, setData] = useState<{ rows: Row[]; total: number; can_edit: boolean; can_edit_note: boolean }>();
  const [query, setQuery] = useState({ page: 1, page_size: 20, search: '' });
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [editing, setEditing] = useState<Row | null | undefined>();
  const [noteRow, setNoteRow] = useState<Row>();
  const [noteDraft, setNoteDraft] = useState('');
  const [owners, setOwners] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    let active = true;
    setLoading(true);
    api('/meetings?' + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])))
      .then(result => { if (active) { setData(result); setError(''); } })
      .catch(e => { if (active) { setError(e.message); setData(undefined); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, refresh]);

  useEffect(() => {
    const changed = () => setRefresh(v => v + 1);
    window.addEventListener('bonus-rules-changed', changed);
    return () => window.removeEventListener('bonus-rules-changed', changed);
  }, []);

  function edit(row: Row | null) {
    form.resetFields();
    form.setFieldsValue({ ...row, qualified: selection(row?.qualified) });
    setEditing(row);
    api<{name: string; role: string}[]>('/users').then(users =>
      setOwners([...new Set(users.filter(u => u.role === 'bd').map(u => u.name))])
    ).catch(e => message.error(e.message));
  }

  async function saveNote(row: Row, note: string) {
    await api('/meetings/' + row.id + '/note', {
      method: 'PUT', body: JSON.stringify({ version: row.version, note }),
    });
    setRefresh(v => v + 1);
  }

  const formulaBonus = editing == null || !!editing.bonus_formula;
  const columns: ColumnsType<Row> = fields.map(([key, title]) => ({
    title, dataIndex: key, width: key === 'note' || key === 'follow_up' ? 220 : 145,
    render: value => {
      if (key === 'qualified') return statusTag(value);
      if (key === 'bonus') return value == null ? '待确认' : money(value);
      if (key === 'friend_rate' && value != null && value !== '') return value + '%';
      return value || (value === 0 ? 0 : '—');
    },
  }));
  columns.push(
    { title: '是否发放奖金', dataIndex: 'is_paid', width: 145, render: statusTag },
    { title: '操作', key: 'action', width: 205, render: (_, row) => <>
      <div style={{ whiteSpace: 'pre-wrap' }}>{row.action_note || <span className="subtext">暂无备注</span>}</div>
      {data?.can_edit_note && <Button type="link" size="small" onClick={() => { setNoteDraft(row.action_note); setNoteRow(row); }}>确认 / 修改</Button>}
      {data?.can_edit && <Button type="link" size="small" onClick={() => edit(row)}>修改明细</Button>}
    </> },
  );

  return <Card title="会议奖金明细" className="reference-data-card" extra={<Space>
    {data?.can_edit && <Button type="primary" onClick={() => edit(null)}>新增会议</Button>}
    <Button loading={exporting} onClick={async () => {
      setExporting(true);
      try { await downloadBonus(); } catch (e) { message.error((e as Error).message); }
      finally { setExporting(false); }
    }}>导出 XLSX</Button>
    <BonusImport />
    <Button onClick={() => setRefresh(v => v + 1)}>刷新</Button>
  </Space>}>
    {error && <Alert type="error" title={error} />}
    <Input.Search style={{ maxWidth: 320, marginBottom: 16 }} placeholder="搜索姓名、会议类型或地点" allowClear onSearch={search => setQuery({ ...query, search, page: 1 })} />
    <BonusTableView<Row> bordered size="small" rowKey="id" loading={loading} columns={columns} dataSource={data?.rows || []} scroll={{ x: 2650, y: 480 }}
      pagination={{ current: query.page, pageSize: query.page_size, total: data?.total || 0, showSizeChanger: true, showTotal: total => '共 ' + total + ' 条', onChange: (page, page_size) => setQuery({ ...query, page: page_size !== query.page_size ? 1 : page, page_size }) }} />
    <Modal title="会议奖金备注" width={560} open={!!noteRow} onCancel={() => !saving && setNoteRow(undefined)}
      confirmLoading={saving} okText="保存备注" onOk={async () => {
        if (!noteRow) return;
        setSaving(true);
        try {
          await saveNote(noteRow, noteDraft);
          setNoteRow(undefined); message.success('备注已保存');
        } catch (e) { message.error((e as Error).message); }
        finally { setSaving(false); }
      }}>
      <Input.TextArea aria-label="会议奖金备注" rows={6} maxLength={4000} showCount value={noteDraft} onChange={event => setNoteDraft(event.target.value)} />
    </Modal>
    <Modal title={editing ? '修改会议奖金明细' : '新增会议奖金明细'} open={editing !== undefined} width={760}
      onCancel={() => !saving && setEditing(undefined)} confirmLoading={saving} onOk={async () => {
        try {
          const values = await form.validateFields();
          setSaving(true);
          await api(editing ? '/meetings/' + editing.id : '/meetings', {
            method: editing ? 'PUT' : 'POST', body: JSON.stringify({
              ...values, version: editing?.version || 0, qualified: statusValue(values.qualified),
              bonus_formula: formulaBonus,
            }),
          });
          setEditing(undefined); setRefresh(v => v + 1); message.success('会议记录已保存');
        } catch (e) { if (e instanceof Error) message.error(e.message); }
        finally { setSaving(false); }
      }}>
      <Form form={form} layout="vertical"><div className="form-grid">{fields.map(([key, label]) => {
        if (key === 'bonus' && formulaBonus) return <Form.Item key={key} label={label}><span className="subtext">按是否达标和会议类型计算</span></Form.Item>;
        return <Form.Item key={key} name={key} label={label} rules={optional.includes(key) ? [] : [{ required: true, message: '请填写' + label }]}>
          {key === 'owner' ? <Select showSearch options={owners.map(value => ({ value, label: value }))} />
            : key === 'qualified' ? <Select options={options} />
            : numeric.includes(key) ? <InputNumber min={0} max={key === 'friend_rate' ? 100 : undefined} precision={['bonus', 'friend_rate'].includes(key) ? 2 : 0} style={{ width: '100%' }} />
            : key === 'meeting_date' ? <Input type="date" />
            : <Input maxLength={['note', 'follow_up'].includes(key) ? 1000 : key === 'location' ? 200 : key === 'employee_no' ? 40 : 100} />}
        </Form.Item>;
      })}</div></Form>
    </Modal>
  </Card>;
}
