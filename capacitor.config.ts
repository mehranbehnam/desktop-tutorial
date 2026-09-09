import type { CapacitorConfig } from '@capacitor/cli';

/**
 * Android shell. The web build in `dist/` is bundled into the APK and runs in
 * the system WebView, which reaches Telegram over WSS exactly as the browser
 * does — no extra native networking code is involved.
 */
const config: CapacitorConfig = {
  appId: 'com.lilika.messenger',
  appName: 'لیلیکا',
  webDir: 'dist',
  android: {
    // The app ships its own assets; nothing is fetched over plaintext HTTP.
    allowMixedContent: false,
  },
  server: {
    androidScheme: 'https',
  },
};

export default config;
