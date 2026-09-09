/**
 * Message box: auto-growing textarea, reply preview, file picker and the
 * throttled typing ping.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon } from '../common/Icon';
import { useChatStore } from '../../store/chatStore';
import { useUiStore } from '../../store/uiStore';
import { setTyping } from '../../lib/telegram/messages';
import type { Peer } from '../../lib/telegram/types';

export function Composer({ peer }: { peer: Peer }) {
  const send = useChatStore((s) => s.send);
  const sendFile = useChatStore((s) => s.sendFile);
  const replyTo = useChatStore((s) => s.replyTo);
  const setReplyTo = useChatStore((s) => s.setReplyTo);
  const draft = useChatStore((s) => s.drafts[peer.id] ?? '');
  const setDraft = useChatStore((s) => s.setDraft);
  const sendOnEnter = useUiStore((s) => s.sendOnEnter);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const lastTypingRef = useRef(0);
  const [pending, setPending] = useState(false);

  // Grow with content up to the CSS max-height, then scroll internally. The
  // observer matters as much as the draft dependency: opening a side panel
  // narrows the box, and text that re-wraps would otherwise be clipped.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    const resize = () => {
      el.style.height = 'auto';
      el.style.height = `${el.scrollHeight}px`;
    };
    resize();

    // Observe the row, not the textarea: resizing the textarea is this
    // callback's own side effect, and watching it would feed back on itself.
    const row = el.parentElement;
    if (!row) return;
    const observer = new ResizeObserver(resize);
    observer.observe(row);
    return () => observer.disconnect();
  }, [draft]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, [peer.id, replyTo]);

  function onChange(value: string) {
    setDraft(peer.id, value);
    // Telegram expects at most one typing ping every few seconds.
    const now = Date.now();
    if (value && now - lastTypingRef.current > 4000) {
      lastTypingRef.current = now;
      void setTyping(peer.id, true);
    }
  }

  async function submit() {
    const text = draft.trim();
    if (!text || pending) return;
    setPending(true);
    setDraft(peer.id, '');
    await send(text);
    void setTyping(peer.id, false);
    setPending(false);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter') return;
    const wantsSend = sendOnEnter ? !event.shiftKey : event.ctrlKey || event.metaKey;
    if (wantsSend) {
      event.preventDefault();
      void submit();
    }
  }

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      await sendFile(file, '');
    }
    if (fileRef.current) fileRef.current.value = '';
  }

  if (!peer.canSend) {
    return (
      <div className="composer">
        <div className="composer-readonly">
          {peer.kind === 'channel' ? 'فقط مدیران می‌توانند در این کانال بنویسند.' : 'ارسال پیام در این گفتگو ممکن نیست.'}
        </div>
      </div>
    );
  }

  return (
    <div className="composer">
      {replyTo && (
        <div className="composer-reply">
          <Icon name="reply" size={16} />
          <div className="grow">
            <div style={{ fontWeight: 600 }}>{replyTo.senderName ?? 'پاسخ به پیام'}</div>
            <div className="reply-text">{replyTo.text || 'پیام'}</div>
          </div>
          <button className="icon-button" onClick={() => setReplyTo(null)} aria-label="لغو پاسخ" type="button">
            <Icon name="close" size={16} />
          </button>
        </div>
      )}

      <div className="composer-row">
        <button
          className="icon-button"
          onClick={() => fileRef.current?.click()}
          aria-label="پیوست فایل"
          type="button"
        >
          <Icon name="attach" />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(e) => void onFiles(e.target.files)}
        />

        <textarea
          ref={textareaRef}
          className="composer-input"
          rows={1}
          value={draft}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="پیام بنویس…"
          aria-label="متن پیام"
        />

        <button
          className="send-button"
          onClick={() => void submit()}
          disabled={!draft.trim() || pending}
          aria-label="ارسال"
          type="button"
        >
          <Icon name="send" />
        </button>
      </div>
    </div>
  );
}
