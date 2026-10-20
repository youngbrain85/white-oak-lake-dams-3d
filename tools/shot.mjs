// Headless render of the Three.js scene: node shot.mjs <preset,...> [outdir]
import { chromium } from '/opt/node-tools/node_modules/playwright/index.mjs';
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const presets = (process.argv[2] || 'bridge').split(',');
const outdir = process.argv[3] || 'shots';
fs.mkdirSync(outdir, { recursive: true });
const port = 8765;
const server = spawn('/opt/node22/bin/npx', ['http-server', '.', '-p', String(port), '-s', '-c-1'], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, 1500));
const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--no-sandbox', '--disable-dev-shm-usage'],
});
try {
  for (const p of presets) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    const logs = [];
    page.on('console', m => logs.push(m.type() + ': ' + m.text()));
    page.on('pageerror', e => logs.push('PAGEERROR: ' + e.message));
    const t0 = Date.now();
    await page.goto(`http://localhost:${port}/index_local.html?shot=${p}&low=${process.env.LOW || '0'}&dbg=${process.env.DBG || '0'}`, { waitUntil: 'load' });
    try {
      await page.waitForFunction(() => window.__ready === true || document.getElementById('status')?.textContent?.startsWith('Error'), null, { timeout: parseInt(process.env.TMO || '420000') });
    } catch (e) { logs.push('TIMEOUT waiting for __ready'); }
    logs.push('status: ' + await page.evaluate(() => document.getElementById('status')?.textContent));
    await page.screenshot({ path: `${outdir}/${p}.png`, timeout: 120000 });
    if (process.env.EXPORT === '1' && p === presets[0]) {
      const [dl, size] = await Promise.all([page.waitForEvent('download', { timeout: 600000 }), page.evaluate(() => window.exportGLB())]);
      await dl.saveAs(`${outdir}/white_oak_lake_dams.glb`);
      console.log('GLB exported', (size / 1e6).toFixed(1), 'MB');
    }
    console.log(p, 'done in', ((Date.now() - t0) / 1000).toFixed(1), 's');
    const bad = logs.filter(l => /error|PAGEERROR|TIMEOUT|status|H@C/i.test(l));
    if (bad.length) console.log(bad.slice(0, 15).join('\n'));
    await page.close();
  }
} finally {
  await browser.close();
  server.kill();
}
