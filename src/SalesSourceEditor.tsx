import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Empty, Input, InputNumber, Select, Space, Spin, Table, Tag } from 'antd';
import { PlusOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from './api';
import { RULE_PARAMETERS } from './SalesFixedRuleContent';

type TargetRow = { BD姓名:string; 季度:string; 直接营收目标:string|number|null };
type ServiceRow = { 所购服务:string; 是否计入提成范围:string; added?:boolean; localKey?:string };
type ConfigData = {
  quarter?:string; quarters?:string[]; year?:number; years?:number[]; missing_years?:number[]; missing_services?:{service:string;count:number}[];
  rows?: (TargetRow|ServiceRow)[]; parameters?:Record<string,string|number|boolean|null>;
  version:number; can_edit:boolean; exists?:boolean; can_copy?:boolean; previous_quarter?:string; previous_year?:number;
};
export type EditorKind = 'targets'|'services'|'constants';
const endpoint:Record<EditorKind,string>={targets:'targets',services:'plans',constants:'constants'};
const years=Array.from({length:100},(_,i)=>2000+i);
const quarters=years.flatMap(year=>[1,2,3,4].map(q=>`${year}Q${q}`));
const constantFields=[...(RULE_PARAMETERS.S||[]),...(RULE_PARAMETERS.X||[])];

export default function SalesSourceEditor({kind,onDirtyChange,onBusyChange}:{kind:EditorKind;onDirtyChange:(dirty:boolean)=>void;onBusyChange:(busy:boolean)=>void}){
  const {message,modal}=App.useApp();
  const [selection,setSelection]=useState<string|number>(),[data,setData]=useState<ConfigData>();
  const [rows,setRows]=useState<(TargetRow|ServiceRow)[]>([]),[parameters,setParameters]=useState<Record<string,number|null>>({});
  const [loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[dirty,setDirty]=useState(false),[revision,setRevision]=useState(0);
  const sequence=useRef(0),alive=useRef(true),ownSave=useRef(false);
  const dirtyRef=useRef(false);dirtyRef.current=dirty;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{onDirtyChange(dirty);return()=>onDirtyChange(false);},[dirty,onDirtyChange]);
  useEffect(()=>{onBusyChange(busy||loading);return()=>onBusyChange(false);},[busy,loading,onBusyChange]);
  useEffect(()=>{
    const changed=()=>{
      if(ownSave.current)return;
      if(dirtyRef.current){setError('其他配置已更新。请先保存草稿；若提示版本冲突，请重新加载后重填。');return;}
      setRevision(v=>v+1);
    };
    window.addEventListener('bonus-rules-changed',changed);return()=>window.removeEventListener('bonus-rules-changed',changed);
  },[]);
  function accept(next:ConfigData){
    setData(next);setRows(next.rows||[]);
    setParameters(Object.fromEntries(constantFields.map(field=>[field.key,next.parameters?.[field.key]==null?null:Number(next.parameters[field.key])])));
    setDirty(false);
  }
  useEffect(()=>{
    const id=++sequence.current;
    setLoading(true);setError('');setData(undefined);setRows([]);setDirty(false);
    const query=selection==null?'':`?${kind==='targets'?'quarter':'year'}=${encodeURIComponent(selection)}`;
    api<ConfigData>(`/bonus-config/${endpoint[kind]}${query}`).then(next=>{if(sequence.current===id)accept(next);}).catch(e=>{if(sequence.current===id)setError(e.message);}).finally(()=>{if(sequence.current===id)setLoading(false);});
    return()=>{sequence.current++;};
  },[kind,selection,revision]);
  const selected=kind==='targets'?data?.quarter:data?.year;
  const editable=!!data?.can_edit&&!busy&&!loading;
  function switchSelection(next:string|number){
    const change=()=>{setDirty(false);setSelection(next);};
    if(dirty)modal.confirm({title:'放弃尚未保存的修改？',content:'切换后将读取所选季度或年份的数据。',okText:'放弃并切换',cancelText:'继续编辑',onOk:change});else change();
  }
  function changed(){setDirty(true);setError('');}
  async function submit(inherit=false){
    if(!data||!editable)return;
    setError('');
    let payload:Record<string,unknown>={version:data.version};
    if(!inherit){
      if(kind==='targets')payload.rows=(rows as TargetRow[]).map(r=>({owner:r.BD姓名,target:r.直接营收目标}));
      if(kind==='services'){
        const entries=(rows as ServiceRow[]).map(r=>({service:r.所购服务.trim(),enabled:r.是否计入提成范围==='是'}));
        if(entries.some(r=>!r.service)||new Set(entries.map(r=>r.service)).size!==entries.length){setError('请填写奖金来源名称，且名称不能重复。');return;}
        payload.rows=entries;
      }
      if(kind==='constants'){
        if(constantFields.some(f=>parameters[f.key]==null)){setError('请填写全部公共常数。');return;}
        payload.parameters=parameters;
      }
    }
    setBusy(true);
    try{
      const path=`/bonus-config/${endpoint[kind]}${kind==='constants'?'':`/${selected}`}${inherit?'/inherit':''}`;
      const next=await api<ConfigData>(path,{method:inherit?'POST':'PUT',body:JSON.stringify(payload)});
      if(!alive.current)return;
      accept(next);ownSave.current=true;window.dispatchEvent(new Event('bonus-rules-changed'));ownSave.current=false;
      message.success(inherit?`${selected}${kind==='targets'?'目标':'年方案'}已沿袭，已保存并用于计算`:'已保存并同步计算与齿轮参数');
    }catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}
  }
  const empty=kind!=='constants'&&!rows.length;
  return <div className="bonus-source-editor" aria-label={kind==='targets'?'季度目标编辑器':kind==='services'?'年度奖金方案编辑器':'公共常数编辑器'}>
    <div className="bonus-config-toolbar"><Space wrap>
      {kind==='targets'&&<><span>季度</span><Select aria-label="目标季度" value={data?.quarter||selection} disabled={busy||loading} showSearch optionFilterProp="label" style={{width:155}} options={quarters.map(value=>({value,label:value}))} onChange={switchSelection}/></>}
      {kind==='services'&&<><span>年份</span><Select aria-label="方案年份" value={data?.year||selection} disabled={busy||loading} showSearch optionFilterProp="label" style={{width:155}} options={years.map(value=>({value,label:`${value}年`}))} onChange={switchSelection}/></>}
      <Tag color={data?.can_edit?'blue':'default'}>{data?.can_edit?'管理员可编辑':'只读查看'}</Tag>
      {dirty&&<Tag color="orange">有未保存修改</Tag>}
    </Space><Space>
      <Button disabled={busy||loading} onClick={()=>dirty?modal.confirm({title:'放弃草稿并重新加载？',onOk:()=>setRevision(v=>v+1)}):setRevision(v=>v+1)}>重新加载</Button>
      {!empty&&<Button type="primary" aria-label={kind==='targets'?'保存本季度目标':kind==='services'?'保存本年方案':'保存公共常数'} icon={<SaveOutlined/>} disabled={!editable||!dirty} loading={busy} onClick={()=>submit()}>{kind==='targets'?'保存本季度目标':kind==='services'?'保存本年方案':'保存公共常数'}</Button>}
    </Space></div>
    {error&&<Alert type="error" showIcon title={error}/>}
    {kind==='services'&&!!data?.missing_years?.length&&<Alert type="warning" showIcon title={`订单涉及的${data.missing_years.map(y=>`${y}年`).join('、')}尚未建立奖金方案`} description="表格按订单付款年份读取，其他年份的‘是’不会应用到这些订单。请选择缺失年份并沿袭上一年方案。" action={<Button onClick={()=>switchSelection(data.missing_years![0])} disabled={busy||loading}>前往{data.missing_years[0]}年</Button>}/>}

    {kind==='services'&&data?.exists&&!!data.missing_services?.length&&<Alert type="warning" showIcon title={`${data.year}年有${data.missing_services.length}个订单服务未配置，相关订单仍待设置规则`} description={<div>{data.missing_services.map(item=><Tag key={item.service}>{item.service}（{item.count}条）</Tag>)}<p>请在下方新增奖金来源并明确设置是或否；系统不会猜测名称相近的服务。</p></div>}/>}
    <Spin spinning={loading}>
      {empty?<div className="bonus-config-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`${selected||''}${kind==='targets'?'尚无营收目标':'年尚无奖金方案'}`}/>
        {data?.can_edit&&<Button className="bonus-inherit-button" aria-label={kind==='targets'?'沿袭上一季度目标':'沿袭上一年奖金方案'} icon={<PlusOutlined/>} disabled={!editable||!data.can_copy} loading={busy} onClick={()=>submit(true)}>{kind==='targets'?`沿袭${data.previous_quarter}全部BD目标`:`沿袭${data.previous_year}年奖金方案`}</Button>}
        {data&&!data.can_copy&&<span className="subtext">请先建立{kind==='targets'?data.previous_quarter:`${data.previous_year}年`}的配置</span>}
      </div>:kind==='targets'?<Table<TargetRow> size="small" bordered rowKey="BD姓名" pagination={false} dataSource={rows as TargetRow[]} columns={[
        {title:'BD姓名',dataIndex:'BD姓名',align:'center'}, {title:'季度',dataIndex:'季度',align:'center'},
        {title:'直接营收目标（元）',align:'center',render:(_,r)=><InputNumber aria-label={`${r.BD姓名}直接营收目标`} value={r.直接营收目标==null?null:Number(r.直接营收目标)} min={0.01} max={1000000000000} precision={2} disabled={!editable} placeholder="待填写" onChange={value=>{setRows(previous=>(previous as TargetRow[]).map(item=>item.BD姓名===r.BD姓名?{...item,直接营收目标:value}:item));changed();}}/>},
      ]}/>:kind==='services'?<>
        <p className="subtext">按订单付款年份匹配本年度方案；团队VIP沿用独立金额下限公式。全部来源在本页展示。</p>
        <Table<ServiceRow> size="small" bordered pagination={false} rowKey={r=>r.localKey||r.所购服务} dataSource={rows as ServiceRow[]} columns={[
          {title:'奖金来源／所购服务',render:(_,r)=>r.added?<Input aria-label="新增奖金来源名称" maxLength={200} value={r.所购服务} disabled={!editable} placeholder="例如：马克智能水电表" onChange={e=>{setRows(previous=>(previous as ServiceRow[]).map(item=>item.localKey===r.localKey?{...item,所购服务:e.target.value}:item));changed();}}/>:r.所购服务},
          {title:'是否计入提成范围',width:220,align:'center',render:(_,r)=><Select aria-label={`${r.所购服务||'新增来源'}是否计入提成范围`} style={{width:110}} value={r.是否计入提成范围} disabled={!editable} options={[{value:'是',label:'是'},{value:'否',label:'否'}]} onChange={value=>{setRows(previous=>(previous as ServiceRow[]).map(item=>(r.localKey?item.localKey===r.localKey:item.所购服务===r.所购服务)?{...item,是否计入提成范围:value}:item));changed();}}/>},
        ]}/>
        {data?.can_edit&&<Button block type="dashed" aria-label="新增奖金来源" icon={<PlusOutlined/>} className="bonus-add-service" disabled={!editable} onClick={()=>{setRows(previous=>[...previous,{所购服务:'',是否计入提成范围:'是',added:true,localKey:crypto.randomUUID()}]);changed();}}>新增奖金来源</Button>}
      </>:<>
        <p className="subtext">与蓝色、紫色齿轮共用同一份参数；保存后适用于全部BD和全部季度。</p>
        <Table size="small" bordered rowKey="key" pagination={false} dataSource={constantFields} columns={[
          {title:'参数',dataIndex:'label'},
          {title:'当前生效值',width:260,render:(_,field)=><InputNumber aria-label={`公共常数${field.label}`} value={parameters[field.key]} min={0} max={field.kind==='rate'?100:1000000000000} precision={field.kind==='rate'?4:2} disabled={!editable} addonAfter={field.kind==='rate'?'%':'元'} onChange={value=>{setParameters(p=>({...p,[field.key]:value}));changed();}}/>},
          {title:'同步位置',width:200,render:(_,field)=>field.key==='vip_minimum'?'⑧ 是否计发提成':'⑮ 适用提点'},
        ]}/>
      </>}
    </Spin>
  </div>;
}
