/**
 * Sample data for the UI harness. Shapes mirror src/lib/telegram/types.ts.
 * Dates are relative to "now" so day separators exercise today/yesterday/older.
 */
const now = Math.floor(Date.now() / 1000);
const DAY = 86400;

export const self = { id: '100', firstName: 'مهران', lastName: 'بهنام', username: 'mehran', phone: '989120000000' };

const peer = (id, kind, title, extra = {}) => ({
  id, kind, title,
  isSelf: false, isBot: false, isVerified: false, isForum: false, canSend: true,
  ...extra,
});

export const peers = {
  saved: peer('100', 'user', 'پیام‌های ذخیره‌شده', { isSelf: true }),
  sara: peer('201', 'user', 'سارا کریمی', { username: 'sara_k', status: { kind: 'online' } }),
  ali: peer('202', 'user', 'علی رضایی', { status: { kind: 'offline', wasOnline: now - 3600 } }),
  team: peer('301', 'group', 'تیم توسعه لیلیکا', { membersCount: 14 }),
  news: peer('401', 'channel', 'اخبار فناوری', { membersCount: 128400, isVerified: true, canSend: false }),
  bot: peer('501', 'user', 'ربات پشتیبانی', { isBot: true, username: 'support_bot' }),
};

export const dialogs = [
  { peerId: peers.team.id, peer: peers.team, unreadCount: 3, unreadMentions: 1, pinned: true, muted: false,
    date: now - 120, lastMessage: { id: 9, text: 'استقرار نسخه جدید تمام شد ✅', date: now - 120, outgoing: false, senderName: 'نگار' } },
  { peerId: peers.sara.id, peer: peers.sara, unreadCount: 0, unreadMentions: 0, pinned: false, muted: false,
    date: now - 300, lastMessage: { id: 24, text: 'باشه، فردا صبح می‌بینمت', date: now - 300, outgoing: true } },
  { peerId: peers.news.id, peer: peers.news, unreadCount: 47, unreadMentions: 0, pinned: false, muted: true,
    date: now - 5400, lastMessage: { id: 88, text: 'گزارش جدید درباره پردازنده‌های موبایل', date: now - 5400, outgoing: false, mediaKind: 'photo' } },
  { peerId: peers.ali.id, peer: peers.ali, unreadCount: 0, unreadMentions: 0, pinned: false, muted: false,
    date: now - DAY, lastMessage: { id: 12, text: '🎤 پیام صوتی', date: now - DAY, outgoing: false, mediaKind: 'voice' } },
  { peerId: peers.saved.id, peer: peers.saved, unreadCount: 0, unreadMentions: 0, pinned: false, muted: false,
    date: now - 2 * DAY, lastMessage: { id: 3, text: 'لینک مستندات MTProto', date: now - 2 * DAY, outgoing: true } },
  { peerId: peers.bot.id, peer: peers.bot, unreadCount: 1, unreadMentions: 0, pinned: false, muted: false,
    date: now - 4 * DAY, lastMessage: { id: 2, text: 'برای شروع /start را بفرست', date: now - 4 * DAY, outgoing: false } },
];

const msg = (id, over) => ({ id, peerId: peers.team.id, text: '', date: now - 100, outgoing: false, ...over });

export const teamMessages = [
  msg(1, { date: now - 2 * DAY - 300, service: 'گروه ساخته شد' }),
  msg(2, { date: now - 2 * DAY, senderId: '203', senderName: 'نگار موسوی', text: 'سلام به همه 👋 کانال جدید تیم اینجاست.' }),
  msg(3, { date: now - DAY - 7200, senderId: '204', senderName: 'رضا امینی',
    text: 'برای اتصال باید useWSS رو true بذاریم، چون مرورگر فقط websocket امن رو قبول می‌کنه.',
    entities: [{ kind: 'code', offset: 17, length: 6 }] }),
  msg(4, { date: now - DAY - 7000, outgoing: true, senderId: self.id, text: 'درسته. تستش کردم، جواب می‌ده.' }),
  msg(5, { date: now - DAY - 6900, outgoing: true, senderId: self.id, text: 'این هم لاگ کامل:\nconnected → authorized → dialogs' }),
  msg(6, { date: now - 7200, senderId: '203', senderName: 'نگار موسوی',
    text: 'گزارش این هفته', media: { kind: 'document', fileName: 'report-1404-06.pdf', size: 2_418_000, mimeType: 'application/pdf' } }),
  msg(7, { date: now - 5400, senderId: '204', senderName: 'رضا امینی',
    text: 'اسکرین‌شات صفحه ورود', media: { kind: 'photo', width: 480, height: 300 } }),
  msg(8, { date: now - 3600, outgoing: true, senderId: self.id, replyToId: 7,
    text: 'خوب شده! فقط رنگ دکمه رو یک درجه تیره‌تر کن.' }),
  msg(9, { date: now - 1800, senderId: '205', senderName: 'مریم', text: 'رمز سرور استیج: hunter2',
    entities: [{ kind: 'spoiler', offset: 16, length: 7 }] }),
  msg(10, { date: now - 900, senderId: '203', senderName: 'نگار موسوی', forwardedFrom: 'اخبار فناوری',
    text: 'تلگرام از پروتکل MTProto 2.0 استفاده می‌کند.' }),
  msg(11, { date: now - 300, senderId: '204', senderName: 'رضا امینی',
    media: { kind: 'voice', duration: 47, size: 184_000 } }),
  msg(12, { date: now - 120, senderId: '203', senderName: 'نگار موسوی', text: 'استقرار نسخه جدید تمام شد ✅' }),
  msg(13, { date: now - 40, outgoing: true, senderId: self.id, text: 'دمت گرم 🙏', pending: true }),
  msg(14, { date: now - 20, outgoing: true, senderId: self.id, text: 'این یکی نرفت', failed: true }),
];
