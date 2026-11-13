import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Descriptions, Modal, Popover, Space, Spin, Table, Tag } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { api } from './api';
import type { SalesContext } from './SalesConfiguration';
import { ParameterInput, RULE_PARAMETERS, SalesFixedRuleContent, showValue } from './SalesFixedRuleContent';
import type { RuleDraft, RuleInputs } from './SalesFixedRuleContent';
const COLUMNS:Record<string,string>={'是否计发提成':'S','分摊比例':'J','奖金计算基数':'K','累计营收':'T','适用提点（分段提点）':'X'};
const RESULT_FIELD:Record<string,string>={S:'enabled',J:'allocation_ratio',K:'bonus_basis',T:'revenue_total',X:'rate_display'};
type Trial={valid:boolean;total:number;changed_count:number;bonus_changed_count:number;new_error_count:number;errors:{row_id:number;column:string;message:string}[];rows:{row_id:number;owner:string;before:Record<string,unknown>;after:Record<string,unknown>}[]};
function toDraft(column:string,period:RuleInputs['period']):RuleDraft{
  return Object.fromEntries((RULE_PARAMETERS[column]||[]).map(field=>[field.key,field.kind==='boolean'?period[field.key]===true:period[field.key]==null?null:Number(period[field.key])]));
}
export function SalesHeaderConfiguration({title,context,onSaved}:{title:string;context?:SalesContext;onSaved:()=>void}){
  const {message}=App.useApp();
  const column=COLUMNS[title],fields=RULE_PARAMETERS[column]||[];
  const [formulaOpen,setFormulaOpen]=useState(false),[parametersOpen,setParametersOpen]=useState(false),[detail,setDetail]=useState(false);
  const [inputs,setInputs]=useState<RuleInputs>(),[draft,setDraft]=useState<RuleDraft>({}),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const [revision,setRevision]=useState(0),[busy,setBusy]=useState(false),[action,setAction]=useState(''),[trial,setTrial]=useState<Trial>(),[applied,setApplied]=useState(false);
  const active=formulaOpen||parametersOpen||detail;
  useEffect(()=>{const changed=()=>setRevision(v=>v+1);window.addEventListener('bonus-rules-changed',changed);return()=>window.removeEventListener('bonus-rules-changed',changed);},[]);
  const contextId=JSON.stringify(context);const contextRef=useRef(contextId);contextRef.current=contextId;
  useEffect(()=>{
    if(!active||!context)return;
    let alive=true;setLoading(true);setError('');setInputs(undefined);setTrial(undefined);setApplied(false);
    api<RuleInputs>('/sales-formulas/inputs?'+new URLSearchParams({owner:context.owner,quarter:context.quarter,record:context.record_key})).then(result=>{
      if(alive){setInputs(result);setDraft(toDraft(column,result.period));}
    }).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});
    return()=>{alive=false;};
  },[active,revision,column,context?.owner,context?.quarter,context?.record_key]);
  const scope='全部BD · 全部季度';
  const example=context?`${context.owner} · ${context.quarter}`:'暂无订单样例';
  const editable=!!inputs?.can_edit&&!busy&&!loading;
  function change(key:string,value:number|boolean|null){setDraft(previous=>({...previous,[key]:value}));setTrial(undefined);setApplied(false);}
  async function run(kind:'preview'|'save'|'reset',singleKey?:string){
    if(!context||!inputs?.can_edit||busy||loading||!fields.length)return;
    const selected=singleKey?fields.filter(field=>field.key===singleKey):fields;
    const parameters=Object.fromEntries(selected.map(field=>[field.key,kind==='reset'?field.sample:draft[field.key]]));
    for(const field of selected){
      const value=parameters[field.key];
      if(field.kind==='boolean'?typeof value!=='boolean':typeof value!=='number'||!Number.isFinite(value)||value<0||(field.kind==='rate'&&value>100)){
        setError(`请填写有效的${field.label}，空白不会覆盖已保存参数`);return;
      }
    }
    const expectedContext=contextRef.current;
    setBusy(true);setAction(kind);setError('');
    try{
      const body={owner:context.owner,quarter:context.quarter,record:context.record_key,version:inputs.period_version,parameters,note:`${singleKey?'紫色参数':'蓝色固定公式'}：${title}${kind==='reset'?'恢复默认':'设置参数'}`};
      if(kind==='preview'){
        const preview=await api<Trial>(`/sales-formulas/parameters/${column}/preview`,{method:'POST',body:JSON.stringify(body)});if(contextRef.current===expectedContext){setTrial(preview);setApplied(false);}
      }else{
        const result=await api<{period:RuleInputs['period'];version:number;preview:Trial}>(`/sales-formulas/parameters/${column}`,{method:'PUT',body:JSON.stringify(body)});
        if(contextRef.current===expectedContext){setInputs(previous=>previous&&({...previous,period:result.period,period_version:result.version}));setDraft(toDraft(column,result.period));setTrial(result.preview);setApplied(true);}onSaved();
        message.success(singleKey?'参数已保存并重新计算':column==='S'?(kind==='reset'?'团队VIP金额下限已恢复为1680元':'团队VIP金额下限已保存并重新计算'):kind==='reset'?'默认参数已恢复并重新计算':`${title}参数已保存并重新计算`);
        try{const latest=await api<RuleInputs>('/sales-formulas/inputs?'+new URLSearchParams({owner:context.owner,quarter:context.quarter,record:context.record_key}));if(contextRef.current===expectedContext)setInputs(latest);}catch{if(contextRef.current===expectedContext)setError('参数已保存；计算详情读取失败，请重新加载。');}
      }
    }catch(e){if(contextRef.current===expectedContext){setError((e as Error).message);setTrial(undefined);}}finally{setBusy(false);setAction('');}
  }
  if(!column)return <>{title}</>;
  const calc=inputs?.trace?.calculation;
  const hidden=[
    ['当季度目标',calc?.target,'按BD、季度从已配置目标读取；用于目标比较及跨目标分段。'],
    ['所购服务是否计发提成',calc?.service_eligible==null?null:calc.service_eligible?'是':'否','完整服务规则判断结果；人工确认优先。'],
    ['分段提成计算结果',calc?.segmented_bonus,'目标内金额×目标内提点＋超额金额×超额提点。'],
    ['累计是否超过目标',calc?.over_target==null?null:calc.over_target?'是':'否','按累计营收严格大于季度目标判断。'],
    ['同BD季度基数合计',calc?.quarter_total,'本季度逐单基数合计，沿用当前累计口径，用于起提判断。'],
    ['成单渠道',({self:'自拓',market:'市场推荐',partner:'协会/合伙人',pending:'待确认'} as Record<string,string>)[String(calc?.channel)],'协会/合伙人优先，其次市场推荐，否则自拓；来源不明待确认。'],
    ['普通提成计算结果',calc?.ordinary_bonus,'本单奖金计算基数×当前适用提点。'],
  ];
  const content=<><p className="subtext">生效范围：{scope}。计算样例：{example}。固定公式统一使用，单笔人工确认仍优先。</p>
    {error&&<Alert type="error" title={error} showIcon/>}
    {!context&&<Alert type="info" title="暂无可见订单；可先查看固定计算规则。"/>}
    <Spin spinning={loading}><SalesFixedRuleContent column={column} inputs={inputs} draft={draft} onChange={change} disabled={!editable}/></Spin>
  </>;
  return <div className="formula-column-title"><span>{title}</span><div className="sales-header-gears">
    {(column==='S'||column==='X')&&<Popover trigger="click" open={parametersOpen} onOpenChange={setParametersOpen} placement="bottomRight" autoAdjustOverflow={false} arrow={false} classNames={{root:'sales-parameter-popover'}} styles={{container:{padding:0}}} content={<div className="sales-parameter-viewport" aria-label={`${title}参数输入区`}>
      <div className="sales-parameter-scope">{scope} · Enter保存</div>{error&&<span className="sales-parameter-error">{error}</span>}<Spin spinning={loading}>{fields.map(field=><ParameterInput key={field.key} field={field} draft={draft} onChange={change} disabled={!editable} onEnter={key=>run('save',key)}/>)}</Spin>
    </div>}><button type="button" disabled={!context} className="sales-parameter-gear" aria-label={`${title}参数配置`} title={`参数配置：${scope}。输入后Enter保存。`}><SettingOutlined/></button></Popover>}
    <Popover trigger="click" open={formulaOpen} onOpenChange={setFormulaOpen} placement="bottomRight" autoAdjustOverflow={false} arrow={false} classNames={{root:'sales-formula-popover'}} styles={{container:{padding:0}}} content={<div className="sales-formula-viewport" aria-label={`${title}公式内容`}>
      <div className="sales-rule-heading"><strong>{title} · 完整计算规则</strong><Tag color="purple">固定公式</Tag></div>{content}
      <Space wrap className="sales-rule-actions">
        {!!fields.length&&<><Button size="small" onClick={()=>run('preview')} loading={busy&&action==='preview'} disabled={!editable}>试算</Button><Button size="small" type="primary" onClick={()=>run('save')} loading={busy&&action==='save'} disabled={!editable}>保存参数</Button><Button size="small" onClick={()=>run('reset')} disabled={!editable}>{column==='S'?'恢复1680元并保存':'恢复默认参数并保存'}</Button></>}
        <Button size="small" onClick={()=>setRevision(value=>value+1)} disabled={busy}>重新加载</Button>
      </Space>
      {!!fields.length&&!inputs?.can_edit&&!loading&&<p className="subtext">当前账号仅可查看；管理员可设置参数。</p>}
      {trial&&<div className="sales-rule-trial"><Alert type={trial.valid?'success':'error'} title={trial.valid?`${applied?'已生效':'试算'}：${trial.changed_count}/${trial.total}条记录变化，其中${trial.bonus_changed_count}条奖金变化`:`发现${trial.new_error_count}处错误，不能保存`} description={trial.errors.map(item=>`来源行${item.row_id}：${item.message}`).join('；')||(applied?'已保存并用于表格与导出。':'试算不写入配置；保存参数后生效。')}/><Table size="small" rowKey="row_id" pagination={false} columns={[
        {title:'BD / 行',render:(_,row:Trial['rows'][number])=>`${row.owner} / ${row.row_id}`},
        {title:'本列：原值 → 新值',render:(_,row:Trial['rows'][number])=>`${showValue(row.before[RESULT_FIELD[column]])} → ${showValue(row.after[RESULT_FIELD[column]])}`},
        {title:'奖金：原值 → 新值',render:(_,row:Trial['rows'][number])=>`${showValue(row.before.bonus)} → ${showValue(row.after.bonus)}`},
      ]} dataSource={trial.rows}/></div>}
      <Button size="small" type="link" onClick={()=>{setFormulaOpen(false);setParametersOpen(false);setDetail(true);}}>公式详情 / 隐藏变量</Button>
    </div>}><button type="button" className="sales-blue-gear" aria-label={`${title}公式`} title="查看完整固定公式与可调参数（蓝色）"><SettingOutlined/></button></Popover>
  </div>
    <Modal title={`${title} · 公式详情`} open={detail} onCancel={()=>setDetail(false)} footer={<Button onClick={()=>setDetail(false)}>关闭</Button>} width={680}>
      <p className="subtext">生效范围：{scope}。计算样例：{example}。下方展示已保存参数和自动计算结果，不在详情中编辑。</p>{error&&<Alert type="error" title={error}/>}<Spin spinning={loading}><SalesFixedRuleContent column={column} inputs={inputs} draft={inputs?toDraft(column,inputs.period):{}} onChange={()=>{}} disabled/></Spin><p className="subtext">下面是自动计算的中间结果，不是额外配置项。</p><Descriptions bordered size="small" column={1} items={hidden.map(([label,value,usage])=>({key:String(label),label:String(label),children:<>{showValue(value)}<div className="subtext">{String(usage)}</div></>}))}/>
    </Modal>
  </div>;
}
