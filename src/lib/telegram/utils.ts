/**
 * Conversions between GramJS entities and the plain view models in `types.ts`.
 */
import { Api } from 'telegram';
import type { Peer, PeerKind, PresenceStatus, MediaKind, MessageMedia, TextEntity } from './types';

/** GramJS hands back BigInteger | number | string depending on the call site. */
export function idToString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return String(value);
}

export function peerIdOf(peer: Api.TypePeer): string {
  if (peer instanceof Api.PeerUser) return idToString(peer.userId);
  if (peer instanceof Api.PeerChat) return idToString(peer.chatId);
  if (peer instanceof Api.PeerChannel) return idToString(peer.channelId);
  return '';
}

function statusOf(status?: Api.TypeUserStatus): PresenceStatus {
  if (!status) return { kind: 'unknown' };
  if (status instanceof Api.UserStatusOnline) return { kind: 'online' };
  if (status instanceof Api.UserStatusOffline) return { kind: 'offline', wasOnline: status.wasOnline ?? null };
  if (status instanceof Api.UserStatusRecently) return { kind: 'recently' };
  if (status instanceof Api.UserStatusLastWeek) return { kind: 'lastWeek' };
  if (status instanceof Api.UserStatusLastMonth) return { kind: 'lastMonth' };
  return { kind: 'unknown' };
}

export function displayName(user: Api.User): string {
  const parts = [user.firstName, user.lastName].filter(Boolean);
  const name = parts.join(' ').trim();
  if (name) return name;
  if (user.username) return `@${user.username}`;
  if (user.phone) return `+${user.phone}`;
  return 'کاربر بی‌نام';
}

/**
 * Normalises a user / chat / channel into the single `Peer` shape the UI uses.
 * Returns null for entities we cannot render (deleted chats, empty peers).
 */
export function toPeer(entity: Api.TypeUser | Api.TypeChat | undefined): Peer | null {
  if (!entity) return null;

  if (entity instanceof Api.User) {
    return {
      id: idToString(entity.id),
      kind: 'user',
      title: entity.self ? 'پیام‌های ذخیره‌شده' : displayName(entity),
      username: entity.username ?? undefined,
      phone: entity.phone ?? undefined,
      isSelf: Boolean(entity.self),
      isBot: Boolean(entity.bot),
      isVerified: Boolean(entity.verified),
      isForum: false,
      canSend: !entity.deleted,
      status: statusOf(entity.status),
      photoId: entity.photo instanceof Api.UserProfilePhoto ? idToString(entity.photo.photoId) : undefined,
    };
  }

  if (entity instanceof Api.Chat) {
    return {
      id: idToString(entity.id),
      kind: 'group',
      title: entity.title,
      isSelf: false,
      isBot: false,
      isVerified: false,
      isForum: false,
      canSend: !entity.left && !entity.deactivated && !entity.defaultBannedRights?.sendMessages,
      membersCount: entity.participantsCount,
      photoId: entity.photo instanceof Api.ChatPhoto ? idToString(entity.photo.photoId) : undefined,
    };
  }

  if (entity instanceof Api.Channel) {
    // A "channel" in MTProto is either a broadcast channel or a supergroup.
    const kind: PeerKind = entity.megagroup ? 'group' : 'channel';
    const canSend = entity.megagroup
      ? !entity.defaultBannedRights?.sendMessages && !entity.left
      : Boolean(entity.creator || entity.adminRights?.postMessages);
    return {
      id: idToString(entity.id),
      kind,
      title: entity.title,
      username: entity.username ?? undefined,
      isSelf: false,
      isBot: false,
      isVerified: Boolean(entity.verified),
      isForum: Boolean(entity.forum),
      canSend,
      membersCount: entity.participantsCount ?? undefined,
      photoId: entity.photo instanceof Api.ChatPhoto ? idToString(entity.photo.photoId) : undefined,
    };
  }

  return null;
}

export function mediaKindOf(media: Api.TypeMessageMedia | undefined): MediaKind | undefined {
  if (!media) return undefined;
  if (media instanceof Api.MessageMediaPhoto) return 'photo';
  if (media instanceof Api.MessageMediaPoll) return 'poll';
  if (media instanceof Api.MessageMediaContact) return 'contact';
  if (media instanceof Api.MessageMediaGeo || media instanceof Api.MessageMediaGeoLive) return 'location';
  if (media instanceof Api.MessageMediaDocument) {
    const doc = media.document;
    if (!(doc instanceof Api.Document)) return 'unsupported';
    const attrs = doc.attributes;
    if (attrs.some((a) => a instanceof Api.DocumentAttributeSticker)) return 'sticker';
    if (attrs.some((a) => a instanceof Api.DocumentAttributeAnimated)) return 'gif';
    const audio = attrs.find((a): a is Api.DocumentAttributeAudio => a instanceof Api.DocumentAttributeAudio);
    if (audio) return audio.voice ? 'voice' : 'audio';
    if (attrs.some((a) => a instanceof Api.DocumentAttributeVideo)) return 'video';
    return 'document';
  }
  return 'unsupported';
}

export function toMedia(media: Api.TypeMessageMedia | undefined): MessageMedia | undefined {
  const kind = mediaKindOf(media);
  if (!kind || !media) return undefined;

  const out: MessageMedia = { kind };

  if (media instanceof Api.MessageMediaPhoto && media.photo instanceof Api.Photo) {
    const largest = media.photo.sizes
      .filter((s): s is Api.PhotoSize => s instanceof Api.PhotoSize)
      .sort((a, b) => b.size - a.size)[0];
    if (largest) {
      out.width = largest.w;
      out.height = largest.h;
      out.size = largest.size;
    }
    const stripped = media.photo.sizes.find(
      (s): s is Api.PhotoStrippedSize => s instanceof Api.PhotoStrippedSize,
    );
    if (stripped) out.thumbUrl = strippedThumbToDataUrl(stripped.bytes);
  }

  if (media instanceof Api.MessageMediaDocument && media.document instanceof Api.Document) {
    const doc = media.document;
    out.size = Number(doc.size);
    out.mimeType = doc.mimeType;
    for (const attr of doc.attributes) {
      if (attr instanceof Api.DocumentAttributeFilename) out.fileName = attr.fileName;
      if (attr instanceof Api.DocumentAttributeAudio) out.duration = attr.duration;
      if (attr instanceof Api.DocumentAttributeVideo) {
        out.duration = attr.duration;
        out.width = attr.w;
        out.height = attr.h;
      }
      if (attr instanceof Api.DocumentAttributeImageSize) {
        out.width = attr.w;
        out.height = attr.h;
      }
      if (attr instanceof Api.DocumentAttributeSticker) out.emoji = attr.alt;
    }
    const stripped = doc.thumbs?.find(
      (s): s is Api.PhotoStrippedSize => s instanceof Api.PhotoStrippedSize,
    );
    if (stripped) out.thumbUrl = strippedThumbToDataUrl(stripped.bytes);
  }

  return out;
}

/**
 * Telegram ships a 2-byte-header JPEG blur thumbnail with most media. Telegram's
 * own clients re-attach a fixed JPEG header/footer to make it decodable; this is
 * that same trick, so a placeholder shows before the real file arrives.
 */
const JPEG_HEADER = Uint8Array.from([
  0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
  0x00, 0x01, 0x00, 0x00, 0xff, 0xdb, 0x00, 0x43, 0x00, 0x28, 0x1c, 0x1e, 0x23, 0x1e, 0x19, 0x28,
  0x23, 0x21, 0x23, 0x2d, 0x2b, 0x28, 0x30, 0x3c, 0x64, 0x41, 0x3c, 0x37, 0x37, 0x3c, 0x7b, 0x58,
  0x5d, 0x49, 0x64, 0x91, 0x80, 0x99, 0x96, 0x8f, 0x80, 0x8c, 0x8a, 0xa0, 0xb4, 0xe6, 0xc3, 0xa0,
  0xaa, 0xda, 0xad, 0x8a, 0x8c, 0xc8, 0xff, 0xcb, 0xda, 0xee, 0xf5, 0xff, 0xff, 0xff, 0x9b, 0xc1,
  0xff, 0xff, 0xff, 0xfa, 0xff, 0xe6, 0xfd, 0xff, 0xf8, 0xff, 0xdb, 0x00, 0x43, 0x01, 0x2b, 0x2d,
  0x2d, 0x3c, 0x35, 0x3c, 0x76, 0x41, 0x41, 0x76, 0xf8, 0xa5, 0x8c, 0xa5, 0xf8, 0xf8, 0xf8, 0xf8,
  0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8,
  0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8,
  0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xf8, 0xff, 0xc0, 0x00,
  0x11, 0x08, 0x00, 0x00, 0x00, 0x00, 0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01,
  0xff, 0xc4, 0x00, 0x1f, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a,
  0x0b, 0xff, 0xc4, 0x00, 0xb5, 0x10, 0x00, 0x02, 0x01, 0x03, 0x03, 0x02, 0x04, 0x03, 0x05, 0x05,
  0x04, 0x04, 0x00, 0x00, 0x01, 0x7d, 0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31,
  0x41, 0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42,
  0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0, 0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18,
  0x19, 0x1a, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43,
  0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63,
  0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83,
  0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a,
  0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8,
  0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6,
  0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2,
  0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa, 0xff, 0xc4, 0x00, 0x1f, 0x01, 0x00, 0x03, 0x01,
  0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03,
  0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0xff, 0xc4, 0x00, 0xb5, 0x11, 0x00, 0x02, 0x01,
  0x02, 0x04, 0x04, 0x03, 0x04, 0x07, 0x05, 0x04, 0x04, 0x00, 0x01, 0x02, 0x77, 0x00, 0x01, 0x02,
  0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71, 0x13, 0x22, 0x32,
  0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0, 0x15, 0x62, 0x72,
  0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26, 0x27, 0x28, 0x29,
  0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53,
  0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73,
  0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a,
  0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8,
  0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6,
  0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe2, 0xe3, 0xe4,
  0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa, 0xff,
  0xda, 0x00, 0x0c, 0x03, 0x01, 0x00, 0x02, 0x11, 0x03, 0x11, 0x00, 0x3f, 0x00,
]);
const JPEG_FOOTER = Uint8Array.from([0xff, 0xd9]);

export function strippedThumbToDataUrl(bytes: Uint8Array): string | undefined {
  if (!bytes || bytes.length < 3) return undefined;
  const header = new Uint8Array(JPEG_HEADER);
  // Bytes 1 and 2 of the stripped payload are the real width/height.
  header[164] = bytes[1];
  header[166] = bytes[2];
  const body = bytes.subarray(3);
  const out = new Uint8Array(header.length + body.length + JPEG_FOOTER.length);
  out.set(header, 0);
  out.set(body, header.length);
  out.set(JPEG_FOOTER, header.length + body.length);
  let binary = '';
  for (const b of out) binary += String.fromCharCode(b);
  return `data:image/jpeg;base64,${btoa(binary)}`;
}

export function toEntities(entities: Api.TypeMessageEntity[] | undefined): TextEntity[] | undefined {
  if (!entities?.length) return undefined;
  const out: TextEntity[] = [];
  for (const e of entities) {
    const base = { offset: e.offset, length: e.length };
    if (e instanceof Api.MessageEntityBold) out.push({ ...base, kind: 'bold' });
    else if (e instanceof Api.MessageEntityItalic) out.push({ ...base, kind: 'italic' });
    else if (e instanceof Api.MessageEntityCode) out.push({ ...base, kind: 'code' });
    else if (e instanceof Api.MessageEntityPre) out.push({ ...base, kind: 'pre' });
    else if (e instanceof Api.MessageEntityUnderline) out.push({ ...base, kind: 'underline' });
    else if (e instanceof Api.MessageEntityStrike) out.push({ ...base, kind: 'strike' });
    else if (e instanceof Api.MessageEntitySpoiler) out.push({ ...base, kind: 'spoiler' });
    else if (e instanceof Api.MessageEntityUrl) out.push({ ...base, kind: 'url' });
    else if (e instanceof Api.MessageEntityTextUrl) out.push({ ...base, kind: 'textUrl', url: e.url });
    else if (e instanceof Api.MessageEntityMention) out.push({ ...base, kind: 'mention' });
    else if (e instanceof Api.MessageEntityHashtag) out.push({ ...base, kind: 'hashtag' });
  }
  return out.length ? out : undefined;
}
