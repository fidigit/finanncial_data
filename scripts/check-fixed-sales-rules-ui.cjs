const assert=require('node:assert/strict');
const{chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
(async()=>{
 const base=process.env.QA_URL||'http://127.0.0.1:18081/';if(new URL(base).port!=='18081')throw Error('Mutating checks require isolated QA port');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.getByLabel('账号',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('Demo2026!');await page.getByRole('button',{name:/登录工作台/}).click();
  const sales=page.locator('.commission-data-card').first();await sales.getByRole('button',{name:'分摊比例公式',exact:true}).waitFor();
  async function api(path){const response=await page.request.get(new URL('/api'+path,base).href);assert(response.ok(),await response.text());return response.json();}
  const defs=(await api('/sales-formulas/definitions')).definitions;assert(defs.every(d=>d.editor_mode!=='expression'));
  const samples=await api('/commission-data?'+new URLSearchParams({category:'sales',owner:'杨红星',search:'团队VIP',page_size:'100'}));
  const chosen=samples.rows.find(r=>Number(r.order_amount)===1680&&r.purchase_type==='续费'&&!Object.keys(r.confirmation).length);assert(chosen&&chosen.enabled&&Number(chosen.bonus)>0);
  const query={owner:chosen.owner,quarter:chosen.quarter,record:chosen.record_key};
  async function config(){return api('/sales-formulas/inputs?'+new URLSearchParams(query));}
  async function row(){const result=await api('/commission-data?'+new URLSearchParams({category:'sales',owner:chosen.owner,search:chosen.order_no}));return result.rows.find(r=>r.record_key===chosen.record_key);}
  const before=await row();
  await sales.getByLabel('搜索提成确认明细').fill(chosen.order_no);const loaded=page.waitForResponse(r=>r.url().includes('/commission-data?')&&r.url().includes('search='+chosen.order_no));await sales.getByLabel('搜索提成确认明细').press('Enter');await loaded;
  async function open(title){await sales.getByRole('button',{name:title+'公式',exact:true}).click();const popup=page.getByLabel(title+'公式内容');await popup.waitFor();await page.waitForFunction(()=>!document.querySelector('.sales-formula-viewport .ant-spin-spinning'));assert.deepEqual(await popup.evaluate(el=>[el.offsetWidth,el.offsetHeight]),[500,400]);assert.equal(await popup.locator('textarea').count(),0);return popup;}
  async function close(){await page.mouse.click(1300,100);}
  for(const [title,count,key]of[['分摊比例',0,'J'],['奖金计算基数',0,'K'],['累计营收',0,'T'],['适用提点（分段提点）',8,'X']]){
    const popup=await open(title);assert.equal(await popup.getByRole('spinbutton').count(),count);
    const text=await popup.innerText();assert(text.includes('订单金额')||text.includes('本人分摊金额'));
    if(key==='J')assert(text.includes('订单号')&&text.includes('100%'));
    if(key==='K')assert(text.includes('四舍五入')&&text.includes('2位'));
    if(key==='X')assert(text.includes('2025年奖金方案')&&text.includes('季度目标')&&text.includes('协会')&&text.includes('跨目标'));
    await page.screenshot({path:`docs/sales-fixed-${key}.png`});await close();
  }
  console.log('PASS: all four expanded rules, no code editors, only allowed parameters.');
  const t=await open('累计营收');await t.getByLabel('累计口径',{exact:true}).click();await page.locator('.ant-select-dropdown:visible').getByText('仅计提订单',{exact:true}).click();
  let saved=page.waitForResponse(r=>r.url().endsWith('/parameters/T')&&r.request().method()==='PUT');await t.getByRole('button',{name:'保存参数',exact:true}).click();assert((await saved).ok());assert.equal((await config()).period.include_ineligible,false);
  saved=page.waitForResponse(r=>r.url().endsWith('/parameters/T')&&r.request().method()==='PUT');await t.getByRole('button',{name:'恢复默认参数并保存',exact:true}).click();assert((await saved).ok());assert.equal((await config()).period.include_ineligible,true);assert.equal((await row()).bonus,before.bonus);await close();
  const x=await open('适用提点（分段提点）');const rate=x.getByLabel('续费提点（%）',{exact:true});await rate.fill('6');
  let preview=page.waitForResponse(r=>r.url().endsWith('/parameters/X/preview'));await x.getByRole('button',{name:/试\s*算/}).click();assert((await(await preview).json()).bonus_changed_count>0);assert.equal((await row()).bonus,before.bonus);
  saved=page.waitForResponse(r=>r.url().endsWith('/parameters/X')&&r.request().method()==='PUT');await x.getByRole('button',{name:'保存参数',exact:true}).click();assert((await saved).ok());assert.equal(Number((await row()).bonus),Number(before.bonus)*2);await close();
  await sales.getByRole('button',{name:'适用提点（分段提点）参数配置',exact:true}).click();const purple=page.getByLabel('适用提点（分段提点）参数输入区');await purple.getByLabel('续费提点（%）',{exact:true}).waitFor();await page.waitForFunction(()=>{const e=document.querySelector('.sales-parameter-viewport input[aria-label="续费提点（%）"]');return e&&Number(e.value)===6;});assert.deepEqual(await purple.evaluate(e=>[e.offsetWidth,e.offsetHeight]),[200,150]);await close();
  await open('适用提点（分段提点）');saved=page.waitForResponse(r=>r.url().endsWith('/parameters/X')&&r.request().method()==='PUT');await x.getByRole('button',{name:'恢复默认参数并保存',exact:true}).click();assert((await saved).ok());assert.equal((await row()).bonus,before.bonus);await close();
  const s=await open('是否计发提成');const minimum=s.getByLabel('团队VIP金额下限（元）',{exact:true});await minimum.fill('2000');saved=page.waitForResponse(r=>r.url().endsWith('/parameters/S')&&r.request().method()==='PUT');await s.getByRole('button',{name:'保存参数',exact:true}).click();assert((await saved).ok());assert.equal((await row()).enabled,false);saved=page.waitForResponse(r=>r.url().endsWith('/parameters/S')&&r.request().method()==='PUT');await s.getByRole('button',{name:'恢复1680元并保存',exact:true}).click();assert((await saved).ok());assert.equal((await row()).bonus,before.bonus);await close();
  for(const width of[1280,1440]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(200);assert.equal(await sales.locator('col').count(),19);assert(await sales.evaluate(el=>el.querySelector('table').getBoundingClientRect().right<=el.querySelector('.bonus-fit-host').getBoundingClientRect().right+2));}
  assert.equal(await sales.locator('.sales-blue-gear').count(),5);assert.equal(await sales.locator('.sales-parameter-gear').count(),2);assert.deepEqual(errors,[]);assert.equal((await api('/health')).version,'0.0.4');
  console.log('PASS: cumulative scope saves/restores; rate trial has no writes; blue rate save changes bonus and syncs purple; S retained; 19 columns fit; version unchanged. Only QA data changed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
