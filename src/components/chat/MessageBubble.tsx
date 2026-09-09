import { memo } from 'react';
import { RichText } from './RichText';
import { MediaContent } from './MediaContent';
import { Avatar } from '../common/Avatar';
import { Icon } from '../common/Icon';
import { formatTime, toFaDigits } from '../../lib/format';
import type { Message, Peer } from '../../lib/telegram/types';

interface Props {
  message: Message;
  repliedTo?: Message;
  peer: Peer;
  sender?: Peer;
  showSender: boolean;
  showAvatar: boolean;
  firstOfGroup: boolean;
  onContextMenu: (event: React.MouseEvent, message: Message) => void;
  onOpenImage: (url: string) => void;
  onJumpTo: (id: number) => void;
}

export const MessageBubble = memo(function MessageBubble({
  message,
  repliedTo,
  peer,
  sender,
  showSender,
  showAvatar,
  firstOfGroup,
  onContextMenu,
  onOpenImage,
  onJumpTo,
}: Props) {
  if (message.service) {
    return <div className="service-message">{message.service}</div>;
  }

  const classes = ['message-row'];
  if (message.outgoing) classes.push('out');
  classes.push(firstOfGroup ? 'first-of-group' : 'grouped');

  return (
    <div className={classes.join(' ')} onContextMenu={(e) => onContextMenu(e, message)}>
      {showAvatar && sender ? (
        <Avatar peer={sender} size={32} />
      ) : (
        !message.outgoing && peer.kind !== 'user' && <div style={{ width: 32, flex: '0 0 auto' }} />
      )}

      <div className="bubble" id={`msg-${message.id}`}>
        {showSender && !message.outgoing && peer.kind !== 'user' && (
          <div className="bubble-sender">{message.senderName ?? sender?.title ?? 'ناشناس'}</div>
        )}

        {message.forwardedFrom && (
          <div className="bubble-forward">
            <Icon name="reply" size={12} /> بازفرست از {message.forwardedFrom}
          </div>
        )}

        {message.replyToId && (
          <button className="bubble-reply" onClick={() => onJumpTo(message.replyToId!)} type="button">
            <span className="reply-name">{repliedTo?.senderName ?? 'پاسخ به'}</span>
            <span className="reply-text">{repliedTo?.text || 'پیام'}</span>
          </button>
        )}

        {message.media && <MediaContent message={message} onOpenImage={onOpenImage} />}

        {message.text && (
          <div className="bubble-text">
            <RichText text={message.text} entities={message.entities} />
          </div>
        )}

        <span className="bubble-meta">
          {message.views !== undefined && (
            <>
              <Icon name="user" size={11} />
              {toFaDigits(message.views)}
            </>
          )}
          {message.editDate && <span>ویرایش‌شده</span>}
          <span>{formatTime(message.date)}</span>
          {message.outgoing && <DeliveryIcon message={message} />}
        </span>
      </div>
    </div>
  );
});

function DeliveryIcon({ message }: { message: Message }) {
  if (message.failed) return <Icon name="alert" size={13} className="failed" />;
  if (message.pending) return <Icon name="clock" size={13} />;
  return <Icon name="check" size={13} />;
}
