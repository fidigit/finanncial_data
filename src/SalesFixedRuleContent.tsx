import { Descriptions, InputNumber, Select } from 'antd';
export type RuleParameter = { key: string; label: string; sample: number | boolean; kind: 'amount' | 'rate' | 'boolean' };
export const RULE_PARAMETERS: Record<string, RuleParameter[]> = {
  S: [{ key:'vip_minimum', label:'团队VIP金额下限（元）', sample:1680, kind:'amount' }],
  J: [], K: [],
  T: [{ key:'include_ineligible', label:'累计口径', sample:true, kind:'boolean' }],
  X: [
    { key:'threshold', label:'同BD季度奖金计算基数合计门槛（元）', sample:30000, kind:'amount' },
    { key:'renewal_rate', label:'续费提点（%）', sample:3, kind:'rate' },
    { key:'self_rate', label:'自拓目标内提点（%）', sample:10, kind:'rate' },
    { key:'self_excess', label:'自拓超额提点（%）', sample:15, kind:'rate' },
    { key:'market_rate', label:'市场推荐目标内提点（%）', sample:8, kind:'rate' },
    { key:'market_excess', label:'市场推荐超额提点（%）', sample:13, kind:'rate' },
    { key:'partner_rate', label:'协会/合伙人目标内提点（%）', sample:5, kind:'rate' },
    { key:'partner_excess', label:'协会/合伙人超额提点（%）', sample:8, kind:'rate' },
  ],
};
export type RuleDraft = Record<string, number | boolean | null>;
export type RuleInputs = {
  owner:string; quarter:string; period:Record<string,string|number|boolean|null>; period_version:number;
  variables:Record<string,unknown>; can_edit:boolean;
  trace?: { order_amount:string; enabled:boolean|null; allocation_ratio:string|null; bonus_basis:string|null; revenue_total:string|null; rate_display:string; bonus:string|null; calculation:Record<string,unknown> };
};
export const showValue = (value:unknown) => value == null ? '待配置' : typeof value==='boolean' ? value?'是':'否' : String(value);

export function ParameterInput({ field, draft, onChange, disabled, compact=false, onEnter }: { field:RuleParameter; draft:RuleDraft; onChange:(key:string,value:number|boolean|null)=>void; disabled:boolean; compact?:boolean; onEnter?:(key:string)=>void }) {
  const value=draft[field.key];
  return <label className={compact?'sales-fixed-parameter compact':'sales-fixed-parameter'}>
    <span>{field.label}</span>
    {field.kind==='boolean' ? <Select aria-label={field.label} value={typeof value==='boolean'?value:undefined} disabled={disabled} options={[{value:true,label:'包含不计提订单（原表口径）'},{value:false,label:'仅计提订单'}]} onChange={next=>onChange(field.key,next)} /> :
      <InputNumber aria-label={field.label} value={typeof value==='number'?value:null} controls={false} min={0} max={field.kind==='rate'?100:1000000000000} precision={field.kind==='rate'?4:2} disabled={disabled} placeholder="待配置" onChange={next=>onChange(field.key,next==null?null:Number(next))} onPressEnter={()=>onEnter?.(field.key)} />}
  </label>;
}
const splitExplanation = <>
  <p>按<strong>订单号＋BD姓名</strong>查询【拆分订单表】，读取本人分摊金额和本订单全部BD分摊金额合计。</p>
  <div className="sales-fixed-equation">分摊比例 ＝ 本人分摊金额 ÷ 订单分摊总金额</div>
  <p>无共享信息且无拆分记录：取100%。已声明共享但金额不完整、总金额不为正或本人金额超过总额：待配置。</p>
  <p>已有单笔人工确认比例时，优先使用确认比例。</p>
</>;
const basisExplanation = <>
  <p>先按订单号、BD姓名读取拆分表的本人金额和订单分摊总金额。</p>
  <div className="sales-fixed-equation">有有效拆分：奖金计算基数 ＝ 订单金额 ×（本人分摊金额 ÷ 订单分摊总金额），四舍五入保留2位小数。</div>
  <p>无共享且无拆分：取订单金额，四舍五入保留2位。拆分依据不完整：待配置。</p>
  <p>有人工确认比例时，改用该比例乘订单金额；有人工确认基数时，以人工基数为准。</p>
</>;
function eligibilityExplanation(minimum:unknown) {
  return <p>先判定计提资格：团队VIP订单金额≥{showValue(minimum)}元为“是”，低于为“否”；其他服务按名称查询【付款年份对应的奖金方案】的“是否计入提成范围”。查不到或异常为Check／待配置；单笔人工确认优先。</p>;
}
function cumulativeExplanation(minimum:unknown) {
  return <>
    <p>同一BD、同一季度，按完整付款时间从早到晚排列；时间相同时按来源行号排列。</p>
    <div className="sales-fixed-equation">截至本单累计营收 ＝ 前面各笔及本笔“计入金额”之和。</div>
    <p>每笔计入金额：有拆分则用订单金额×本人分摊金额÷订单分摊总金额，并逐笔四舍五入到2位；无共享且无拆分则取订单金额并保留2位；人工确认比例、基数优先。</p>
    <p>选择“包含不计提订单”：上述基数全部累计。选择“仅计提订单”：先按下述资格规则判断，只累计结果为“是”的订单。</p>
    {eligibilityExplanation(minimum)}
    <p>源头金额、时间或当前口径所需资格未确认时，保留待核对。先计算完整季度，再筛选、分页，搜索不会改变累计值。</p>
  </>;
}

export function SalesFixedRuleContent({ column, inputs, draft, onChange, disabled }: { column:string; inputs?:RuleInputs; draft:RuleDraft; onChange:(key:string,value:number|boolean|null)=>void; disabled:boolean }) {
  const fields=RULE_PARAMETERS[column] || [];
  const field=(key:string,compact=false)=><ParameterInput field={fields.find(item=>item.key===key)!} draft={draft} onChange={onChange} disabled={disabled} compact={compact} />;
  const calc=inputs?.trace?.calculation;
  if(column==='S') return <div className="sales-eligibility-rule" aria-label="是否计发提成完整计算规则">
    <strong>如果 所购服务 = “团队VIP”：</strong>
    <div className="sales-eligibility-branch">订单金额 ≥ {field('vip_minimum',true)} → “是”</div>
    <div className="sales-eligibility-branch">订单金额 &lt; 同一金额下限 → “否”</div>
    <strong>否则：</strong><div className="sales-eligibility-branch">按所购服务查询【付款年份对应的奖金方案】的“是否计入提成范围”，返回“是”或“否”。</div>
    <div className="sales-eligibility-fallback">查不到规则或输入异常 → “Check（待配置）”</div>
    <p className="subtext">单笔人工确认优先。仅金额下限可填写，判断和查表流程固定。</p>
  </div>;
  if(column==='J') return <div className="sales-fixed-rule" aria-label="分摊比例完整计算规则">
    {splitExplanation}
    <Descriptions bordered size="small" column={1} items={[
      {key:'amount',label:'当前本人分摊金额',children:showValue(inputs?.variables.split_amount)},
      {key:'total',label:'当前订单分摊总金额',children:showValue(inputs?.variables.split_total)},
      {key:'ratio',label:'当前结果',children:inputs?.trace?.allocation_ratio==null?'待配置':`${Number(inputs.trace.allocation_ratio)*100}%`},
    ]} />
    <p className="subtext">本列没有额外规则参数。分摊金额属于输入源头，在拆分订单数据中维护；此处不重复修改。</p>
  </div>;
  if(column==='K') return <div className="sales-fixed-rule" aria-label="奖金计算基数完整计算规则">
    {basisExplanation}<p className="subtext">乘除规则与保留2位小数固定，本列没有额外规则参数。</p>
    <Descriptions bordered size="small" column={1} items={[
      {key:'order',label:'当前订单金额',children:showValue(inputs?.trace?.order_amount)},
      {key:'basis',label:'当前奖金计算基数',children:showValue(inputs?.trace?.bonus_basis)},
    ]} />
  </div>;
  if(column==='T') return <div className="sales-fixed-rule" aria-label="累计营收完整计算规则">
    {cumulativeExplanation(inputs?.period.vip_minimum)}
    {field('include_ineligible')}
    <p className="subtext">只开放已有的累计口径选项，人员范围、季度范围、排序、分摊及逐笔取整规则固定。</p>
  </div>;
  return <div className="sales-fixed-rule" aria-label="适用提点完整计算规则">
    <strong>① 计提资格与起提门槛</strong>
    {eligibilityExplanation(inputs?.period.vip_minimum)}
    <p>资格为“否” → 提点0%；资格未知 → 待配置。</p>
    <p>同BD本季度所有计入基数合计低于下方门槛 → 提点0%；达到门槛后再判断购买性质和渠道。</p>
    {field('threshold')}
    <p>季度合计的每笔基数＝订单金额×按订单号、BD查得的拆分比例，并逐笔保留2位；无拆分时取订单金额。是否包含不计提订单，沿用“累计营收”中的口径设置。</p>
    <strong>② 续费</strong><p>购买性质为续费，使用下方续费提点，不走新客的目标分档。</p>{field('renewal_rate')}
    <strong>③ 首购／新客：先确定渠道</strong>
    <p>存在协会／合伙人推荐 → 协会／合伙人；否则，来自市场 → 市场推荐；否则 → 自拓。客户推荐但计奖渠道未确认时，保留待配置。</p>
    <strong>④ 查询季度目标，再比较累计金额</strong>
    <p>按BD姓名和季度从【奖金汇总表】读取直接营收目标；未配置目标时保留待配置。当前目标：<b>{showValue(calc?.target)}</b>元。</p>
    <p>累计金额按同BD、同季度付款顺序，将订单金额×拆分比例逐笔保留2位后合计。累计金额≤目标取目标内提点，严格超过目标取超额提点。</p>
    <table className="sales-fixed-rate-table"><thead><tr><th>成单渠道</th><th>目标内提点</th><th>超额提点</th></tr></thead><tbody>
      <tr><th>自拓</th><td>{field('self_rate',true)}</td><td>{field('self_excess',true)}</td></tr>
      <tr><th>市场推荐</th><td>{field('market_rate',true)}</td><td>{field('market_excess',true)}</td></tr>
      <tr><th>协会／合伙人</th><td>{field('partner_rate',true)}</td><td>{field('partner_excess',true)}</td></tr>
    </tbody></table>
    <strong>⑤ 跨目标订单分两段</strong>
    <div className="sales-fixed-equation">目标内金额＝本单基数与“目标－（截至本单累计－本单基数）”非负部分的较小值；超额金额＝本单基数－目标内金额。</div>
    <p>两部分均大于0时显示两段提点；奖金分别乘以上表对应提点后相加。续费仍按续费提点；无效或缺失输入不当作0。</p>
    <p className="subtext">本列仅开放1个金额门槛和7个提点。VIP门槛由“是否计发提成”维护，季度目标、推荐信息及订单金额属于源头数据。</p>
  </div>;
}
