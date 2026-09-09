import { memo } from 'react';
import { Avatar } from '../common/Avatar';
import { Icon } from '../common/Icon';
import { formatStamp, toFaDigits } from '../../lib/format';
import type { Dialog } from '../../lib/telegram/types';

interface Props {
  dialog: Dialog;
  selected: boolean;
  onSelect: () => void;
  onContextMenu: (event: React.MouseEvent) => void;
}

export const ChatListItem = memo(function ChatListItem({
  dialog,
  selected,
  onSelect,
  onContextMenu,
}: Props) {
  const { peer, lastMessage, unreadCount, muted, pinned } = dialog;

  return (
    <button
      className={selected ? 'chat-item selected' : 'chat-item'}
      onClick={onSelect}
      onContextMenu={onContextMenu}
      type="button"
    >
      <Avatar peer={peer} size={50} showPresence />

      <div className="chat-item-body">
        <div className="chat-item-row">
          <span className="chat-title">
            {peer.kind === 'channel' && <Icon name="megaphone" size={14} />}
            {peer.kind === 'group' && <Icon name="users" size={14} />} {peer.title}
          </span>
          {pinned && <Icon name="pin" size={13} />}
          {muted && <Icon name="mute" size={13} />}
          <span className="chat-time">{lastMessage ? formatStamp(lastMessage.date) : ''}</span>
        </div>

        <div className="chat-item-row">
          <span className="chat-preview">
            {lastMessage?.outgoing && <Icon name="check" size={13} />}
            {lastMessage?.senderName && peer.kind !== 'user' && (
              <span className="preview-sender">{lastMessage.senderName}:</span>
            )}
            {lastMessage?.text || 'بدون پیام'}
          </span>
          {unreadCount > 0 && (
            <span className={muted ? 'badge muted' : 'badge'}>{toFaDigits(unreadCount)}</span>
          )}
        </div>
      </div>
    </button>
  );
});
