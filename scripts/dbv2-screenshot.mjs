// Dev helper: screenshot dashboard-v2 pages + report console errors.
// Usage: node scripts/dbv2-screenshot.mjs CODE [CODE...]
import { chromium } from 'playwright';

const codes = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });

for (const code of codes) {
    const errors = [];
    page.removeAllListeners('console');
    page.removeAllListeners('pageerror');
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));

    await page.goto(`http://127.0.0.1:8088/dataset-v2.html?code=${code}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    const path = `/tmp/dbv2-${code}.png`;
    await page.screenshot({ path, fullPage: true });
    console.log(`${code}: ${path}${errors.length ? '\n  ERRORS: ' + errors.join('\n  ') : ' (no console errors)'}`);
}
await browser.close();
