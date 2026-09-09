/**
 * Scrollback.
 *
 * Two behaviours matter here: stay pinned to the bottom while the user is
 * already there, and keep the reading position stable when an older page is
 * prepended (measure scrollHeight before, restore the delta after).
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { MessageBubble } from './MessageBubble';
import { Spinner } from '../common/Spinner';
import { Icon } from '../common/Icon';
import { formatDaySeparator, isSameDay } from '../../lib/format';
import { useChatStore } from '../../store/chatStore';
import { useUiStore } from '../../store/uiStore';
import type { Message, Peer } from '../../lib/telegram/types';

interface Props {
  peer: Peer;
  messages: Message[];
  loading: boolean;
  hasMore: boolean;
}

export function MessageList({ peer, messages, loading, hasMore }: Props) {
  const loadOlder = useChatStore((s) => s.loadOlder);
  const setReplyTo = useChatStore((s) => s.setReplyTo);
  const remove = useChatStore((s) => s.remove);
  const dialogs = useChatStore((s) => s.dialogs);
  const showAvatars = useUiStore((s) => s.showAvatarsInGroups);

  const scrollRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<{ height: number; top: number } | null>(null);
  const lastIdRef = useRef<number | null>(null);

  const [menu, setMenu] = useState<{ x: number; y: number; message: Message } | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const byId = new Map(messages.map((m) => [m.id, m]));
  const peersById = new Map(dialogs.map((d) => [d.peerId, d.peer]));

  // Before a render that prepends history, remember where we were.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const newest = messages.at(-1)?.id ?? null;
    const grewAtTop = anchorRef.current !== null && newest === lastIdRef.current;

    if (grewAtTop) {
      el.scrollTop = el.scrollHeight - anchorRef.current!.height + anchorRef.current!.top;
    } else if (newest !== lastIdRef.current) {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 220;
      if (nearBottom || lastIdRef.current === null) el.scrollTop = el.scrollHeight;
    }
    anchorRef.current = null;
    lastIdRef.current = newest;
  }, [messages]);

  useEffect(() => {
    lastIdRef.current = null;
    anchorRef.current = null;
  }, [peer.id]);

  useEffect(() => {
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, []);

  function onScroll() {
    const el = scrollRef.current;
    if (!el || loading || !hasMore) return;
    if (el.scrollTop < 300) {
      anchorRef.current = { height: el.scrollHeight, top: el.scrollTop };
      void loadOlder();
    }
  }

  function jumpTo(id: number) {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  return (
    <>
      <div className="message-scroll" ref={scrollRef} onScroll={onScroll}>
        {loading && messages.length === 0 && <Spinner center />}
        {hasMore && messages.length > 0 && (
          <div className="load-more">{loading ? 'در حال بارگذاری…' : 'برای دیدن پیام‌های قدیمی‌تر بالا برو'}</div>
        )}

        {messages.map((message, index) => {
          const previous = messages[index - 1];
          const newDay = !previous || !isSameDay(previous.date, message.date);
          const sameSender =
            previous &&
            previous.senderId === message.senderId &&
            previous.outgoing === message.outgoing &&
            !previous.service &&
            message.date - previous.date < 300;

          const sender = message.senderId ? peersById.get(message.senderId) : undefined;

          return (
            <div key={message.id} style={{ display: 'contents' }}>
              {newDay && <div className="day-separator">{formatDaySeparator(message.date)}</div>}
              <MessageBubble
                message={message}
                repliedTo={message.replyToId ? byId.get(message.replyToId) : undefined}
                peer={peer}
                sender={sender}
                showSender={!sameSender || newDay}
                showAvatar={showAvatars && peer.kind !== 'user' && !message.outgoing && (!sameSender || newDay)}
                firstOfGroup={!sameSender || newDay}
                onContextMenu={(event, target) => {
                  event.preventDefault();
                  setMenu({ x: event.clientX, y: event.clientY, message: target });
                }}
                onOpenImage={setLightbox}
                onJumpTo={jumpTo}
              />
            </div>
          );
        })}
      </div>

      {menu && (
        <div className="context-menu" style={{ top: menu.y, left: menu.x }} role="menu">
          <button type="button" onClick={() => setReplyTo(menu.message)}>
            <Icon name="reply" size={16} /> پاسخ
          </button>
          <button
            type="button"
            onClick={() => void navigator.clipboard?.writeText(menu.message.text)}
            disabled={!menu.message.text}
          >
            <Icon name="copy" size={16} /> کپی متن
          </button>
          <button
            className="danger"
            type="button"
            onClick={() => void remove([menu.message.id], menu.message.outgoing)}
          >
            <Icon name="trash" size={16} /> حذف
          </button>
        </div>
      )}

      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)} role="dialog" aria-modal="true">
          <button className="icon-button close" aria-label="بستن" type="button">
            <Icon name="close" size={24} />
          </button>
          <img src={lightbox} alt="" />
        </div>
      )}
    </>
  );
}
