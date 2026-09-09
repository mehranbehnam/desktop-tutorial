/**
 * Drives the logged-in UI without a Telegram connection.
 *
 * The dev build exposes the zustand stores on `window.__lilika`; this script
 * pushes fixtures into them, then walks the app and screenshots each state.
 * Run against `npm run dev`:  node tools/ui-harness.mjs [outDir]
 */
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { self, peers, dialogs, teamMessages } from './fixtures.mjs';

// Honour a preinstalled browser when the environment provides one; otherwise
// fall back to whatever `npx playwright install chromium` put in place.
const EXECUTABLE = process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium';
const launchOptions = existsSync(EXECUTABLE) ? { executablePath: EXECUTABLE } : {};

const BASE = process.env.HARNESS_URL ?? 'http://127.0.0.1:5173/';
const OUT = process.argv[2] ?? 'harness-out';
await mkdir(OUT, { recursive: true });

const problems = [];
const browser = await chromium.launch(launchOptions);
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });

page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}\n${(e.stack ?? '').split('\n').slice(1, 5).join('\n')}`));
page.on('console', (m) => {
  const t = m.text();
  if (m.type() === 'error' && !t.includes('WebSocket') && !t.includes('Event')) {
    problems.push(`console: ${t.slice(0, 200)}`);
  }
});

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => Boolean(window.__lilika), null, { timeout: 20000 });

/** Skips login and drops straight into the shell with fixture data. */
async function seed(target, withChat = true) {
  await target.evaluate(
    ({ self, dialogs }) => {
      const { auth, chat } = window.__lilika;
      auth.setState({ stage: 'ready', user: self, busy: false, error: null });
      chat.setState({ selfId: self.id, dialogs, dialogsLoading: false, dialogsCursor: null });
    },
    { self, dialogs },
  );
  if (!withChat) return;
  await target.evaluate(
    ({ peer, messages }) => {
      window.__lilika.chat.setState({
        activePeerId: peer.id,
        activePeer: peer,
        conversations: { [peer.id]: { messages, nextOffsetId: 1, loading: false, loadedOnce: true } },
      });
    },
    { peer: peers.team, messages: teamMessages },
  );
}

await seed(page, false);
await page.waitForSelector('.chat-item', { timeout: 10000 });
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/10-list-empty-chat.png` });

// Open a group conversation with a spread of message shapes.
await seed(page);
await page.waitForSelector('.bubble', { timeout: 10000 });
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/11-chat-dark.png` });

const counts = await page.evaluate(() => ({
  bubbles: document.querySelectorAll('.bubble').length,
  service: document.querySelectorAll('.service-message').length,
  daySeparators: document.querySelectorAll('.day-separator').length,
  senders: document.querySelectorAll('.bubble-sender').length,
  replies: document.querySelectorAll('.bubble-reply').length,
  spoilers: document.querySelectorAll('.spoiler').length,
  code: document.querySelectorAll('.bubble-text code').length,
  files: document.querySelectorAll('.media-file').length,
  horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
}));

// Reply composer.
await page.click('.bubble-reply');
await page.evaluate(() => {
  const { chat } = window.__lilika;
  const conv = chat.getState().conversations['301'];
  chat.getState().setReplyTo(conv.messages.find((m) => m.id === 12));
});
await page.waitForSelector('.composer-reply');
await page.fill('.composer-input', 'یک پیام آزمایشی برای بررسی ارتفاع خودکار جعبه نوشتن که چند خط می‌شود.');
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/12-composer-reply.png` });

// Profile panel.
await page.click('.chat-header-info');
await page.waitForSelector('.panel', { timeout: 5000 });
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/13-profile-panel.png` });

// Settings panel.
await page.evaluate(() => window.__lilika.ui.getState().openPanel('settings'));
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/14-settings.png` });

// Light theme. Captured after a reload: it proves the preference persists,
// and headless compositing does not always repaint layers when a CSS custom
// property flips mid-session, which makes a live-swap screenshot unreliable.
await page.evaluate(() => {
  window.__lilika.ui.getState().set('theme', 'light');
  window.__lilika.ui.getState().openPanel('none');
});
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => Boolean(window.__lilika));
await seed(page);
await page.waitForSelector('.bubble');
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/15-chat-light.png` });
const lightPaint = await page.evaluate(() => ({
  theme: document.documentElement.dataset.theme,
  sidebar: getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
  header: getComputedStyle(document.querySelector('.chat-header')).backgroundColor,
}));

// Accent swap, to prove the token wiring.
await page.evaluate(() => {
  window.__lilika.ui.getState().set('theme', 'dark');
  window.__lilika.ui.getState().set('accent', 'violet');
});
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/16-accent-violet.png` });

// Phone-width: list view, then chat view.
await page.evaluate(() => window.__lilika.ui.getState().set('accent', 'teal'));
await page.setViewportSize({ width: 390, height: 780 });
await page.evaluate(() => window.__lilika.ui.getState().setMobileView('list'));
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/17-mobile-list.png` });

await page.evaluate(() => window.__lilika.ui.getState().setMobileView('chat'));
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/18-mobile-chat.png` });

const mobileOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
);

console.log(JSON.stringify({ counts, lightPaint, mobileOverflow, problems }, null, 2));
await browser.close();
process.exit(problems.length ? 1 : 0);
