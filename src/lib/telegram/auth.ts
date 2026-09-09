/**
 * Login flow: phone -> code -> (2FA password | sign-up).
 *
 * Telegram signals each branch with a named RPC error rather than a status
 * field, so the caller drives the state machine off the discriminated result
 * below instead of catching strings.
 */
import { Api } from 'telegram';
import { computeCheck } from 'telegram/Password';
import { getClient, persistSession } from './client';
import type { AuthUser } from './types';
import { idToString } from './utils';

export type SendCodeResult =
  | { status: 'codeSent'; phoneCodeHash: string; viaApp: boolean; timeout: number }
  | { status: 'error'; code: AuthErrorCode; message: string };

export type SignInResult =
  | { status: 'ok'; user: AuthUser }
  | { status: 'passwordNeeded'; hint?: string }
  | { status: 'signUpNeeded' }
  | { status: 'error'; code: AuthErrorCode; message: string };

export type AuthErrorCode =
  | 'PHONE_NUMBER_INVALID'
  | 'PHONE_CODE_INVALID'
  | 'PHONE_CODE_EXPIRED'
  | 'PASSWORD_INVALID'
  | 'FLOOD_WAIT'
  | 'API_ID_INVALID'
  | 'PHONE_BANNED'
  | 'NETWORK'
  | 'UNKNOWN';

interface RpcErrorish {
  errorMessage?: string;
  message?: string;
  seconds?: number;
}

/** Maps an RPC error onto our own codes plus a Persian message. */
export function describeError(err: unknown): { code: AuthErrorCode; message: string } {
  const e = err as RpcErrorish;
  const raw = e?.errorMessage ?? e?.message ?? '';

  if (raw.includes('PHONE_NUMBER_INVALID'))
    return { code: 'PHONE_NUMBER_INVALID', message: 'شماره تلفن معتبر نیست.' };
  if (raw.includes('PHONE_CODE_INVALID'))
    return { code: 'PHONE_CODE_INVALID', message: 'کد وارد‌شده درست نیست.' };
  if (raw.includes('PHONE_CODE_EXPIRED'))
    return { code: 'PHONE_CODE_EXPIRED', message: 'کد منقضی شده است؛ دوباره درخواست کنید.' };
  if (raw.includes('PASSWORD_HASH_INVALID'))
    return { code: 'PASSWORD_INVALID', message: 'رمز دومرحله‌ای درست نیست.' };
  if (raw.includes('PHONE_NUMBER_BANNED'))
    return { code: 'PHONE_BANNED', message: 'این شماره توسط تلگرام مسدود شده است.' };
  if (raw.includes('API_ID_INVALID') || raw.includes('API_ID_PUBLISHED_FLOOD'))
    return { code: 'API_ID_INVALID', message: 'api_id / api_hash نامعتبر است یا محدود شده.' };
  if (raw.includes('FLOOD_WAIT')) {
    const seconds = e?.seconds ?? Number(raw.match(/FLOOD_WAIT_(\d+)/)?.[1] ?? 0);
    const minutes = Math.ceil(seconds / 60);
    return {
      code: 'FLOOD_WAIT',
      message: `درخواست‌های زیاد. حدود ${minutes} دقیقه دیگر دوباره تلاش کنید.`,
    };
  }
  if (raw.includes('CONNECTION_TIMEOUT') || raw.includes('Not connected'))
    return {
      code: 'NETWORK',
      message: 'اتصال به سرورهای تلگرام برقرار نشد. اینترنت یا فیلترشکن را بررسی کن.',
    };
  if (raw.includes('CONNECTION') || raw.includes('TIMEOUT') || raw.includes('Not connected'))
    return { code: 'NETWORK', message: 'ارتباط با سرور برقرار نشد.' };

  return { code: 'UNKNOWN', message: raw || 'خطای ناشناخته.' };
}

export function toAuthUser(user: Api.User): AuthUser {
  return {
    id: idToString(user.id),
    firstName: user.firstName ?? '',
    lastName: user.lastName ?? undefined,
    username: user.username ?? undefined,
    phone: user.phone ?? undefined,
  };
}

export async function sendCode(
  apiId: number,
  apiHash: string,
  phoneNumber: string,
): Promise<SendCodeResult> {
  try {
    const result = await getClient().sendCode({ apiId, apiHash }, normalisePhone(phoneNumber));
    persistSession();
    return {
      status: 'codeSent',
      phoneCodeHash: result.phoneCodeHash,
      viaApp: Boolean(result.isCodeViaApp),
      timeout: 120,
    };
  } catch (err) {
    return { status: 'error', ...describeError(err) };
  }
}

export async function signIn(
  phoneNumber: string,
  phoneCodeHash: string,
  phoneCode: string,
): Promise<SignInResult> {
  const client = getClient();
  try {
    const res = await client.invoke(
      new Api.auth.SignIn({
        phoneNumber: normalisePhone(phoneNumber),
        phoneCodeHash,
        phoneCode: phoneCode.replace(/\D/g, ''),
      }),
    );
    persistSession();
    if (res instanceof Api.auth.Authorization && res.user instanceof Api.User) {
      return { status: 'ok', user: toAuthUser(res.user) };
    }
    return { status: 'signUpNeeded' };
  } catch (err) {
    const raw = (err as RpcErrorish)?.errorMessage ?? '';
    if (raw.includes('SESSION_PASSWORD_NEEDED')) {
      const hint = await passwordHint();
      return { status: 'passwordNeeded', hint };
    }
    if (raw.includes('PHONE_NUMBER_UNOCCUPIED')) return { status: 'signUpNeeded' };
    return { status: 'error', ...describeError(err) };
  }
}

async function passwordHint(): Promise<string | undefined> {
  try {
    const pwd = await getClient().invoke(new Api.account.GetPassword());
    return pwd.hint || undefined;
  } catch {
    return undefined;
  }
}

/** Second factor: SRP check against the cloud password. */
export async function checkPassword(password: string): Promise<SignInResult> {
  const client = getClient();
  try {
    const pwd = await client.invoke(new Api.account.GetPassword());
    const srp = await computeCheck(pwd, password);
    const res = await client.invoke(new Api.auth.CheckPassword({ password: srp }));
    persistSession();
    if (res instanceof Api.auth.Authorization && res.user instanceof Api.User) {
      return { status: 'ok', user: toAuthUser(res.user) };
    }
    return { status: 'error', code: 'UNKNOWN', message: 'ورود کامل نشد.' };
  } catch (err) {
    return { status: 'error', ...describeError(err) };
  }
}

/** Registration for a phone number that has no Telegram account yet. */
export async function signUp(
  phoneNumber: string,
  phoneCodeHash: string,
  firstName: string,
  lastName: string,
): Promise<SignInResult> {
  try {
    const res = await getClient().invoke(
      new Api.auth.SignUp({
        phoneNumber: normalisePhone(phoneNumber),
        phoneCodeHash,
        firstName,
        lastName,
      }),
    );
    persistSession();
    if (res instanceof Api.auth.Authorization && res.user instanceof Api.User) {
      return { status: 'ok', user: toAuthUser(res.user) };
    }
    return { status: 'error', code: 'UNKNOWN', message: 'ثبت‌نام کامل نشد.' };
  } catch (err) {
    return { status: 'error', ...describeError(err) };
  }
}

export async function getMe(): Promise<AuthUser | null> {
  try {
    const me = await getClient().getMe();
    return me instanceof Api.User ? toAuthUser(me) : null;
  } catch {
    return null;
  }
}

/** Accepts "0912…", "+98912…", "۰۹۱۲…" and normalises to E.164-ish digits. */
export function normalisePhone(input: string): string {
  const latin = input.replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
  return latin.replace(/[^\d+]/g, '');
}
