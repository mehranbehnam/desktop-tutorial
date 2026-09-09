/**
 * UI-facing view models.
 *
 * The rest of the app never touches raw `Api.*` constructors — everything
 * crossing out of `lib/telegram` is a plain, serialisable object with string
 * ids (GramJS hands back BigInt, which React state and JSON both dislike).
 */

export type PeerKind = 'user' | 'group' | 'channel';

export interface Peer {
  id: string;
  kind: PeerKind;
  title: string;
  username?: string;
  /** Users only. */
  phone?: string;
  isSelf: boolean;
  isBot: boolean;
  isVerified: boolean;
  isForum: boolean;
  /** Set when the account can post — false for read-only channels. */
  canSend: boolean;
  membersCount?: number;
  /** Last-seen text, already localised by the presence formatter. */
  status?: PresenceStatus;
  photoId?: string;
}

export type PresenceStatus =
  | { kind: 'online' }
  | { kind: 'offline'; wasOnline: number | null }
  | { kind: 'recently' }
  | { kind: 'lastWeek' }
  | { kind: 'lastMonth' }
  | { kind: 'longAgo' }
  | { kind: 'unknown' };

export interface Dialog {
  peerId: string;
  peer: Peer;
  unreadCount: number;
  unreadMentions: number;
  pinned: boolean;
  muted: boolean;
  /** Preview line under the chat title. */
  lastMessage: MessagePreview | null;
  date: number;
}

export interface MessagePreview {
  id: number;
  text: string;
  date: number;
  outgoing: boolean;
  senderName?: string;
  mediaKind?: MediaKind;
}

export type MediaKind = 'photo' | 'video' | 'voice' | 'audio' | 'document' | 'sticker' | 'gif' | 'poll' | 'contact' | 'location' | 'unsupported';

export interface MessageMedia {
  kind: MediaKind;
  /** Bytes, when Telegram reports it. */
  size?: number;
  fileName?: string;
  mimeType?: string;
  width?: number;
  height?: number;
  /** Seconds, for audio/video/voice. */
  duration?: number;
  /** Inline base64 thumbnail, available before the full file downloads. */
  thumbUrl?: string;
  /** Emoji a sticker stands for. */
  emoji?: string;
}

export interface Message {
  id: number;
  peerId: string;
  senderId?: string;
  senderName?: string;
  text: string;
  date: number;
  editDate?: number;
  outgoing: boolean;
  /** Local echo that has not been acknowledged by the server yet. */
  pending?: boolean;
  failed?: boolean;
  media?: MessageMedia;
  replyToId?: number;
  forwardedFrom?: string;
  views?: number;
  /** Service messages ("X joined the group") render as a centred pill. */
  service?: string;
  entities?: TextEntity[];
}

export interface TextEntity {
  kind: 'bold' | 'italic' | 'code' | 'pre' | 'underline' | 'strike' | 'spoiler' | 'url' | 'textUrl' | 'mention' | 'hashtag';
  offset: number;
  length: number;
  url?: string;
}

export interface AuthUser {
  id: string;
  firstName: string;
  lastName?: string;
  username?: string;
  phone?: string;
}

export interface TypingEvent {
  peerId: string;
  userId: string;
  userName: string;
  action: 'typing' | 'recording' | 'uploading';
}
