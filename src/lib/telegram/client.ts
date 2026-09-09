/**
 * MTProto client lifecycle.
 *
 * One `TelegramClient` lives for the whole tab. The session string is the only
 * durable secret we hold; it is written back to localStorage after every
 * auth-changing call so a reload lands straight back in the chat list.
 */
import { Api, TelegramClient } from 'telegram';
import { StringSession } from 'telegram/sessions';
import { LogLevel } from 'telegram/extensions/Logger';
import type { ApiCredentials } from '../../config';
import { readString, writeString, remove } from '../storage';

const SESSION_KEY = 'lilika.session';

/** Recognised by `describeError` so the UI can name the failure. */
export const CONNECTION_TIMEOUT = 'CONNECTION_TIMEOUT';

const CONNECT_TIMEOUT_MS = 25_000;
const RPC_TIMEOUT_MS = 20_000;

let client: TelegramClient | null = null;
let session: StringSession | null = null;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error(CONNECTION_TIMEOUT)),
      ms,
    );
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export function loadSessionString(): string {
  return readString(SESSION_KEY) ?? '';
}

export function persistSession(): void {
  if (!session) return;
  const saved = session.save();
  if (typeof saved === 'string' && saved.length > 0) writeString(SESSION_KEY, saved);
}

export function clearSession(): void {
  remove(SESSION_KEY);
}

export function hasClient(): boolean {
  return client !== null;
}

/** Throws if called before `createClient` — every caller is downstream of auth. */
export function getClient(): TelegramClient {
  if (!client) throw new Error('Telegram client is not initialised yet');
  return client;
}

export async function createClient(creds: ApiCredentials): Promise<TelegramClient> {
  if (client) return client;

  session = new StringSession(loadSessionString());
  client = new TelegramClient(session, creds.apiId, creds.apiHash, {
    connectionRetries: 5,
    retryDelay: 1500,
    autoReconnect: true,
    useWSS: true, // browsers only get MTProto over secure websockets
    deviceModel: navigator.userAgent.slice(0, 64),
    systemVersion: navigator.platform || 'web',
    appVersion: '0.1.0',
    langCode: 'fa',
    systemLangCode: 'fa',
  });

  client.setLogLevel(import.meta.env.DEV ? LogLevel.WARN : LogLevel.ERROR);

  try {
    // GramJS retries internally and will otherwise sit on a dead socket
    // indefinitely — on a blocked network the UI must get an answer.
    await withTimeout(client.connect(), CONNECT_TIMEOUT_MS);
    // connect() resolves even when every transport attempt failed, so the
    // socket state is what actually says whether we have a link to a DC.
    if (!client.connected) throw new Error(CONNECTION_TIMEOUT);
  } catch (err) {
    client = null;
    session = null;
    throw err;
  }
  persistSession();
  return client;
}

/** Full teardown: used by "log out" and by credential changes. */
export async function destroyClient(logOut: boolean): Promise<void> {
  if (client) {
    try {
      if (logOut) await client.invoke(new Api.auth.LogOut());
    } catch {
      /* the session may already be dead server-side; local cleanup still matters */
    }
    try {
      await client.disconnect();
      await client.destroy();
    } catch {
      /* ignore */
    }
  }
  client = null;
  session = null;
  clearSession();
}

/**
 * Throws `CONNECTION_TIMEOUT` when the check cannot reach a DC — the caller
 * must not read that as "logged out", or a flaky network would silently drop
 * the user back to the phone screen.
 */
export async function isAuthorized(): Promise<boolean> {
  if (!client) return false;
  return withTimeout(client.isUserAuthorized(), RPC_TIMEOUT_MS);
}
