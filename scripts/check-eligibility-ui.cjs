const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
(async()=>{
 const base='http://127.0.0.1:18081';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.goto(base);
  await page.getByLabel('账号',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('Demo2026!');
  await page.getByRole('button',{name:/登录工作台/}).click();
  const sales=page.locator('.commission-data-card').first();await sales.locator('.sales-source-entries button').first().waitFor();
  assert.deepEqual(await sales.locator('.sales-source-entries button').allTextContents(),['奖金汇总表','奖金方案','C 订单号','Z 是否适用分段计算']);
  const get=async query=>(await (await page.request.get(base+'/api/commission-data?category=sales&'+query)).json()).rows;
  const records=await get('page_size=100');
  const original=records.find(r=>r.enabled===true&&Number(r.bonus)>0&&r.confirmation.enabled==null);
  assert(original,'Need a formula-eligible source order');
  const search=sales.getByLabel('搜索提成确认明细',{exact:true});
  await search.fill(original.order_no);const load=page.waitForResponse(r=>r.url().includes('/api/commission-data?')&&r.url().includes('search='));await search.press('Enter');await load;
  const choice=sales.getByRole('combobox',{name:`修改sales第${original.row_id}行是否计发提成`,exact:true});await choice.waitFor();
  async function choose(label){
   await choice.click();
   const options=page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option');
   assert.deepEqual(await options.allTextContents(),['是','否']);
   const save=page.waitForResponse(r=>r.url().endsWith('/commission-data/eligibility')&&r.request().method()==='PUT');
   const refreshed=page.waitForResponse(r=>r.url().includes('/api/commission-data?')&&r.url().includes('category=sales'));
   await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:new RegExp('^'+label+'$')}).click();
   assert((await save).ok());await refreshed;
   return (await get('search='+encodeURIComponent(original.order_no))).find(r=>r.record_key===original.record_key);
  }
  const no=await choose('否');assert.equal(no.enabled,false);assert.equal(Number(no.bonus),0);assert.equal(no.bonus_basis,original.bonus_basis);
  const yes=await choose('是');assert.equal(yes.enabled,true);assert.equal(yes.bonus,original.bonus);
  const restored=await page.request.put(base+'/api/commission-data/eligibility',{data:{record_key:yes.record_key,version:yes.version,enabled:null}});
  assert(restored.ok());
  await page.screenshot({path:'data/ui-qa-20261116/eligibility.png'});
  console.log('PASS: two source entries hidden, Z retained, eligibility only offers yes/no, both recalculate bonus.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
