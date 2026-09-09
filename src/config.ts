/**
 * Runtime configuration.
 *
 * API credentials can come from two places:
 *  1. Build-time env (VITE_TG_API_ID / VITE_TG_API_HASH) — for a real deployment.
 *  2. The in-app setup screen — stored in localStorage, useful for local dev.
 *
 * Never ship someone else's api_id: Telegram bans apps that share credentials.
 */
import { readJSON, writeJSON, remove } from './lib/storage';

export interface ApiCredentials {
  apiId: number;
  apiHash: string;
}

const CREDENTIALS_KEY = 'lilika.credentials';

export const branding = {
  name: import.meta.env.VITE_APP_NAME || 'لیلیکا',
  nameEn: import.meta.env.VITE_APP_NAME_EN || 'LiLika',
  version: '0.1.0',
};

function fromEnv(): ApiCredentials | null {
  const id = Number(import.meta.env.VITE_TG_API_ID);
  const hash = import.meta.env.VITE_TG_API_HASH;
  if (Number.isFinite(id) && id > 0 && typeof hash === 'string' && hash.length > 0) {
    return { apiId: id, apiHash: hash };
  }
  return null;
}

export function getCredentials(): ApiCredentials | null {
  return fromEnv() ?? readJSON<ApiCredentials>(CREDENTIALS_KEY);
}

export function saveCredentials(creds: ApiCredentials): void {
  writeJSON(CREDENTIALS_KEY, creds);
}

export function clearCredentials(): void {
  remove(CREDENTIALS_KEY);
}

/** True when credentials are baked into the build and cannot be edited at runtime. */
export function credentialsAreFixed(): boolean {
  return fromEnv() !== null;
}
