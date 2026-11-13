const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
(async()=>{
 const base=process.env.QA_URL||'http://127.0.0.1:18081/';
 if(new URL(base).port!=='18081')throw Error('Mutation requires isolated QA port 18081');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.getByLabel('账号',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('Demo2026!');await page.getByRole('button',{name:/登录工作台/}).click();
  const sales=page.locator('.commission-data-card').first();await sales.locator('.sales-blue-gear').first().waitFor();
  const api=async path=>{const response=await page.request.get(new URL('/api'+path,base).href);assert(response.ok(),await response.text());return response.json()};
  const snapshot=await api('/commission-data?category=sales&page_size=100');
  const row=snapshot.rows[0];assert.equal(row.service,'收费系统户数');assert.equal(row.enabled,true);const renewal=snapshot.rows.find(r=>r.enabled===true&&r.purchase_type==='续费'&&r.bonus!==null);assert(renewal,'At least one eligible renewal has a computed bonus');
  const owners=[...new Map(snapshot.rows.map(r=>[r.owner,r])).values()];assert(owners.length>1);
  const contexts=owners.map(r=>new URLSearchParams({owner:r.owner,quarter:r.quarter,record:r.record_key}));
  for(const query of contexts){const config=await api('/sales-formulas/inputs?'+query);assert.equal(config.parameter_scope,'global');assert.equal(Number(config.period.vip_minimum),1680);}
  await sales.locator('.sales-source-entries button').nth(2).click();
  const source=page.locator('.sales-source-modal');await source.getByText('实际生效规则 · 只读查看',{exact:true}).waitFor();
  const active=await api('/sales-workspace/sources/services');assert.equal(active.active,true);assert.equal(active.rows.length,42);assert.equal(active.rows.find(r=>r['所购服务']==='收费系统户数')['是否计入提成范围'],'是');
  await page.locator('.sales-source-modal-wrap .ant-modal-close').click();
  const gear=sales.getByRole('button',{name:'是否计发提成公式',exact:true});await gear.click();
  const formula=page.getByLabel('是否计发提成公式内容',{exact:true});await formula.waitFor();await formula.getByText(/生效范围：全部BD · 全部季度/).waitFor();await formula.getByText(/计算样例：/).waitFor();
  const input=formula.getByRole('spinbutton',{name:'团队VIP金额下限（元）',exact:true});await input.fill('2000');
  const previewResponse=page.waitForResponse(r=>r.url().endsWith('/parameters/S/preview')&&r.request().method()==='POST');await formula.getByRole('button',{name:/试\s*算/}).click();assert((await previewResponse).ok());
  for(const query of contexts)assert.equal(Number((await api('/sales-formulas/inputs?'+query)).period.vip_minimum),1680);
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/parameters/S')&&r.request().method()==='PUT');await formula.getByRole('button',{name:'保存参数',exact:true}).click();assert((await saveResponse).ok());
  for(const query of contexts)assert.equal(Number((await api('/sales-formulas/inputs?'+query)).period.vip_minimum),2000);
  await gear.click();await formula.waitFor({state:'hidden'});
  const purple=sales.getByRole('button',{name:'是否计发提成参数配置',exact:true});await purple.click();const params=page.getByLabel('是否计发提成参数输入区');await params.getByText(/全部BD · 全部季度/).waitFor();await page.waitForFunction(()=>Number(document.querySelector('.sales-parameter-viewport input')?.value)===2000);await purple.click();
  await gear.click();await formula.waitFor();await page.waitForFunction(()=>!document.querySelector('.sales-formula-viewport .ant-spin-spinning'));
  const resetResponse=page.waitForResponse(r=>r.url().endsWith('/parameters/S')&&r.request().method()==='PUT');await formula.getByRole('button',{name:'恢复1680元并保存'}).click();assert((await resetResponse).ok());
  for(const query of contexts)assert.equal(Number((await api('/sales-formulas/inputs?'+query)).period.vip_minimum),1680);
  await page.screenshot({path:'docs/global-bonus-rule-popup.png'});assert.deepEqual(errors,[]);
  console.log('PASS: active workbook plan (43 source rows / 42 unique services), first order now eligible, global labels, global preview without write, cross-BD parameter save, purple/blue consistency, global restore. Isolated database only.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
