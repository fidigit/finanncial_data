const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(process.env.QA_URL || 'http://127.0.0.1:18080/');
    await page.getByLabel('账号', { exact: true }).fill('admin');
    await page.getByLabel('密码', { exact: true }).fill('Demo2026!');
    await page.getByRole('button', { name: /登录工作台/ }).click();
    const sales = page.locator('.commission-data-card').first();
    await sales.getByRole('button', { name: '分摊比例公式', exact: true }).waitFor();
    assert.equal(await sales.locator('.sales-source-entries button').count(), 6);
    assert.equal(await sales.locator('.sales-blue-gear').count(), 5);
    assert.equal(await sales.locator('.sales-parameter-gear').count(), 2);
    assert.equal(await sales.locator('col').count(), 19);
    assert.equal(await page.locator('.commission-data-card').nth(1).locator('.sales-blue-gear').count(), 0);
    for (let i = 0; i < 6; i++) {
      await sales.locator('.sales-source-entries button').nth(i).click();
      const modal = page.locator('.sales-source-modal'); await modal.waitFor();
      await page.waitForFunction(() => { const el = document.querySelector('.sales-source-modal'); return el && el.getBoundingClientRect().width > innerWidth * .79 && el.getBoundingClientRect().height > innerHeight * .79; });
      await page.waitForTimeout(300);
      const geometry = await modal.evaluate(el => ({ height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width }));
      assert(Math.abs(geometry.height - 800) < 3, JSON.stringify(geometry));
      assert(Math.abs(geometry.width - 1152) < 5, JSON.stringify(geometry));
      assert.equal(await page.locator('.sales-source-mask').evaluate(el => getComputedStyle(el).backdropFilter), 'blur(8px)');
      await modal.getByText('原表样例 · 只读预览').waitFor();
      if (i === 0) await page.screenshot({ path: 'docs/sales-source-preview.png' });
      await page.locator('.sales-source-modal-wrap .ant-modal-close').click();
    }
    await sales.getByRole('button', { name: '分摊比例公式', exact: true }).click();
    const formula = page.getByLabel('分摊比例公式内容'); await formula.waitFor();
    assert.deepEqual(await formula.evaluate(el => [el.offsetWidth, el.offsetHeight]), [500, 400]);
    await formula.getByLabel('分摊比例完整计算规则').waitFor(); assert.equal(await formula.locator('textarea').count(), 0); assert.equal(await formula.getByPlaceholder('源头绑定待配置').count(), 0);
    await formula.getByRole('button', { name: '公式详情 / 隐藏变量' }).click();
    const detail = page.getByRole('dialog').filter({ hasText: '分摊比例 · 公式详情' });
    await detail.getByText('当季度目标', { exact: true }).waitFor();
    await detail.getByText('普通提成计算结果', { exact: true }).waitFor();
    await detail.locator('.ant-modal-close').click();
    await page.mouse.click(1200, 100);
    await sales.getByRole('button', { name: '适用提点（分段提点）参数配置', exact: true }).click();
    const params = page.getByLabel('适用提点（分段提点）参数输入区'); await params.waitFor();
    await params.getByRole('spinbutton').first().waitFor();
    await page.waitForFunction(() => !document.querySelector('.sales-parameter-viewport .ant-input-number')?.classList.contains('ant-input-number-disabled'));
    assert.deepEqual(await params.evaluate(el => [el.offsetWidth, el.offsetHeight]), [200, 150]);
    assert.equal(await params.getByRole('spinbutton').count(), 8);
    assert.equal(Number(await params.getByRole('spinbutton').first().inputValue()), 30000);
    if (process.env.QA_MUTATE === '1') {
      if (!process.env.QA_URL?.includes(':18081')) throw Error('Mutation allowed only on isolated QA port');
      const input = params.getByRole('spinbutton').first(); await input.fill('31000');
      const saved = page.waitForResponse(r => r.url().endsWith('/api/sales-formulas/inputs/period') && r.request().method() === 'PUT');
      await input.press('Enter'); assert((await saved).ok());
      await page.getByText('参数已保存并重新计算', { exact: true }).waitFor();
    }
    await page.mouse.click(1200, 100);
    for (const width of [1280, 1440]) {
      await page.setViewportSize({ width, height: 1000 }); await page.waitForTimeout(200);
      assert(await sales.evaluate(el => el.querySelector('table').getBoundingClientRect().right <= el.querySelector('.bonus-fit-host').getBoundingClientRect().right + 2));
    }
    await sales.scrollIntoViewIfNeeded(); await page.screenshot({ path: 'docs/sales-entry-overview.png' });
    const health = await (await page.request.get(new URL('/api/health', page.url()).href)).json(); assert.equal(health.version, '0.0.4');
    assert.deepEqual(errors, []);
    console.log('PASS: 6 sources, 5 blue/2 purple gears, 80% modal+blur, 500x400/200x150 popovers, 7 hidden variables, 19-column fit, version unchanged.' + (process.env.QA_MUTATE === '1' ? ' Isolated parameter save passed.' : ' Read only.'));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
