/**
 * Connectivity preflight.
 *
 * The single most common reason a self-hosted Telegram client "does not work"
 * is that the network between the browser and Telegram's datacentres is
 * blocked. This checks each web datacentre endpoint the client can be routed
 * to and reports which ones answer, before anyone starts debugging the app.
 *
 *   node tools/doctor.mjs
 *
 * Note: this tests the *machine running the script*. The browser that actually
 * runs LiLika is what must reach Telegram, so run it from the same network.
 */

// Telegram's public websocket endpoints, one per datacentre.
const ENDPOINTS = [
  ['DC1  pluto', 'wss://pluto.web.telegram.org/apiws'],
  ['DC2  venus', 'wss://venus.web.telegram.org/apiws'],
  ['DC3  aurora', 'wss://aurora.web.telegram.org/apiws'],
  ['DC4  vesta', 'wss://vesta.web.telegram.org/apiws'],
  ['DC5  flora', 'wss://flora.web.telegram.org/apiws'],
];

const TIMEOUT_MS = 12_000;

if (typeof WebSocket === 'undefined') {
  console.error('این اسکریپت به Node 21 یا بالاتر نیاز دارد (WebSocket سراسری).');
  process.exit(2);
}

/** Resolves to true only when the socket actually opens. */
function probe(url) {
  return new Promise((resolve) => {
    let socket;
    // Closing a socket that is still CONNECTING fires onerror again, so
    // without this guard the handler would re-enter itself until the stack
    // blew up.
    let settled = false;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { socket?.close(); } catch { /* already gone */ }
      resolve(result);
    };

    const timer = setTimeout(() => finish({ ok: false, reason: 'timeout' }), TIMEOUT_MS);

    try {
      socket = new WebSocket(url, 'binary');
    } catch (err) {
      finish({ ok: false, reason: err.message });
      return;
    }
    socket.onopen = () => finish({ ok: true });
    socket.onerror = (event) => finish({ ok: false, reason: event?.message ?? 'connection refused' });
  });
}

const started = Date.now();
console.log('بررسی دسترسی به دیتاسنترهای تلگرام…\n');

// Probed in parallel: on a blocked network every one of these has to time
// out, and doing that serially would take a minute for no extra information.
const results = await Promise.all(
  ENDPOINTS.map(async ([label, url]) => {
    const at = Date.now();
    const result = await probe(url);
    return { label, ms: Date.now() - at, ...result };
  }),
);

for (const result of results) {
  console.log(
    result.ok
      ? `  ✅ ${result.label.padEnd(12)} ${String(result.ms).padStart(5)}ms`
      : `  ❌ ${result.label.padEnd(12)} ${result.reason}`,
  );
}

const reachable = results.filter((r) => r.ok).length;
console.log(`\nنتیجه: ${reachable} از ${results.length} دیتاسنتر پاسخ داد (${Date.now() - started}ms)\n`);

if (reachable === 0) {
  console.log('هیچ دیتاسنتری در دسترس نیست. لیلیکا از این شبکه کار نمی‌کند.');
  console.log('این محدودیت شبکه است، نه ایراد برنامه. گزینه‌ها:');
  console.log('  • همین دستور را از شبکه‌ای که به تلگرام دسترسی دارد اجرا کن.');
  console.log('  • برنامه را روی سروری خارج از آن شبکه میزبانی کن.');
  console.log('  • از VPN روی همان دستگاهی که مرورگر را اجرا می‌کند استفاده کن.');
  process.exit(1);
}

console.log('شبکه آماده است. حالا `npm run dev` را اجرا کن.');
