/**
 * Real-time update bridge.
 *
 * GramJS emits raw MTProto updates; this module translates the handful the UI
 * cares about into typed callbacks and nothing else. Anything unhandled is
 * dropped on purpose — the chat list refetch is the safety net.
 */
import { Api } from 'telegram';
import { NewMessage, type NewMessageEvent } from 'telegram/events';
import { EditedMessage, type EditedMessageEvent } from 'telegram/events/EditedMessage';
import { DeletedMessage, type DeletedMessageEvent } from 'telegram/events/DeletedMessage';
import { getClient, persistSession } from './client';
import { toMessage } from './messages';
import { idToString, peerIdOf } from './utils';
import type { Message, PresenceStatus, TypingEvent } from './types';

export interface UpdateHandlers {
  onMessage: (message: Message) => void;
  onMessageEdited: (message: Message) => void;
  onMessagesDeleted: (peerId: string | null, ids: number[]) => void;
  onTyping: (event: TypingEvent) => void;
  onPresence: (userId: string, status: PresenceStatus) => void;
  onReadOutbox: (peerId: string, maxId: number) => void;
  onConnectionChange: (connected: boolean) => void;
}

type Unsubscribe = () => void;

export function subscribe(selfId: string, handlers: UpdateHandlers): Unsubscribe {
  const client = getClient();

  const onNew = async (event: NewMessageEvent) => {
    const peerId = peerIdOf(event.message.peerId);
    const mapped = toMessage(event.message, peerId, selfId);
    if (mapped) {
      mapped.senderName = await senderNameOf(event.message);
      handlers.onMessage(mapped);
    }
    persistSession();
  };

  const onEdit = async (event: EditedMessageEvent) => {
    const peerId = peerIdOf(event.message.peerId);
    const mapped = toMessage(event.message, peerId, selfId);
    if (mapped) handlers.onMessageEdited(mapped);
  };

  const onDelete = (event: DeletedMessageEvent) => {
    // `peer` is absent for private-chat deletions: Telegram sends those without
    // a peer and every open chat has to reconcile against the id list itself.
    const peer = event.peer as unknown;
    const peerId =
      peer instanceof Api.PeerUser || peer instanceof Api.PeerChat || peer instanceof Api.PeerChannel
        ? peerIdOf(peer)
        : null;
    handlers.onMessagesDeleted(peerId, event.deletedIds ?? []);
  };

  // Raw updates cover the things GramJS has no sugar for.
  const onRaw = (update: Api.TypeUpdate) => {
    if (update instanceof Api.UpdateUserTyping || update instanceof Api.UpdateChatUserTyping) {
      const peerId =
        update instanceof Api.UpdateUserTyping
          ? idToString(update.userId)
          : idToString(update.chatId);
      const userId =
        update instanceof Api.UpdateUserTyping
          ? idToString(update.userId)
          : update.fromId instanceof Api.PeerUser
            ? idToString(update.fromId.userId)
            : '';
      handlers.onTyping({
        peerId,
        userId,
        userName: '',
        action: typingActionOf(update.action),
      });
      return;
    }

    if (update instanceof Api.UpdateChannelUserTyping) {
      handlers.onTyping({
        peerId: idToString(update.channelId),
        userId: update.fromId instanceof Api.PeerUser ? idToString(update.fromId.userId) : '',
        userName: '',
        action: typingActionOf(update.action),
      });
      return;
    }

    if (update instanceof Api.UpdateUserStatus) {
      handlers.onPresence(idToString(update.userId), presenceOf(update.status));
      return;
    }

    if (update instanceof Api.UpdateReadHistoryOutbox) {
      handlers.onReadOutbox(peerIdOf(update.peer), update.maxId);
    }
  };

  client.addEventHandler(onNew, new NewMessage({}));
  client.addEventHandler(onEdit, new EditedMessage({}));
  client.addEventHandler(onDelete, new DeletedMessage({}));
  client.addEventHandler(onRaw);

  // GramJS surfaces socket state through these two events.
  const connected = () => handlers.onConnectionChange(true);
  const disconnected = () => handlers.onConnectionChange(false);
  const socket = client as unknown as {
    on?: (event: string, cb: () => void) => void;
    off?: (event: string, cb: () => void) => void;
  };
  socket.on?.('connected', connected);
  socket.on?.('disconnected', disconnected);

  return () => {
    client.removeEventHandler(onNew, new NewMessage({}));
    client.removeEventHandler(onEdit, new EditedMessage({}));
    client.removeEventHandler(onDelete, new DeletedMessage({}));
    socket.off?.('connected', connected);
    socket.off?.('disconnected', disconnected);
  };
}

async function senderNameOf(message: Api.Message): Promise<string | undefined> {
  try {
    const sender = await message.getSender();
    if (sender instanceof Api.User) {
      return [sender.firstName, sender.lastName].filter(Boolean).join(' ') || sender.username;
    }
    if (sender instanceof Api.Channel || sender instanceof Api.Chat) return sender.title;
  } catch {
    /* sender may not be cached; the bubble falls back to the peer title */
  }
  return undefined;
}

function typingActionOf(action: Api.TypeSendMessageAction): TypingEvent['action'] {
  if (action instanceof Api.SendMessageRecordAudioAction) return 'recording';
  if (
    action instanceof Api.SendMessageUploadPhotoAction ||
    action instanceof Api.SendMessageUploadDocumentAction ||
    action instanceof Api.SendMessageUploadVideoAction
  ) {
    return 'uploading';
  }
  return 'typing';
}

function presenceOf(status: Api.TypeUserStatus): PresenceStatus {
  if (status instanceof Api.UserStatusOnline) return { kind: 'online' };
  if (status instanceof Api.UserStatusOffline)
    return { kind: 'offline', wasOnline: status.wasOnline ?? null };
  if (status instanceof Api.UserStatusRecently) return { kind: 'recently' };
  if (status instanceof Api.UserStatusLastWeek) return { kind: 'lastWeek' };
  if (status instanceof Api.UserStatusLastMonth) return { kind: 'lastMonth' };
  return { kind: 'unknown' };
}
