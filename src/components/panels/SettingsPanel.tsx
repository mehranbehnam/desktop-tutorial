/**
 * Appearance + account settings.
 */
import { useState } from 'react';
import { Icon } from '../common/Icon';
import { branding, credentialsAreFixed } from '../../config';
import { useAuthStore } from '../../store/authStore';
import { useUiStore, type Accent, type Theme } from '../../store/uiStore';
import { toFaDigits } from '../../lib/format';

const THEMES: { value: Theme; label: string }[] = [
  { value: 'dark', label: 'تیره' },
  { value: 'light', label: 'روشن' },
  { value: 'system', label: 'مثل سیستم' },
];

const ACCENTS: { value: Accent; color: string }[] = [
  { value: 'teal', color: '#2ea6a0' },
  { value: 'violet', color: '#7c6bd8' },
  { value: 'rose', color: '#d9557f' },
  { value: 'amber', color: '#d99a2b' },
  { value: 'blue', color: '#4a90d9' },
];

export function SettingsPanel() {
  const user = useAuthStore((s) => s.user);
  const logOut = useAuthStore((s) => s.logOut);
  const resetCredentials = useAuthStore((s) => s.resetCredentials);
  const ui = useUiStore();
  const [confirming, setConfirming] = useState(false);

  return (
    <aside className="panel">
      <header className="panel-header">
        <button className="icon-button" onClick={() => ui.openPanel('none')} aria-label="بستن" type="button">
          <Icon name="close" />
        </button>
        <h2>تنظیمات</h2>
      </header>

      <div className="panel-hero">
        <div
          className="avatar"
          style={{ width: 84, height: 84, fontSize: 32, background: 'linear-gradient(135deg,var(--accent),var(--accent-strong))' }}
        >
          {(user?.firstName ?? '؟').slice(0, 1)}
        </div>
        <div className="name">{[user?.firstName, user?.lastName].filter(Boolean).join(' ') || '—'}</div>
        <div className="status" dir="ltr">
          {user?.username ? `@${user.username}` : user?.phone ? `+${toFaDigits(user.phone)}` : ''}
        </div>
      </div>

      <div className="panel-section">
        <div className="section-label" style={{ padding: '4px 0' }}>ظاهر</div>

        <div className="panel-row" style={{ display: 'block' }}>
          <div className="label" style={{ marginBottom: 8 }}>پوسته</div>
          <div className="chip-row">
            {THEMES.map((theme) => (
              <button
                key={theme.value}
                className={ui.theme === theme.value ? 'chip selected' : 'chip'}
                onClick={() => ui.set('theme', theme.value)}
                type="button"
              >
                {theme.label}
              </button>
            ))}
          </div>
        </div>

        <div className="panel-row" style={{ display: 'block' }}>
          <div className="label" style={{ marginBottom: 8 }}>رنگ اصلی</div>
          <div className="swatch-row">
            {ACCENTS.map((accent) => (
              <button
                key={accent.value}
                className={ui.accent === accent.value ? 'swatch selected' : 'swatch'}
                style={{ background: accent.color }}
                onClick={() => ui.set('accent', accent.value)}
                aria-label={accent.value}
                type="button"
              />
            ))}
          </div>
        </div>

        <div className="panel-row">
          <span>اندازه متن</span>
          <input
            type="range"
            min={0.85}
            max={1.3}
            step={0.05}
            value={ui.fontScale}
            onChange={(e) => ui.set('fontScale', Number(e.target.value))}
            aria-label="اندازه متن"
          />
        </div>

        <div className="section-label" style={{ padding: '12px 0 4px' }}>گفتگو</div>

        <div className="panel-row">
          <span>ارسال با Enter</span>
          <button
            className={ui.sendOnEnter ? 'switch on' : 'switch'}
            onClick={() => ui.set('sendOnEnter', !ui.sendOnEnter)}
            aria-label="ارسال با اینتر"
            type="button"
          />
        </div>

        <div className="panel-row">
          <span>نمایش عکس فرستنده در گروه‌ها</span>
          <button
            className={ui.showAvatarsInGroups ? 'switch on' : 'switch'}
            onClick={() => ui.set('showAvatarsInGroups', !ui.showAvatarsInGroups)}
            aria-label="نمایش عکس فرستنده"
            type="button"
          />
        </div>

        <div className="section-label" style={{ padding: '12px 0 4px' }}>حساب</div>

        {!credentialsAreFixed() && (
          <button
            className="panel-row"
            onClick={resetCredentials}
            type="button"
          >
            <span>تغییر api_id / api_hash</span>
            <Icon name="edit" size={18} />
          </button>
        )}

        <button className="panel-row danger-text" onClick={() => setConfirming(true)} type="button">
          <span>خروج از حساب</span>
          <Icon name="logout" size={18} />
        </button>

        <p style={{ color: 'var(--text-tertiary)', fontSize: '0.8em', marginTop: 20 }}>
          {branding.name} نسخه {toFaDigits(branding.version)} — بر پایه پروتکل MTProto تلگرام
        </p>
      </div>

      {confirming && (
        <div className="overlay" onClick={() => setConfirming(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>خروج از حساب</h3>
            <p>نشست این دستگاه از تلگرام حذف می‌شود و باید دوباره وارد شوی.</p>
            <div className="dialog-actions">
              <button className="button ghost" onClick={() => setConfirming(false)} type="button">
                انصراف
              </button>
              <button className="button danger" onClick={() => void logOut()} type="button">
                خروج
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
