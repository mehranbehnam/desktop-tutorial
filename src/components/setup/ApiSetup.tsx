/**
 * First-run screen for builds that do not bake in api_id / api_hash.
 *
 * Sharing credentials between deployments gets them revoked, so the app asks
 * rather than shipping a default pair.
 */
import { useState, type FormEvent } from 'react';
import { branding, saveCredentials } from '../../config';
import { useAuthStore } from '../../store/authStore';
import { BrandMark } from '../common/BrandMark';

export function ApiSetup() {
  const useCredentials = useAuthStore((s) => s.useCredentials);
  const busy = useAuthStore((s) => s.busy);
  const error = useAuthStore((s) => s.error);

  const [apiId, setApiId] = useState('');
  const [apiHash, setApiHash] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const id = Number(apiId.trim());
    const hash = apiHash.trim();
    if (!Number.isInteger(id) || id <= 0) {
      setLocalError('api_id باید یک عدد باشد.');
      return;
    }
    if (hash.length !== 32) {
      setLocalError('api_hash باید ۳۲ کاراکتر باشد.');
      return;
    }
    setLocalError(null);
    saveCredentials({ apiId: id, apiHash: hash });
    void useCredentials({ apiId: id, apiHash: hash });
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <BrandMark />
          <h1>{branding.name}</h1>
          <p>برای شروع، کلید برنامه‌نویسی تلگرام خودت را وارد کن.</p>
        </div>

        <div className="field">
          <label htmlFor="api-id">api_id</label>
          <input
            id="api-id"
            className="ltr"
            inputMode="numeric"
            autoComplete="off"
            value={apiId}
            onChange={(e) => setApiId(e.target.value)}
            placeholder="1234567"
          />
        </div>

        <div className="field">
          <label htmlFor="api-hash">api_hash</label>
          <input
            id="api-hash"
            className="ltr"
            autoComplete="off"
            value={apiHash}
            onChange={(e) => setApiHash(e.target.value)}
            placeholder="0123456789abcdef0123456789abcdef"
          />
          <span className="hint">
            از <a href="https://my.telegram.org" target="_blank" rel="noreferrer">my.telegram.org</a>{' '}
            → API development tools بگیر. این کلید فقط روی همین مرورگر ذخیره می‌شود.
          </span>
        </div>

        {(localError || error) && <div className="form-error">{localError ?? error}</div>}

        <button className="button" type="submit" disabled={busy}>
          {busy ? 'در حال اتصال…' : 'ادامه'}
        </button>
      </form>
    </div>
  );
}
