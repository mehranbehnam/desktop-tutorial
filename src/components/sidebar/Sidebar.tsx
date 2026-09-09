/**
 * Chat list plus search. Search results replace the list while a query is
 * active; picking one opens the chat and clears the box.
 */
import { useEffect, useRef, useState } from 'react';
import { ChatListItem } from './ChatListItem';
import { Avatar } from '../common/Avatar';
import { Icon } from '../common/Icon';
import { Spinner } from '../common/Spinner';
import { useChatStore } from '../../store/chatStore';
import { useUiStore } from '../../store/uiStore';
import type { Dialog, Peer } from '../../lib/telegram/types';

export function Sidebar() {
  const dialogs = useChatStore((s) => s.dialogs);
  const loading = useChatStore((s) => s.dialogsLoading);
  const hasMore = useChatStore((s) => s.dialogsCursor !== null);
  const activePeerId = useChatStore((s) => s.activePeerId);
  const openChat = useChatStore((s) => s.openChat);
  const loadDialogs = useChatStore((s) => s.loadDialogs);
  const runSearch = useChatStore((s) => s.runSearch);
  const searchResults = useChatStore((s) => s.searchResults);
  const setPinned = useChatStore((s) => s.setPinned);
  const setMuted = useChatStore((s) => s.setMuted);
  const openPanel = useUiStore((s) => s.openPanel);
  const setMobileView = useUiStore((s) => s.setMobileView);

  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState<{ x: number; y: number; dialog: Dialog } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Debounce so typing does not fire a contacts.Search per keystroke.
  useEffect(() => {
    const handle = window.setTimeout(() => void runSearch(query), 300);
    return () => window.clearTimeout(handle);
  }, [query, runSearch]);

  useEffect(() => {
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, []);

  function onScroll() {
    const el = scrollRef.current;
    if (!el || loading || !hasMore) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) void loadDialogs(true);
  }

  function select(peer: Peer) {
    void openChat(peer);
    setMobileView('chat');
    setQuery('');
  }

  const searching = query.trim().length > 0;

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <button
          className="icon-button"
          onClick={() => openPanel('settings')}
          aria-label="تنظیمات"
          type="button"
        >
          <Icon name="menu" />
        </button>
        <div className="search-box">
          <Icon name="search" size={18} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="جستجو"
            aria-label="جستجو در گفتگوها"
          />
          {searching && (
            <button className="icon-button" onClick={() => setQuery('')} aria-label="پاک کردن" type="button">
              <Icon name="close" size={16} />
            </button>
          )}
        </div>
      </div>

      <div className="chat-list" ref={scrollRef} onScroll={onScroll}>
        {searching ? (
          <SearchResults results={searchResults} onSelect={select} />
        ) : dialogs.length === 0 && loading ? (
          <Spinner center />
        ) : dialogs.length === 0 ? (
          <p className="chat-list-empty">هنوز گفتگویی نداری.</p>
        ) : (
          dialogs.map((dialog) => (
            <ChatListItem
              key={dialog.peerId}
              dialog={dialog}
              selected={dialog.peerId === activePeerId}
              onSelect={() => select(dialog.peer)}
              onContextMenu={(event) => {
                event.preventDefault();
                setMenu({ x: event.clientX, y: event.clientY, dialog });
              }}
            />
          ))
        )}
        {!searching && loading && dialogs.length > 0 && <Spinner center />}
      </div>

      {menu && (
        <div className="context-menu" style={{ top: menu.y, left: menu.x }} role="menu">
          <button
            type="button"
            onClick={() => void setPinned(menu.dialog.peerId, !menu.dialog.pinned)}
          >
            <Icon name="pin" size={16} />
            {menu.dialog.pinned ? 'برداشتن سنجاق' : 'سنجاق کردن'}
          </button>
          <button type="button" onClick={() => void setMuted(menu.dialog.peerId, !menu.dialog.muted)}>
            <Icon name={menu.dialog.muted ? 'bell' : 'mute'} size={16} />
            {menu.dialog.muted ? 'فعال کردن اعلان' : 'بی‌صدا کردن'}
          </button>
        </div>
      )}
    </aside>
  );
}

function SearchResults({ results, onSelect }: { results: Peer[]; onSelect: (peer: Peer) => void }) {
  if (results.length === 0) return <p className="chat-list-empty">نتیجه‌ای پیدا نشد.</p>;
  return (
    <>
      <div className="section-label">نتایج جستجو</div>
      {results.map((peer) => (
        <button key={peer.id} className="chat-item" onClick={() => onSelect(peer)} type="button">
          <Avatar peer={peer} size={44} />
          <div className="chat-item-body">
            <div className="chat-title">{peer.title}</div>
            <div className="chat-preview">{peer.username ? `@${peer.username}` : kindLabel(peer)}</div>
          </div>
        </button>
      ))}
    </>
  );
}

function kindLabel(peer: Peer): string {
  if (peer.kind === 'channel') return 'کانال';
  if (peer.kind === 'group') return 'گروه';
  return peer.isBot ? 'ربات' : 'کاربر';
}
