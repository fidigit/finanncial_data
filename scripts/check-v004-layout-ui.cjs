const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_PATH || 'playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  // Browser-only fixture: exercise meeting cell layout without adding business records.
  await page.route('**/api/meetings?*',route=>route.fulfill({json:{can_edit:false,total:1,rows:[{id:'layout-fixture',version:0,owner:'布局测试',meeting_date:'2026-11-12',meeting_type:'交流会',location:'测试地点',companies:6,attendees:10,friend_rate:'95',registrations:2,leads:5,qualified:true,bonus:'100',note:'仅浏览器样例',follow_up:'已联系',is_paid:false}]}}));
  await page.goto(process.env.QA_URL||'http://127.0.0.1:18080/');
  await page.getByLabel('账号',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('Demo2026!');await page.getByRole('button',{name:/登录工作台/}).click();
  const sales=page.locator('.commission-data-card').first(),market=page.locator('.commission-data-card').nth(1),meeting=page.locator('.reference-data-card').filter({has:page.locator('.ant-card-head-title',{hasText:'会议奖金明细'})});
  await sales.locator('.sales-blue-gear').first().waitFor();
  for(const card of [sales,market,meeting]){
   await card.locator('.ant-table-tbody tr.ant-table-row').first().waitFor();
   assert.equal(await card.locator('.ant-card-body > p.subtext').count(),0);
   assert.equal(await card.locator('.ant-card-body > .ant-alert-warning').count(),0);
   const alignments=await card.locator('.bonus-fit-content .ant-table-tbody tr.ant-table-row td').evaluateAll(cells=>cells.map(el=>[getComputedStyle(el).textAlign,getComputedStyle(el).verticalAlign]));
   assert(alignments.length>0);assert(alignments.every(([h,v])=>h==='center'&&v==='middle'));
  }
  assert.equal(await sales.locator('.ant-card-extra .sales-source-entries').count(),0);
  assert.equal(await sales.locator('.reference-filters .sales-source-entries button').count(),6);
  assert.equal(await sales.locator('.sales-blue-gear').count(),5);assert.equal(await sales.locator('.sales-parameter-gear').count(),2);
  for(const width of [1440,1280]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(400);
   const reset=await sales.getByRole('button',{name:/重\s*置/ }).boundingBox(),source=await sales.locator('.sales-source-entries button').first().boundingBox();
   assert(source.x>=reset.x+reset.width-1,JSON.stringify({width,reset,source}));assert(Math.abs(source.y-reset.y)<10);
   for(const card of [sales,market,meeting])assert(await card.evaluate(el=>el.querySelector('table').getBoundingClientRect().right<=el.querySelector('.bonus-fit-host').getBoundingClientRect().right+2));
  }
  // Place the gears near the viewport bottom so default overflow flipping would hide the header.
  for(const [selector,label,dimensions] of [['.sales-blue-gear','是否计发提成公式内容',[500,400]],['.sales-parameter-gear','是否计发提成参数输入区',[200,150]]]){
   const gear=sales.locator(selector).first();await gear.scrollIntoViewIfNeeded();
   await gear.evaluate(el=>window.scrollBy(0,el.getBoundingClientRect().top-(innerHeight-80)));
   await gear.click();const popup=page.getByLabel(label,{exact:true});await popup.waitFor();await page.waitForTimeout(700);
   assert.deepEqual(await popup.evaluate(el=>[el.offsetWidth,el.offsetHeight]),dimensions);
   const a=await gear.boundingBox(),b=await popup.boundingBox();assert(b.y>=a.y+a.height-1,JSON.stringify({selector,a,b}));
   assert.equal(await popup.locator('textarea').count(),0);await gear.click();await popup.waitFor({state:'hidden'});
  }
  const health=await(await page.request.get(new URL('/api/health',page.url()).href)).json();assert.equal(health.version,'0.0.4');assert.deepEqual(errors,[]);
  await sales.scrollIntoViewIfNeeded();await page.screenshot({path:'docs/v004-sales-layout.png'});
  console.log('PASS v0.0.4: all three tables centered; descriptions/warnings removed; six sources beside reset at 1280/1440; all columns fit; five blue/two purple gears retained; both fixed-size popovers open downward near viewport bottom. No business configuration changed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
