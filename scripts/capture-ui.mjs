/**
 * Capture polished UI screens with Playwright.
 *
 * Usage:
 *   WEB_URL=http://127.0.0.1:4100 node scripts/capture-ui.mjs
 *
 * The target app should already be running and reachable.
 * Login credentials default to the backend bootstrap owner used in local dev.
 */
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const WEB = (process.env.WEB_URL || 'http://127.0.0.1:4100').replace(/\/+$/, '');
const EMAIL = process.env.UI_SHOT_EMAIL || 'owner@example.com';
const PASSWORD = process.env.UI_SHOT_PASSWORD || 'OwnerPass123!';
const OUT = process.env.UI_SHOT_DIR || 'artifacts/ui-shots';
mkdirSync(OUT, { recursive: true });

async function shot(page, name, fullPage = true) {
  await page.screenshot({ path: path.join(OUT, name), fullPage });
}

const browser = await chromium.launch({ headless: true });

const desktop = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
await desktop.goto(WEB, { waitUntil: 'networkidle', timeout: 45000 });
await shot(desktop, '01-landing-desktop.png');
await desktop.goto(`${WEB}/login`, { waitUntil: 'networkidle', timeout: 45000 });
await shot(desktop, '02-login-desktop.png');
await desktop.fill('input[type="email"]', EMAIL);
await desktop.fill('input[type="password"]', PASSWORD);
await desktop.click('button[type="submit"]');
await desktop.waitForURL('**/chat', { timeout: 20000 });
await desktop.waitForLoadState('networkidle');
await shot(desktop, '03-chat-desktop.png');

for (const [url, name] of [
  ['/files', '04-files-desktop.png'],
  ['/plugins', '05-plugins-desktop.png'],
  ['/deepsearch', '06-research-desktop.png'],
  ['/images', '07-media-lab-desktop.png'],
  ['/design', '08-design-studio-desktop.png'],
  ['/films', '09-films-desktop.png'],
  ['/voice', '10-voice-desktop.png'],
  ['/settings', '11-settings-desktop.png'],
  ['/admin', '12-admin-desktop.png'],
]) {
  await desktop.goto(`${WEB}${url}`, { waitUntil: 'networkidle', timeout: 45000 });
  await shot(desktop, name);
}

const mobileCtx = await browser.newContext({ ...devices['Pixel 7'] });
const mobile = await mobileCtx.newPage();
await mobile.goto(`${WEB}/login`, { waitUntil: 'networkidle', timeout: 45000 });
await shot(mobile, '13-login-mobile.png');
await mobile.fill('input[type="email"]', EMAIL);
await mobile.fill('input[type="password"]', PASSWORD);
await mobile.click('button[type="submit"]');
await mobile.waitForURL('**/chat', { timeout: 20000 });
await mobile.waitForLoadState('networkidle');
await shot(mobile, '14-chat-mobile.png');
await mobile.goto(`${WEB}/images`, { waitUntil: 'networkidle', timeout: 45000 });
await shot(mobile, '15-media-lab-mobile.png');
await mobile.goto(`${WEB}/settings`, { waitUntil: 'networkidle', timeout: 45000 });
await shot(mobile, '16-settings-mobile.png');

await browser.close();
console.log(`Saved screenshots to ${OUT}`);
