/**
 * Chat list: fetching, searching, and the small mutations the sidebar offers.
 */
import { Api } from 'telegram';
import bigInt from 'big-integer';
import { getClient } from './client';
import type { Dialog, Peer, MessagePreview } from './types';
import { toPeer, idToString, mediaKindOf, displayName } from './utils';

function previewOf(message: Api.Message | undefined, selfId: string): MessagePreview | null {
  if (!message) return null;
  const kind = mediaKindOf(message.media);
  let text = message.message ?? '';
  if (!text && kind) text = mediaLabel(kind);
  if (message.action) text = serviceLabel(message.action);

  const fromId = message.fromId ? idToString((message.fromId as Api.PeerUser).userId) : undefined;
  return {
    id: message.id,
    text,
    date: message.date,
    outgoing: Boolean(message.out) || fromId === selfId,
    mediaKind: kind,
  };
}

export function mediaLabel(kind: string): string {
  switch (kind) {
    case 'photo': return '🖼 عکس';
    case 'video': return '🎬 ویدیو';
    case 'voice': return '🎤 پیام صوتی';
    case 'audio': return '🎵 موسیقی';
    case 'sticker': return '😀 استیکر';
    case 'gif': return '🎞 گیف';
    case 'document': return '📎 فایل';
    case 'poll': return '📊 نظرسنجی';
    case 'contact': return '👤 مخاطب';
    case 'location': return '📍 موقعیت';
    default: return 'پیام';
  }
}

export function serviceLabel(action: Api.TypeMessageAction): string {
  if (action instanceof Api.MessageActionChatCreate) return 'گروه ساخته شد';
  if (action instanceof Api.MessageActionChatAddUser) return 'کاربر به گروه اضافه شد';
  if (action instanceof Api.MessageActionChatDeleteUser) return 'کاربر از گروه خارج شد';
  if (action instanceof Api.MessageActionChatJoinedByLink) return 'با لینک به گروه پیوست';
  if (action instanceof Api.MessageActionChatEditTitle) return `نام گروه به «${action.title}» تغییر کرد`;
  if (action instanceof Api.MessageActionChatEditPhoto) return 'عکس گروه تغییر کرد';
  if (action instanceof Api.MessageActionPinMessage) return 'یک پیام سنجاق شد';
  if (action instanceof Api.MessageActionPhoneCall) return '📞 تماس';
  if (action instanceof Api.MessageActionContactSignUp) return 'به لیلیکا پیوست';
  return 'رویداد گفتگو';
}

export interface DialogPage {
  dialogs: Dialog[];
  /** Feed back into `fetchDialogs` to page further down the list. */
  cursor: { offsetDate: number; offsetId: number; offsetPeer: Api.TypeInputPeer } | null;
}

export async function fetchDialogs(
  selfId: string,
  limit = 50,
  cursor?: DialogPage['cursor'],
): Promise<DialogPage> {
  const client = getClient();
  const result = await client.invoke(
    new Api.messages.GetDialogs({
      offsetDate: cursor?.offsetDate ?? 0,
      offsetId: cursor?.offsetId ?? 0,
      offsetPeer: cursor?.offsetPeer ?? new Api.InputPeerEmpty(),
      limit,
      hash: bigInt(0),
    }),
  );

  if (result instanceof Api.messages.DialogsNotModified) return { dialogs: [], cursor: null };

  const entities = new Map<string, Peer>();
  for (const u of result.users) {
    const p = toPeer(u);
    if (p) entities.set(`user:${p.id}`, p);
  }
  for (const c of result.chats) {
    const p = toPeer(c);
    if (p) entities.set(`chat:${p.id}`, p);
  }

  const messages = new Map<string, Api.Message>();
  for (const m of result.messages) {
    if (m instanceof Api.Message || m instanceof Api.MessageService) {
      messages.set(`${peerKeyOf(m.peerId)}:${m.id}`, m as Api.Message);
    }
  }

  const dialogs: Dialog[] = [];
  for (const d of result.dialogs) {
    if (!(d instanceof Api.Dialog)) continue;
    const key = peerKeyOf(d.peer);
    const peer = entities.get(key);
    if (!peer) continue;

    dialogs.push({
      peerId: peer.id,
      peer,
      unreadCount: d.unreadCount,
      unreadMentions: d.unreadMentionsCount,
      pinned: Boolean(d.pinned),
      muted: isMuted(d.notifySettings),
      lastMessage: previewOf(messages.get(`${key}:${d.topMessage}`), selfId),
      date: messages.get(`${key}:${d.topMessage}`)?.date ?? 0,
    });
  }

  dialogs.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.date - a.date);

  const last = result.dialogs.at(-1);
  const more =
    result instanceof Api.messages.DialogsSlice && last instanceof Api.Dialog && dialogs.length > 0;

  return {
    dialogs,
    cursor: more
      ? {
          offsetDate: dialogs.at(-1)!.date,
          offsetId: (last as Api.Dialog).topMessage,
          offsetPeer: await client.getInputEntity(dialogs.at(-1)!.peerId),
        }
      : null,
  };
}

function peerKeyOf(peer: Api.TypePeer): string {
  if (peer instanceof Api.PeerUser) return `user:${idToString(peer.userId)}`;
  if (peer instanceof Api.PeerChat) return `chat:${idToString(peer.chatId)}`;
  if (peer instanceof Api.PeerChannel) return `chat:${idToString(peer.channelId)}`;
  return '';
}

function isMuted(settings: Api.TypePeerNotifySettings): boolean {
  if (!(settings instanceof Api.PeerNotifySettings)) return false;
  if (settings.silent) return true;
  const until = settings.muteUntil ?? 0;
  return until > Math.floor(Date.now() / 1000);
}

/** Global search across chat titles, usernames and message text. */
export async function search(query: string, limit = 30): Promise<{ peers: Peer[]; messages: Peer[] }> {
  const client = getClient();
  const trimmed = query.trim();
  if (!trimmed) return { peers: [], messages: [] };

  const res = await client.invoke(new Api.contacts.Search({ q: trimmed, limit }));
  const peers: Peer[] = [];
  for (const u of res.users) {
    const p = toPeer(u);
    if (p) peers.push(p);
  }
  for (const c of res.chats) {
    const p = toPeer(c);
    if (p) peers.push(p);
  }
  return { peers, messages: [] };
}

export async function resolvePeer(idOrUsername: string): Promise<Peer | null> {
  try {
    const entity = await getClient().getEntity(idOrUsername);
    return toPeer(entity as Api.User | Api.Chat | Api.Channel);
  } catch {
    return null;
  }
}

export async function togglePin(peerId: string, pinned: boolean): Promise<void> {
  const client = getClient();
  await client.invoke(
    new Api.messages.ToggleDialogPin({
      peer: new Api.InputDialogPeer({ peer: await client.getInputEntity(peerId) }),
      pinned,
    }),
  );
}

export async function toggleMute(peerId: string, muted: boolean): Promise<void> {
  const client = getClient();
  await client.invoke(
    new Api.account.UpdateNotifySettings({
      peer: new Api.InputNotifyPeer({ peer: await client.getInputEntity(peerId) }),
      settings: new Api.InputPeerNotifySettings({
        muteUntil: muted ? Math.floor(Date.now() / 1000) + 10 * 365 * 24 * 3600 : 0,
      }),
    }),
  );
}

export async function markRead(peerId: string, maxId: number): Promise<void> {
  const client = getClient();
  const input = await client.getInputEntity(peerId);
  if (input instanceof Api.InputPeerChannel) {
    await client.invoke(
      new Api.channels.ReadHistory({
        channel: new Api.InputChannel({ channelId: input.channelId, accessHash: input.accessHash }),
        maxId,
      }),
    );
  } else {
    await client.invoke(new Api.messages.ReadHistory({ peer: input, maxId }));
  }
}

/** Full profile for the right-hand panel: bio, member count, common chats. */
export async function fetchFullPeer(peerId: string): Promise<{ about?: string; membersCount?: number }> {
  const client = getClient();
  try {
    const entity = await client.getEntity(peerId);
    if (entity instanceof Api.User) {
      const full = await client.invoke(
        new Api.users.GetFullUser({ id: await client.getInputEntity(peerId) }),
      );
      return { about: full.fullUser.about ?? undefined };
    }
    if (entity instanceof Api.Channel) {
      const full = await client.invoke(
        new Api.channels.GetFullChannel({ channel: await client.getInputEntity(peerId) }),
      );
      const chatFull = full.fullChat;
      return {
        about: chatFull instanceof Api.ChannelFull ? chatFull.about : undefined,
        membersCount: chatFull instanceof Api.ChannelFull ? chatFull.participantsCount : undefined,
      };
    }
    if (entity instanceof Api.Chat) {
      const full = await client.invoke(new Api.messages.GetFullChat({ chatId: entity.id }));
      const chatFull = full.fullChat;
      return { about: chatFull instanceof Api.ChatFull ? chatFull.about : undefined };
    }
  } catch {
    /* profile is best-effort */
  }
  return {};
}

export { displayName };
