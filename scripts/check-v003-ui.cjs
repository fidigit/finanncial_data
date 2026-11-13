const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://127.0.0.1:18080/');
  await page.getByLabel('账号', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('Demo2026!');
  await page.getByRole('button', { name: /登录工作台/ }).click();
  const tables = page.locator('.bonus-fit-section');
  await tables.nth(2).waitFor();
  await page.locator('.commission-data-card .ant-table-tbody tr').first().waitFor();
  for (const width of [1920, 1440, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(250);
    const sizes = await tables.evaluateAll(elements => elements.map(el => {
      const host = el.querySelector('.bonus-fit-host').getBoundingClientRect();
      const table = el.querySelector('table').getBoundingClientRect();
      return { width: table.width, available: host.width, leaves: el.querySelectorAll('col').length, overflow: table.right > host.right + 2, clipped: [...el.querySelectorAll('th,td')].some(cell => cell.scrollWidth > cell.clientWidth + 2) };
    }));
    if (sizes.some(s => s.overflow || s.clipped) || sizes[0].leaves !== 19 || sizes[1].leaves !== 19 || sizes[2].leaves !== 15) throw Error(JSON.stringify({ width, sizes }));
    console.log(JSON.stringify({ width, sizes }));
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  const sales = tables.first();
  await sales.evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: 'docs/v0.0.3-all-columns.png' });
  await sales.getByRole('button', { name: '全屏查看', exact: true }).click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: 'docs/v0.0.3-fullscreen.png' });
  await sales.getByRole('button', { name: '确认 / 修改', exact: true }).first().click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button', { name: '取 消', exact: true }).click();
  await page.keyboard.press('Escape');
  if (await page.locator('.bonus-fit-fullscreen').count()) throw Error('Escape failed');
  await page.getByRole('button', { name: '展开导航', exact: true }).click();
  await page.waitForTimeout(250);
  const fits = await sales.evaluate(el => el.querySelector('table').getBoundingClientRect().right <= el.querySelector('.bonus-fit-host').getBoundingClientRect().right + 2);
  if (!fits || errors.length) throw Error(JSON.stringify({ fits, errors }));
  console.log('PASS: all columns visible, no clipped cells, auto-fit, full screen, edit modal, Escape and navigation resizing.');
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
