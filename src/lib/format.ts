/**
 * Presentation helpers: dates, sizes, presence text.
 *
 * Persian digits are used everywhere in the UI, so every number that reaches a
 * label goes through `toFaDigits`.
 */
import type { PresenceStatus } from './telegram/types';

const FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

export function toFaDigits(input: string | number): string {
  return String(input).replace(/\d/g, (d) => FA_DIGITS[Number(d)]);
}

const timeFormatter = new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit' });
const dayFormatter = new Intl.DateTimeFormat('fa-IR', { weekday: 'long' });
const dateFormatter = new Intl.DateTimeFormat('fa-IR', { day: 'numeric', month: 'long' });
const fullFormatter = new Intl.DateTimeFormat('fa-IR', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

/** Unix seconds -> "۱۴:۳۲". */
export function formatTime(unixSeconds: number): string {
  return timeFormatter.format(new Date(unixSeconds * 1000));
}

/** Chat-list stamp: time today, weekday this week, otherwise a date. */
export function formatStamp(unixSeconds: number): string {
  if (!unixSeconds) return '';
  const date = new Date(unixSeconds * 1000);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return timeFormatter.format(date);

  const days = (now.getTime() - date.getTime()) / 86_400_000;
  if (days < 7) return dayFormatter.format(date);
  if (date.getFullYear() === now.getFullYear()) return dateFormatter.format(date);
  return fullFormatter.format(date);
}

/** Separator pill between days in the message list. */
export function formatDaySeparator(unixSeconds: number): string {
  const date = new Date(unixSeconds * 1000);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return 'امروز';
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (date.toDateString() === yesterday.toDateString()) return 'دیروز';
  return fullFormatter.format(date);
}

export function isSameDay(a: number, b: number): boolean {
  return new Date(a * 1000).toDateString() === new Date(b * 1000).toDateString();
}

export function formatSize(bytes: number | undefined): string {
  if (!bytes) return '';
  const units = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? String(Math.round(value)) : value.toFixed(1);
  return `${toFaDigits(rounded)} ${units[unit]}`;
}

export function formatDuration(seconds: number | undefined): string {
  if (!seconds) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return toFaDigits(`${m}:${String(s).padStart(2, '0')}`);
}

export function formatPresence(status: PresenceStatus | undefined): string {
  if (!status) return '';
  switch (status.kind) {
    case 'online':
      return 'آنلاین';
    case 'recently':
      return 'اخیراً آنلاین بوده';
    case 'lastWeek':
      return 'در هفته گذشته آنلاین بوده';
    case 'lastMonth':
      return 'در ماه گذشته آنلاین بوده';
    case 'offline':
      return status.wasOnline ? `آخرین بازدید ${formatStamp(status.wasOnline)}` : 'آفلاین';
    default:
      return '';
  }
}

export function formatCount(count: number | undefined, noun: string): string {
  if (count === undefined) return '';
  return `${toFaDigits(count)} ${noun}`;
}

/** Deterministic avatar colour so the same peer always gets the same swatch. */
const AVATAR_COLORS = [
  'linear-gradient(135deg,#e17076,#d05a5f)',
  'linear-gradient(135deg,#7bc862,#5fae48)',
  'linear-gradient(135deg,#e5ca77,#d4b45a)',
  'linear-gradient(135deg,#65aadd,#4a90c9)',
  'linear-gradient(135deg,#a695e7,#8a76d8)',
  'linear-gradient(135deg,#ee7aae,#dd5f97)',
  'linear-gradient(135deg,#6ec9cb,#4fb3b5)',
];

export function avatarColor(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

export function initials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '؟';
  if (words.length === 1) return words[0].slice(0, 1);
  return words[0].slice(0, 1) + words[1].slice(0, 1);
}
