import { useEffect, useState } from 'react';
import { Alert, App, Button, Descriptions, Drawer, Form, Input, InputNumber, Select, Space, Spin, Tabs } from 'antd';
import { api } from './api';

type FieldSpec = [string, string, string];
type Snapshot = {
  owner: string; quarter: string; period: Record<string, unknown>; variables: Record<string, unknown>;
  period_version: number; order_version: number; service_version: number;
  period_fields: FieldSpec[]; order_fields: FieldSpec[]; orders: { key: string; label: string }[];
  source: Record<string, string>; service: string; rule: { enabled?: boolean; note?: string }; can_edit: boolean;
  trace?: { bonus_basis: string; revenue_total: string; bonus: string; rate_display: string; calculation: { channel: string; target: string; quarter_total: string; before: string; inside_basis: string; excess_basis: string; crossing: boolean; over_target: boolean | null; ordinary_bonus: string; segmented_bonus: string; problems: string[]; overrides: string[]; finance_difference: string; refund_period: string; payment_period: string } };
};
const tri = [{ value: 'auto', label: '使用来源判断/待确认' }, { value: 'yes', label: '是' }, { value: 'no', label: '否' }];
function valuesForForm(values: Record<string, unknown>, fields: FieldSpec[]) {
  return Object.fromEntries(fields.map(([key, , kind]) => [key, kind === 'tri' ? values[key] === true ? 'yes' : values[key] === false ? 'no' : 'auto' : kind === 'number' && values[key] != null ? Number(values[key]) : values[key]]));
}
export default function SalesFormulaInputs({ open, onClose, owners, quarters, initialOwner, initialQuarter, initialRecord, onSaved }: { open: boolean; onClose: () => void; owners: string[]; quarters: string[]; initialOwner: string; initialQuarter: string; initialRecord: string; onSaved: () => void }) {
  const { message } = App.useApp();
  const [owner, setOwner] = useState('');
  const [quarter, setQuarter] = useState('');
  const [record, setRecord] = useState('');
  const [data, setData] = useState<Snapshot>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const [activeTab, setActiveTab] = useState('period');
  const [periodForm] = Form.useForm();
  const [orderForm] = Form.useForm();
  const [serviceForm] = Form.useForm();
  useEffect(() => { if (open) { setActiveTab('period'); setOwner(initialOwner || owners[0] || ''); setQuarter(initialQuarter || quarters[0] || ''); setRecord(initialRecord); } }, [open, initialOwner, initialQuarter, initialRecord]);
  useEffect(() => {
    if (!open || !owner || !quarter) return;
    let active = true; setLoading(true); setData(undefined); setError('');
    api<Snapshot>('/sales-formulas/inputs?' + new URLSearchParams({ owner, quarter, record })).then(result => {
      if (!active) return;
      if (!record && result.orders.length) { setRecord(result.orders[0].key); return; }
      setData(result);
      periodForm.resetFields(); orderForm.resetFields(); serviceForm.resetFields();
      periodForm.setFieldsValue(valuesForForm(result.period, result.period_fields));
      orderForm.setFieldsValue(valuesForForm(result.variables, result.order_fields));
      serviceForm.setFieldsValue(result.rule);
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, owner, quarter, record, revision]);
  function input([key, label, kind]: FieldSpec) {
    return <Form.Item key={key} name={key} label={label} rules={kind === 'number' && ['threshold','vip_minimum'].includes(key) || key.endsWith('_rate') || key.endsWith('_excess') ? [{ required: true }] : []}>
      {kind === 'number' ? <InputNumber style={{ width: '100%' }} min={0} max={key.endsWith('_rate') || key.endsWith('_excess') ? 100 : 1000000000000} precision={key.endsWith('_rate') || key.endsWith('_excess') ? 4 : 2} placeholder="未配置" /> : kind === 'boolean' ? <Select options={[{value:true,label:'包含（Excel原口径）'},{value:false,label:'仅计提订单'}]} /> : kind === 'tri' ? <Select options={tri} /> : kind === 'channel' ? <Select options={[{value:'auto',label:'按推荐标记及来源自动判断'},{value:'self',label:'自拓'},{value:'market',label:'市场推荐'},{value:'partner',label:'协会/合伙人'}]} /> : <Input type={['date','datetime-local'].includes(kind) ? kind : 'text'} maxLength={key.includes('note') ? 1000 : 200} />}
    </Form.Item>;
  }
  async function save(kind: 'period' | 'order') {
    if (!data) return;
    const form = kind === 'period' ? periodForm : orderForm;
    try {
      const values = await form.validateFields(); setSaving(true);
      const fields = kind === 'period' ? data.period_fields : data.order_fields;
      const payload = Object.fromEntries(fields.map(([key,,type]) => [key, type === 'tri' ? values[key] === 'auto' ? null : values[key] === 'yes' : values[key] === '' && ['number','date','datetime-local'].includes(type) ? null : values[key] ?? (['number','date','datetime-local'].includes(type) ? null : '')]));
      await api(`/sales-formulas/inputs/${kind}`, { method: 'PUT', body: JSON.stringify({ owner, quarter, record, version: kind === 'period' ? data.period_version : data.order_version, note: values.change_note, [kind === 'period' ? 'period' : 'variables']: payload }) });
      message.success('变量已保存，销售公式已重新计算'); setRevision(v => v+1); onSaved();
    } catch (e) { if (e instanceof Error) message.error(e.message); } finally { setSaving(false); }
  }
  const note = <Form.Item name="change_note" label="本次修改依据" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={2} maxLength={1000} /></Form.Item>;
  const calculation = data?.trace?.calculation;
  return <Drawer title="销售公式变量 · 赋值与计算依据" open={open} onClose={onClose} size={780} styles={{body:{padding:20}}}>
    <Alert type="info" showIcon title="季度参数按BD＋季度保存；订单变量只作用于选中来源行" description="销售服务规则作用于销售表同名服务，不修改市场规则。保存后列表及导出使用同一公式。切换人员/订单会放弃未保存输入。" />
    <Space wrap style={{marginBottom:16}}><Select aria-label="公式变量BD" style={{width:150}} value={owner || undefined} onChange={value => {setOwner(value);setRecord('');}} options={owners.map(value=>({value,label:value}))} /><Select aria-label="公式变量季度" style={{width:150}} value={quarter || undefined} onChange={value=>{setQuarter(value);setRecord('');}} options={quarters.map(value=>({value,label:value}))} /><Button onClick={()=>setRevision(v=>v+1)}>重新加载</Button></Space>
    {error && <Alert type="error" title={error} />}
    {!owners.length && <Alert type="info" title="暂无销售记录，请先确认BD身份归类" />}
    <Spin spinning={loading}>
    {data && <><Select aria-label="公式变量订单" style={{width:'100%',marginBottom:18}} showSearch optionFilterProp="label" value={record || undefined} onChange={setRecord} options={data.orders.map(r=>({value:r.key,label:r.label}))} />
      <p className="subtext">参数按原表列名及列号标注。“公式常数”为原单元格公式中的固定数值，非原表独立列；“计算口径”和“网页补充项”亦单独标明。推广金额、财务信息用于核对；退款金额不自动扣奖。</p><Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        {key:'period',label:'BD季度参数',children:<Form name="sales-period" form={periodForm} layout="vertical" disabled={!data.can_edit}><div className="form-grid">{data.period_fields.map(input)}</div>{data.can_edit && <>{note}<Button type="primary" loading={saving} onClick={()=>save('period')}>保存季度参数并计算</Button></>}</Form>},
        {key:'order',label:'订单外部变量',children:<><p>订单号C：{data.source['订单号']}。岗位由身份归类器管理。表内比例、基数、提点和奖金的人工覆盖在“确认 / 修改”中维护。</p><Form name="sales-order" form={orderForm} layout="vertical" disabled={!data.can_edit}><div className="form-grid">{data.order_fields.map(input)}</div>{data.can_edit && <>{note}<Button type="primary" loading={saving} onClick={()=>save('order')}>保存订单变量并计算</Button></>}</Form></>},
        {key:'service',label:'R 所购服务是否计发提成',children:<><p>所购服务：<strong>{data.service}</strong></p>{data.service === '团队VIP' ? <Alert type="info" title="团队VIP按当前BD季度的金额门槛判断；单笔特殊情况在确认/修改中覆盖。" /> : <Form name="sales-service" form={serviceForm} layout="vertical" disabled={!data.can_edit}><Form.Item name="enabled" label="R 所购服务是否计发提成" rules={[{required:true}]}><Select options={[{value:true,label:'计发'},{value:false,label:'不计发'}]} /></Form.Item><Form.Item name="note" label="规则依据" rules={[{required:true,whitespace:true}]}><Input.TextArea maxLength={500} /></Form.Item>{data.can_edit && <Button type="primary" loading={saving} onClick={async()=>{try{const values=await serviceForm.validateFields();setSaving(true);await api('/sales-formulas/service',{method:'PUT',body:JSON.stringify({owner,quarter,record,version:data.service_version,...values})});message.success('销售服务规则已保存');setRevision(v=>v+1);onSaved();}catch(e){if(e instanceof Error)message.error(e.message);}finally{setSaving(false);}}}>保存销售服务规则</Button>}</Form>}</>},
        {key:'trace',label:'自动中间变量',children:<>{calculation?.problems.length ? <Alert type="warning" title="待配置/核对" description={calculation.problems.join('；')} /> : null}{calculation?.overrides.length ? <Alert type="info" title={'人工覆盖：'+calculation.overrides.join('、')} /> : null}<Descriptions bordered size="small" column={1} items={[
          ['U 成单渠道',({self:'自拓',market:'市场推荐',partner:'协会/合伙人',pending:'待确认'} as Record<string,string>)[calculation?.channel || '']],['W 当季度目标',calculation?.target],['奖金计算基数 · 同BD同季度合计（辅助计算，原表无独立列）',calculation?.quarter_total],['累计营收 · 本单前（辅助计算，原表无独立列）',calculation?.before],['T 累计营收',data.trace?.revenue_total],['K 奖金计算基数',data.trace?.bonus_basis],['V 累计是否超额完成',calculation?.over_target == null ? '待配置' : calculation.over_target ? '是':'否'],['Z 是否适用分段计算',calculation?.crossing ? '是':'否'],['提成计算2 · 目标内基数（公式拆解）',calculation?.inside_basis],['提成计算2 · 超额基数（公式拆解）',calculation?.excess_basis],['X 适用提点',data.trace?.rate_display],['Y 提成计算1',calculation?.ordinary_bonus],['AA 提成计算2',calculation?.segmented_bonus],['AB 合计提成',data.trace?.bonus],['AN 订单金额check',calculation?.finance_difference],['AE 付款所属期间',calculation?.payment_period],['AL 退款期间',calculation?.refund_period],
        ].map(([label,value])=>({key:label,label,children:value ?? '待配置/不适用'}))} /><p className="subtext">V超额、Y普通计算、AA分段计算由上述输入推导，不接受手工赋值。重复行按来源保留，不自动去重。AO:AS同组/跨组自动查重尚未接入，使用已确认共享信息。退款仅识别，不自动冲减奖金；是否发放仍按人工记录。</p></>},
      ]} />
    </>}
    </Spin>
  </Drawer>;
}
