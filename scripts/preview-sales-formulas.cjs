// Read-only UI verification of the actual local deployment; no configuration writes.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto('http://127.0.0.1:18080/');
  await page.getByLabel('账号', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('Demo2026!');
  await page.getByRole('button', { name: /登录工作台/ }).click();
  const sales = page.locator('.commission-data-card').first();
  await sales.getByRole('button', { name: '奖金公式', exact: true }).waitFor();
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(200);
    const fit = await sales.evaluate(el => {
      const table = el.querySelector('table'), host = el.querySelector('.bonus-fit-host');
      return table.getBoundingClientRect().right <= host.getBoundingClientRect().right + 2;
    });
    if (!fit || await sales.locator('col').count() !== 19) throw Error('Sales table no longer fits 19 columns');
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await sales.evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.waitForTimeout(700);
  await page.screenshot({ path: 'docs/sales-formula-table.png' });
  await sales.getByRole('button', { name: '奖金公式', exact: true }).click();
  await page.getByRole('dialog').getByText('涉及变量及来源').waitFor();
  await page.waitForFunction(() => { const el = document.querySelector('.ant-modal'); return el && Number(getComputedStyle(el).opacity) === 1 && el.getBoundingClientRect().width > 400; });
  await page.waitForTimeout(700);
  await page.screenshot({ path: 'docs/sales-formula-dialog.png' });
  await page.getByRole('button', { name: '查看 / 配置变量', exact: true }).click();
  await page.locator('.ant-drawer-body').getByLabel('W 当季度目标（元）').waitFor();
  await page.waitForTimeout(700);
  await page.screenshot({ path: 'docs/sales-formula-inputs.png' });
  console.log('PASS: actual deployment has 19 visible columns, formulas and variables; no data written.');
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
