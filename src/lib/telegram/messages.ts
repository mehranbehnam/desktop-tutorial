/**
 * Message history and sending.
 *
 * History is paged backwards from the newest message (Telegram's own order),
 * then reversed once so the UI can render oldest-first without re-sorting.
 */
import { Api } from 'telegram';
import bigInt from 'big-integer';
import { getClient } from './client';
import type { Message } from './types';
import { toMedia, toEntities, idToString, displayName } from './utils';
import { serviceLabel } from './dialogs';

export interface HistoryPage {
  messages: Message[];
  /** Pass as `offsetId` to load the previous page; null when the top is reached. */
  nextOffsetId: number | null;
}

export async function fetchHistory(
  peerId: string,
  selfId: string,
  limit = 40,
  offsetId = 0,
): Promise<HistoryPage> {
  const client = getClient();
  const entity = await client.getInputEntity(peerId);
  const result = await client.invoke(
    new Api.messages.GetHistory({
      peer: entity,
      offsetId,
      offsetDate: 0,
      addOffset: 0,
      limit,
      maxId: 0,
      minId: 0,
      hash: bigInt(0),
    }),
  );

  if (result instanceof Api.messages.MessagesNotModified) {
    return { messages: [], nextOffsetId: null };
  }

  const names = new Map<string, string>();
  for (const u of result.users) if (u instanceof Api.User) names.set(idToString(u.id), displayName(u));
  for (const c of result.chats) {
    if (c instanceof Api.Chat || c instanceof Api.Channel) names.set(idToString(c.id), c.title);
  }

  const messages = result.messages
    .map((m) => toMessage(m, peerId, selfId, names))
    .filter((m): m is Message => m !== null)
    .reverse();

  const reachedTop = result.messages.length < limit;
  return {
    messages,
    nextOffsetId: reachedTop || messages.length === 0 ? null : messages[0].id,
  };
}

export function toMessage(
  raw: Api.TypeMessage,
  peerId: string,
  selfId: string,
  names?: Map<string, string>,
): Message | null {
  if (raw instanceof Api.MessageEmpty) return null;

  const senderId = raw.fromId instanceof Api.PeerUser ? idToString(raw.fromId.userId) : undefined;
  const channelSender =
    raw.fromId instanceof Api.PeerChannel ? idToString(raw.fromId.channelId) : undefined;
  const from = senderId ?? channelSender;

  const base = {
    id: raw.id,
    peerId,
    senderId: from,
    senderName: from ? names?.get(from) : undefined,
    date: raw.date,
    outgoing: Boolean(raw.out) || (from !== undefined && from === selfId),
  };

  if (raw instanceof Api.MessageService) {
    return { ...base, text: '', service: serviceLabel(raw.action) };
  }

  if (!(raw instanceof Api.Message)) return null;

  let forwardedFrom: string | undefined;
  if (raw.fwdFrom instanceof Api.MessageFwdHeader) {
    forwardedFrom =
      raw.fwdFrom.fromName ??
      (raw.fwdFrom.fromId instanceof Api.PeerUser
        ? names?.get(idToString(raw.fwdFrom.fromId.userId))
        : raw.fwdFrom.fromId instanceof Api.PeerChannel
          ? names?.get(idToString(raw.fwdFrom.fromId.channelId))
          : undefined) ??
      'ناشناس';
  }

  return {
    ...base,
    text: raw.message ?? '',
    editDate: raw.editDate ?? undefined,
    media: toMedia(raw.media),
    replyToId:
      raw.replyTo instanceof Api.MessageReplyHeader ? (raw.replyTo.replyToMsgId ?? undefined) : undefined,
    forwardedFrom,
    views: raw.views ?? undefined,
    entities: toEntities(raw.entities),
  };
}

export interface SendOptions {
  replyTo?: number;
  /** Local id used to reconcile the optimistic bubble with the server's reply. */
  localId: number;
}

export async function sendText(
  peerId: string,
  text: string,
  selfId: string,
  options: SendOptions,
): Promise<Message> {
  const client = getClient();
  const entity = await client.getInputEntity(peerId);
  const sent = await client.sendMessage(entity, {
    message: text,
    replyTo: options.replyTo,
  });
  const mapped = toMessage(sent, peerId, selfId);
  if (mapped) return mapped;
  // sendMessage always resolves to a Message; this is belt-and-braces.
  return {
    id: sent.id,
    peerId,
    text,
    date: Math.floor(Date.now() / 1000),
    outgoing: true,
  };
}

export async function sendFile(
  peerId: string,
  file: File,
  selfId: string,
  caption: string,
  onProgress?: (fraction: number) => void,
): Promise<Message> {
  const client = getClient();
  const entity = await client.getInputEntity(peerId);
  const sent = await client.sendFile(entity, {
    file,
    caption,
    forceDocument: !file.type.startsWith('image/') && !file.type.startsWith('video/'),
    progressCallback: onProgress ? ((p: number) => onProgress(p)) as never : undefined,
  });
  return (
    toMessage(sent, peerId, selfId) ?? {
      id: sent.id,
      peerId,
      text: caption,
      date: Math.floor(Date.now() / 1000),
      outgoing: true,
    }
  );
}

export async function editMessage(peerId: string, messageId: number, text: string): Promise<void> {
  const client = getClient();
  await client.editMessage(await client.getInputEntity(peerId), { message: messageId, text });
}

export async function deleteMessages(
  peerId: string,
  ids: number[],
  forEveryone: boolean,
): Promise<void> {
  const client = getClient();
  await client.deleteMessages(await client.getInputEntity(peerId), ids, { revoke: forEveryone });
}

export async function forwardMessages(
  fromPeerId: string,
  toPeerId: string,
  ids: number[],
): Promise<void> {
  const client = getClient();
  await client.forwardMessages(await client.getInputEntity(toPeerId), {
    messages: ids,
    fromPeer: await client.getInputEntity(fromPeerId),
  });
}

/** Fires the "…is typing" indicator on the other side. Safe to call often. */
export async function setTyping(peerId: string, active: boolean): Promise<void> {
  const client = getClient();
  try {
    await client.invoke(
      new Api.messages.SetTyping({
        peer: await client.getInputEntity(peerId),
        action: active ? new Api.SendMessageTypingAction() : new Api.SendMessageCancelAction(),
      }),
    );
  } catch {
    /* a failed typing ping must never surface to the user */
  }
}

export async function searchInChat(peerId: string, query: string, selfId: string): Promise<Message[]> {
  const client = getClient();
  const res = await client.invoke(
    new Api.messages.Search({
      peer: await client.getInputEntity(peerId),
      q: query,
      filter: new Api.InputMessagesFilterEmpty(),
      minDate: 0,
      maxDate: 0,
      offsetId: 0,
      addOffset: 0,
      limit: 50,
      maxId: 0,
      minId: 0,
      hash: bigInt(0),
    }),
  );
  if (res instanceof Api.messages.MessagesNotModified) return [];
  return res.messages
    .map((m) => toMessage(m, peerId, selfId))
    .filter((m): m is Message => m !== null);
}
