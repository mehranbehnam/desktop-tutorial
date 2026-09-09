/**
 * Phone -> code -> (password | sign-up) wizard.
 *
 * Each step is a tiny form; the store owns every transition so a reload during
 * login lands somewhere sane rather than half-way through.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { branding } from '../../config';
import { useAuthStore, type Stage } from '../../store/authStore';
import { toFaDigits } from '../../lib/format';
import { credentialsAreFixed } from '../../config';
import { BrandMark } from '../common/BrandMark';

const STEP_ORDER: Stage[] = ['phone', 'code', 'password'];

export function AuthScreen() {
  const stage = useAuthStore((s) => s.stage);
  const busy = useAuthStore((s) => s.busy);
  const error = useAuthStore((s) => s.error);

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-brand">
          <BrandMark />
          <h1>{branding.name}</h1>
          <p>{subtitleFor(stage)}</p>
        </div>

        {stage === 'offline' && <OfflineStep busy={busy} />}
        {stage === 'phone' && <PhoneStep busy={busy} />}
        {stage === 'code' && <CodeStep busy={busy} />}
        {stage === 'password' && <PasswordStep busy={busy} />}
        {stage === 'signUp' && <SignUpStep busy={busy} />}

        {error && <div className="form-error">{error}</div>}

        {stage !== 'offline' && (
        <div className="auth-steps" aria-hidden="true">
          {STEP_ORDER.map((step) => (
            <span key={step} className={STEP_ORDER.indexOf(stage) >= STEP_ORDER.indexOf(step) ? 'done' : ''} />
          ))}
        </div>
        )}
      </div>
    </div>
  );
}

function subtitleFor(stage: Stage): string {
  switch (stage) {
    case 'offline':
      return 'اتصال به سرورهای تلگرام برقرار نشد.';
    case 'phone':
      return 'شماره موبایلت را وارد کن تا کد تأیید برایت بفرستیم.';
    case 'code':
      return 'کدی که تلگرام فرستاده را وارد کن.';
    case 'password':
      return 'حساب تو تأیید دومرحله‌ای دارد.';
    case 'signUp':
      return 'این شماره حساب ندارد؛ بیا بسازیم.';
    default:
      return '';
  }
}

function OfflineStep({ busy }: { busy: boolean }) {
  const boot = useAuthStore((s) => s.boot);
  const resetCredentials = useAuthStore((s) => s.resetCredentials);
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9em' }}>
        نشست تو پاک نشده است. وقتی اینترنت وصل شد دوباره تلاش کن.
      </p>
      <button className="button" type="button" onClick={() => void boot()} disabled={busy}>
        {busy ? 'در حال تلاش…' : 'تلاش دوباره'}
      </button>
      {!credentialsAreFixed() && (
        <button className="button ghost" type="button" onClick={resetCredentials}>
          تغییر api_id / api_hash
        </button>
      )}
    </div>
  );
}

function PhoneStep({ busy }: { busy: boolean }) {
  const submitPhone = useAuthStore((s) => s.submitPhone);
  const resetCredentials = useAuthStore((s) => s.resetCredentials);
  const saved = useAuthStore((s) => s.phone);
  const [phone, setPhone] = useState(saved);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (phone.trim().length >= 6) void submitPhone(phone);
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
      <div className="field">
        <label htmlFor="phone">شماره موبایل</label>
        <input
          ref={inputRef}
          id="phone"
          className="ltr"
          type="tel"
          autoComplete="tel"
          dir="ltr"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+98 912 000 0000"
        />
        <span className="hint">با کد کشور وارد کن، مثلاً ‎+98‎ برای ایران.</span>
      </div>
      <button className="button" type="submit" disabled={busy || phone.trim().length < 6}>
        {busy ? 'در حال ارسال کد…' : 'ارسال کد'}
      </button>
      {!credentialsAreFixed() && (
        <button className="button ghost" type="button" onClick={resetCredentials} disabled={busy}>
          تغییر api_id / api_hash
        </button>
      )}
    </form>
  );
}

function CodeStep({ busy }: { busy: boolean }) {
  const submitCode = useAuthStore((s) => s.submitCode);
  const back = useAuthStore((s) => s.back);
  const phone = useAuthStore((s) => s.phone);
  const viaApp = useAuthStore((s) => s.codeViaApp);
  const [code, setCode] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  // Telegram codes are five digits; submit as soon as we have them.
  useEffect(() => {
    if (code.replace(/\D/g, '').length === 5 && !busy) void submitCode(code);
  }, [code, busy, submitCode]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (code.trim()) void submitCode(code);
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
      <div className="field">
        <label htmlFor="code">کد تأیید</label>
        <input
          ref={inputRef}
          id="code"
          className="ltr code-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          dir="ltr"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          placeholder="۱۲۳۴۵"
        />
        <span className="hint">
          {viaApp
            ? 'کد در برنامه تلگرام روی دستگاه‌های دیگرت فرستاده شد.'
            : `کد پیامکی به ${toFaDigits(phone)} فرستاده شد.`}
        </span>
      </div>
      <button className="button" type="submit" disabled={busy || code.length < 4}>
        {busy ? 'در حال بررسی…' : 'تأیید'}
      </button>
      <button className="button ghost" type="button" onClick={back} disabled={busy}>
        تغییر شماره
      </button>
    </form>
  );
}

function PasswordStep({ busy }: { busy: boolean }) {
  const submitPassword = useAuthStore((s) => s.submitPassword);
  const back = useAuthStore((s) => s.back);
  const hint = useAuthStore((s) => s.passwordHint);
  const [password, setPassword] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password) void submitPassword(password);
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
      <div className="field">
        <label htmlFor="password">رمز دومرحله‌ای</label>
        <input
          ref={inputRef}
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {hint && <span className="hint">راهنما: {hint}</span>}
      </div>
      <button className="button" type="submit" disabled={busy || !password}>
        {busy ? 'در حال بررسی…' : 'ورود'}
      </button>
      <button className="button ghost" type="button" onClick={back} disabled={busy}>
        بازگشت
      </button>
    </form>
  );
}

function SignUpStep({ busy }: { busy: boolean }) {
  const submitSignUp = useAuthStore((s) => s.submitSignUp);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');

  function submit(event: FormEvent) {
    event.preventDefault();
    if (firstName.trim()) void submitSignUp(firstName.trim(), lastName.trim());
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 14 }}>
      <div className="field">
        <label htmlFor="first-name">نام</label>
        <input id="first-name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="last-name">نام خانوادگی (اختیاری)</label>
        <input id="last-name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
      </div>
      <button className="button" type="submit" disabled={busy || !firstName.trim()}>
        {busy ? 'در حال ساخت حساب…' : 'ساخت حساب'}
      </button>
    </form>
  );
}
