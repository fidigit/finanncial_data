// Local, read-only UI smoke check. Requires Playwright from the installed runtime.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:18080/');
  await page.getByLabel('账号', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('Demo2026!');
  await page.getByRole('button', { name: /登录工作台/ }).click();
  await page.getByText('BD身份归类器', { exact: true }).waitFor();
  for (const title of ['销售奖金表', '市场奖金表', '会议奖金明细']) {
    await page.getByText(title, { exact: true }).waitFor();
  }
  const sales = page.locator('.commission-data-card').first();
  await sales.locator('.ant-table-row-expand-icon').first().click();
  await sales.getByText('奖金计算基数', { exact: true }).waitFor();
  await sales.scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'docs/v0.0.2-sales-preview.png' });
  await page.getByRole('button', { name: '新增会议' }).click();
  await page.getByRole('dialog').waitFor();
  await page.screenshot({ path: 'docs/v0.0.2-meeting-preview.png' });
  await page.getByRole('button', { name: '取 消', exact: true }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (errors.length || overflow) throw Error(JSON.stringify({ errors, overflow }));
  console.log('UI passed: three tables, category editor, expanded details, meeting form; no page errors or page overflow.');
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
