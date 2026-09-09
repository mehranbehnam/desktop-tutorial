import { MessageList } from './MessageList';
import { Composer } from './Composer';
import { Avatar } from '../common/Avatar';
import { Icon } from '../common/Icon';
import { BrandMark } from '../common/BrandMark';
import { formatPresence, formatCount } from '../../lib/format';
import { useChatStore } from '../../store/chatStore';
import { useUiStore } from '../../store/uiStore';
import type { Peer } from '../../lib/telegram/types';

export function ChatView() {
  const peer = useChatStore((s) => s.activePeer);
  const conversation = useChatStore((s) => (s.activePeerId ? s.conversations[s.activePeerId] : undefined));
  const typing = useChatStore((s) => (s.activePeerId ? s.typing[s.activePeerId] : undefined));
  const closeChat = useChatStore((s) => s.closeChat);
  const openPanel = useUiStore((s) => s.openPanel);
  const panel = useUiStore((s) => s.panel);
  const setMobileView = useUiStore((s) => s.setMobileView);

  if (!peer) {
    return (
      <main className="chat">
        <div className="chat-empty">
          <BrandMark size={64} />
          <p>یک گفتگو را انتخاب کن تا شروع کنیم.</p>
        </div>
      </main>
    );
  }

  const typingText = typing?.length
    ? peer.kind === 'user'
      ? 'در حال نوشتن…'
      : `${typing.map((t) => t.name).join('، ')} در حال نوشتن…`
    : '';

  return (
    <main className="chat">
      <header className="chat-header">
        <button
          className="icon-button"
          onClick={() => {
            closeChat();
            setMobileView('list');
          }}
          aria-label="بازگشت"
          type="button"
        >
          <Icon name="back" />
        </button>

        <Avatar peer={peer} size={40} showPresence />

        <button className="chat-header-info" onClick={() => openPanel('profile')} type="button">
          <div className="chat-header-title">{peer.title}</div>
          <div className={peer.status?.kind === 'online' ? 'chat-header-status online' : 'chat-header-status'}>
            {typingText || subtitleFor(peer)}
          </div>
        </button>

        <button
          className={panel === 'profile' ? 'icon-button active' : 'icon-button'}
          onClick={() => openPanel('profile')}
          aria-label="اطلاعات گفتگو"
          type="button"
        >
          <Icon name="more" />
        </button>
      </header>

      <MessageList
        peer={peer}
        messages={conversation?.messages ?? []}
        loading={conversation?.loading ?? false}
        hasMore={conversation?.nextOffsetId !== null}
      />

      <Composer peer={peer} />
    </main>
  );
}

function subtitleFor(peer: Peer): string {
  if (peer.kind === 'channel') return formatCount(peer.membersCount, 'دنبال‌کننده') || 'کانال';
  if (peer.kind === 'group') return formatCount(peer.membersCount, 'عضو') || 'گروه';
  if (peer.isSelf) return 'یادداشت‌های خودت';
  if (peer.isBot) return 'ربات';
  return formatPresence(peer.status);
}
