const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs/promises');
const {execFileSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
(async()=>{
 const base=process.env.QA_URL||'http://127.0.0.1:18081/';if(new URL(base).port!=='18081')throw Error('Mutations require isolated port 18081');
 const browser=await chromium.launch({channel:'msedge',headless:true});let page;
 try{
  page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.getByLabel('账号',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('Demo2026!');await page.getByRole('button',{name:/登录工作台/}).click();
  const sales=page.locator('.commission-data-card').first();await sales.locator('.sales-blue-gear').first().waitFor();
  const api=async url=>{const r=await page.request.get(new URL('/api'+url,base).href);assert(r.ok(),await r.text());return r.json()};
  let first=(await api('/commission-data?category=sales&page_size=1')).rows[0];const before={basis:first.bonus_basis,bonus:first.bonus,paid:first.is_paid,refunded:first.is_refunded};
  await sales.getByRole('button',{name:'确认 / 修改',exact:true}).first().click();const note=page.getByRole('dialog').filter({hasText:'订单提成确认'});await note.getByRole('textbox',{name:'订单备注',exact:true}).waitFor();
  assert.equal(await note.getByRole('textbox',{name:'订单备注',exact:true}).inputValue(),first.note);
  assert.equal(await note.getByRole('spinbutton').count(),0);assert.equal(await note.getByRole('combobox').count(),0);assert.equal(await note.getByRole('textbox').count(),1);
  const editedNote=first.note+'\nQA：仅修改备注';await note.getByRole('textbox',{name:'订单备注',exact:true}).fill(editedNote);
  await Promise.all([page.waitForResponse(r=>r.url().endsWith('/commission-data/note')&&r.request().method()==='PUT'),note.getByRole('button',{name:/保存备注/}).click()]);await note.waitFor({state:'hidden'});
  first=(await api('/commission-data?category=sales&page_size=1')).rows[0];assert.equal(first.note,editedNote);assert.deepEqual({basis:first.bonus_basis,bonus:first.bonus,paid:first.is_paid,refunded:first.is_refunded},before);
  console.log('PASS notes: current displayed text prefilled, single text area only, save preserves bonus and statuses');
  // Filter to one BD and one order so the saved workbook has a single reviewed row.
  const bd=sales.getByRole('combobox',{name:'提成确认BD',exact:true});await bd.fill(first.owner);await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:new RegExp('^'+first.owner+'$')}).click();
  const search=sales.getByLabel('搜索提成确认明细',{exact:true});await search.fill(first.order_no);await search.press('Enter');await page.waitForTimeout(650);
  const pending=page.waitForEvent('download');await sales.getByRole('button',{name:'导出 XLSX',exact:true}).click();const download=await pending;const filename=download.suggestedFilename();assert(/_\d{8}-\d{6}_v[1-9]\d*\.xlsx$/.test(filename),filename);
  const source=path.resolve('data/v006-ui-roundtrip/original',filename),edited=path.resolve('data/v006-ui-roundtrip/edited',filename);await fs.mkdir(path.dirname(source),{recursive:true});await download.saveAs(source);
  const latest=await api('/bonus-import/latest');assert.equal(latest.filename,filename);
  const paid=first.is_paid===true?'否':'是',refunded=first.is_refunded===false?'是':'否';
  const python=process.env.QA_PYTHON||'C:/Users/JOYY/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
  console.log(execFileSync(python,['scripts/qa_resave_status_xlsx.py',source,edited,'--paid',paid,'--refunded',refunded],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}}).trim());
  const chooser=page.waitForEvent('filechooser');await sales.getByRole('button',{name:'导入销售奖金XLSX',exact:true}).click();await(await chooser).setFiles(edited);
  const preview=page.getByRole('dialog').filter({hasText:'奖金状态导入预览'});await preview.waitFor();await preview.getByText(latest.suffix,{exact:true}).waitFor();await preview.getByText(/1条将变更/).waitFor();
  let stored=(await api('/commission-data?category=sales&page_size=1')).rows[0];assert.equal(stored.is_paid,first.is_paid);
  await page.screenshot({path:'docs/v006-import-preview.png'});
  await Promise.all([page.waitForResponse(r=>r.url().includes('/bonus-import/sales?')&&r.request().method()==='POST'),preview.getByRole('button',{name:/确认导入/}).click()]);await preview.waitFor({state:'hidden'});
  stored=(await api('/commission-data?category=sales&page_size=1')).rows[0];assert.equal(stored.is_paid,paid==='是');assert.equal(stored.is_refunded,refunded==='是');assert.equal(stored.note,editedNote);assert.equal(stored.bonus,first.bonus);
  assert.equal((await api('/bonus-import/latest')).consumed,true);console.log('PASS protected workbook: browser version filename, Excel-compatible read/save, preview without write and status-only import');
  const replayChooser=page.waitForEvent('filechooser');await sales.getByRole('button',{name:'导入销售奖金XLSX',exact:true}).click();await(await replayChooser).setFiles(edited);await page.getByText(/此版本已经导入/).waitFor();
  const nextDownload=page.waitForEvent('download');await sales.getByRole('button',{name:'导出 XLSX',exact:true}).click();const next=await nextDownload;assert.notEqual(next.suggestedFilename(),filename);
  const oldChooser=page.waitForEvent('filechooser');await sales.getByRole('button',{name:'导入销售奖金XLSX',exact:true}).click();await(await oldChooser).setFiles(edited);await page.getByText(/文件版本不是当前账号最后一次导出版本/).waitFor();
  const latestAfter=await api('/bonus-import/latest');assert.equal(latestAfter.filename,next.suggestedFilename());
  const meeting=page.locator('.reference-data-card').filter({has:page.locator('.ant-card-head-title',{hasText:'会议奖金明细'})});const meetingDownload=page.waitForEvent('download');await meeting.getByRole('button',{name:'导出 XLSX',exact:true}).click();assert.equal((await meetingDownload).suggestedFilename(),'会议奖金明细.xlsx');assert.equal((await api('/bonus-import/latest')).suffix,latestAfter.suffix);
  assert.equal((await api('/health')).version,'0.0.6');assert.deepEqual(errors,[]);console.log('PASS replay and older-version rejection; meetings unchanged; v0.0.6 end-to-end (isolated data only)');
 }catch(e){if(page)await page.screenshot({path:'docs/v006-ui-failure.png'}).catch(()=>{});throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
