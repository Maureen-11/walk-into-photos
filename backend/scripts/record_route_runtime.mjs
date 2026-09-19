#!/usr/bin/env node
/**
 * R04 runtime evidence for an already exported offline scene.
 * This does not modify the scene. It drives a real file:// page with the
 * same Playwright/Chrome runtime used by offline-verify and records HUD text,
 * screenshots, console errors, and page errors at route checkpoints.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const argv = process.argv.slice(2);
const value = (name, fallback = null) => {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : fallback;
};

const entry = value('--entry');
const out = value('--out');
const playwrightModule = value('--playwright-module');
if (!entry || !out || !playwrightModule) {
  console.error('usage: node record_route_runtime.mjs --entry <index.html> --out <dir> --playwright-module <dir>');
  process.exit(2);
}

const { chromium } = require(playwrightModule);
const outputDir = path.resolve(out);
await fs.mkdir(outputDir, { recursive: true });
const errors = [];
const consoleMessages = [];
let browser;
for (const channel of ['chrome', 'msedge']) {
  try {
    browser = await chromium.launch({
      channel,
      headless: true,
      args: ['--no-default-browser-check', '--no-first-run', '--use-angle=swiftshader'],
    });
    break;
  } catch (error) {
    if (channel === 'msedge') throw error;
  }
}
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
page.on('console', (message) => {
  const text = message.text();
  consoleMessages.push({ type: message.type(), text });
  if (message.type() === 'error') errors.push(`console: ${text}`);
});

const checkpoints = [];
async function capture(label) {
  const hud = await page.locator('#hud').innerText();
  await page.screenshot({ path: path.join(outputDir, `${label}.png`), fullPage: false });
  checkpoints.push({ label, hud });
}
async function hold(key, milliseconds) {
  await page.keyboard.down(key);
  await page.waitForTimeout(milliseconds);
  await page.keyboard.up(key);
  await page.waitForTimeout(180);
}

try {
  await page.goto(`file:///${entry.replaceAll('\\', '/')}`, { waitUntil: 'load' });
  await page.locator('canvas').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('canvas').click();
  await capture('00-start');
  await hold('w', 3200);
  await capture('01-forward');
  await hold('d', 2000);
  await capture('02-right');
  await hold('w', 6500);
  await capture('03-end-approach');
  await hold('a', 2000);
  await hold('w', 5000);
  await capture('04-end');
  await page.keyboard.press('r');
  await page.waitForTimeout(250);
  await capture('05-reset');
} finally {
  await browser.close();
}

const report = {
  schema: 'luna-route-runtime/1',
  entry: path.resolve(entry),
  viewport: { width: 1280, height: 800 },
  checkpoints,
  page_errors: errors,
  console_errors: consoleMessages.filter((item) => item.type === 'error'),
  console_warnings: consoleMessages.filter((item) => item.type === 'warning'),
  verdict: errors.length === 0 ? 'candidate_pass' : 'fail',
  note: '真实 file:// 路线实测；candidate_pass 仍需人工检查截图中的穿模、闪烁和审美退步。',
};
await fs.writeFile(path.join(outputDir, 'route-runtime.json'), JSON.stringify(report, null, 2), 'utf8');
console.log(JSON.stringify(report, null, 2));
