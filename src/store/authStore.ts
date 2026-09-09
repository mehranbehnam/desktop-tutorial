/**
 * Login state machine.
 *
 * `stage` is the single source of truth for which screen renders; every action
 * either advances it or parks an error on it.
 */
import { create } from 'zustand';
import { clearCredentials, credentialsAreFixed, getCredentials, type ApiCredentials } from '../config';
import { createClient, destroyClient, isAuthorized } from '../lib/telegram/client';
import * as auth from '../lib/telegram/auth';
import { releaseAll } from '../lib/telegram/media';
import type { AuthUser } from '../lib/telegram/types';

export type Stage =
  | 'booting'
  /** Reached a DC but the client has no api_id/api_hash yet. */
  | 'needsCredentials'
  /** Could not reach Telegram at all — the session, if any, is still intact. */
  | 'offline'
  | 'phone'
  | 'code'
  | 'password'
  | 'signUp'
  | 'ready';

interface AuthState {
  stage: Stage;
  busy: boolean;
  error: string | null;
  phone: string;
  phoneCodeHash: string;
  codeViaApp: boolean;
  passwordHint?: string;
  user: AuthUser | null;

  boot: () => Promise<void>;
  useCredentials: (creds: ApiCredentials) => Promise<void>;
  submitPhone: (phone: string) => Promise<void>;
  submitCode: (code: string) => Promise<void>;
  submitPassword: (password: string) => Promise<void>;
  submitSignUp: (firstName: string, lastName: string) => Promise<void>;
  back: () => void;
  resetCredentials: () => void;
  logOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  stage: 'booting',
  busy: false,
  error: null,
  phone: '',
  phoneCodeHash: '',
  codeViaApp: false,
  user: null,

  async boot() {
    set({ stage: 'booting', error: null });
    const creds = getCredentials();
    if (!creds) {
      set({ stage: 'needsCredentials' });
      return;
    }
    try {
      await createClient(creds);
      if (await isAuthorized()) {
        const user = await auth.getMe();
        set({ stage: 'ready', user });
      } else {
        set({ stage: 'phone' });
      }
    } catch (err) {
      const described = auth.describeError(err);
      // A network failure must not look like a logout: park on `offline` so the
      // stored session survives and a retry can pick it back up.
      set({
        stage: described.code === 'NETWORK' ? 'offline' : 'phone',
        error: described.message,
      });
    }
  },

  async useCredentials(creds) {
    set({ busy: true, error: null });
    try {
      await createClient(creds);
      set({ stage: (await isAuthorized()) ? 'ready' : 'phone', busy: false });
      if (get().stage === 'ready') set({ user: await auth.getMe() });
    } catch (err) {
      set({ busy: false, error: auth.describeError(err).message });
    }
  },

  async submitPhone(phone) {
    const creds = getCredentials();
    if (!creds) {
      set({ stage: 'needsCredentials' });
      return;
    }
    set({ busy: true, error: null });
    const result = await auth.sendCode(creds.apiId, creds.apiHash, phone);
    if (result.status === 'error') {
      // Bad credentials are unrecoverable from the phone step — go back a screen.
      if (result.code === 'API_ID_INVALID' && !credentialsAreFixed()) {
        clearCredentials();
        set({ busy: false, stage: 'needsCredentials', error: result.message });
        return;
      }
      set({ busy: false, error: result.message });
      return;
    }
    set({
      busy: false,
      stage: 'code',
      phone,
      phoneCodeHash: result.phoneCodeHash,
      codeViaApp: result.viaApp,
      error: null,
    });
  },

  async submitCode(code) {
    const { phone, phoneCodeHash } = get();
    set({ busy: true, error: null });
    const result = await auth.signIn(phone, phoneCodeHash, code);
    switch (result.status) {
      case 'ok':
        set({ busy: false, stage: 'ready', user: result.user, error: null });
        break;
      case 'passwordNeeded':
        set({ busy: false, stage: 'password', passwordHint: result.hint, error: null });
        break;
      case 'signUpNeeded':
        set({ busy: false, stage: 'signUp', error: null });
        break;
      default:
        set({ busy: false, error: result.message });
    }
  },

  async submitPassword(password) {
    set({ busy: true, error: null });
    const result = await auth.checkPassword(password);
    if (result.status === 'ok') set({ busy: false, stage: 'ready', user: result.user });
    else set({ busy: false, error: result.status === 'error' ? result.message : 'ورود ناموفق بود.' });
  },

  async submitSignUp(firstName, lastName) {
    const { phone, phoneCodeHash } = get();
    set({ busy: true, error: null });
    const result = await auth.signUp(phone, phoneCodeHash, firstName, lastName);
    if (result.status === 'ok') set({ busy: false, stage: 'ready', user: result.user });
    else set({ busy: false, error: result.status === 'error' ? result.message : 'ثبت‌نام ناموفق بود.' });
  },

  back() {
    const { stage } = get();
    if (stage === 'code' || stage === 'password' || stage === 'signUp') {
      set({ stage: 'phone', error: null, phoneCodeHash: '' });
    }
  },

  resetCredentials() {
    clearCredentials();
    window.location.reload();
  },

  async logOut() {
    set({ busy: true });
    releaseAll();
    await destroyClient(true);
    set({
      stage: 'phone',
      busy: false,
      user: null,
      phone: '',
      phoneCodeHash: '',
      error: null,
    });
    // A fresh MTProto session needs a fresh client instance.
    window.location.reload();
  },
}));
