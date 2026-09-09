/**
 * Right-hand details panel for the open chat.
 */
import { useEffect, useState } from 'react';
import { Avatar } from '../common/Avatar';
import { Icon } from '../common/Icon';
import { formatPresence, formatCount, toFaDigits } from '../../lib/format';
import { fetchFullPeer } from '../../lib/telegram/dialogs';
import { useChatStore } from '../../store/chatStore';
import { useUiStore } from '../../store/uiStore';

export function ProfilePanel() {
  const peer = useChatStore((s) => s.activePeer);
  const dialog = useChatStore((s) => s.dialogs.find((d) => d.peerId === s.activePeerId));
  const setMuted = useChatStore((s) => s.setMuted);
  const openPanel = useUiStore((s) => s.openPanel);

  const [full, setFull] = useState<{ about?: string; membersCount?: number }>({});

  useEffect(() => {
    if (!peer) return;
    let alive = true;
    void fetchFullPeer(peer.id).then((data) => {
      if (alive) setFull(data);
    });
    return () => {
      alive = false;
    };
  }, [peer?.id]);

  if (!peer) return null;

  const members = full.membersCount ?? peer.membersCount;

  return (
    <aside className="panel">
      <header className="panel-header">
        <button className="icon-button" onClick={() => openPanel('none')} aria-label="بستن" type="button">
          <Icon name="close" />
        </button>
        <h2>اطلاعات</h2>
      </header>

      <div className="panel-hero">
        <Avatar peer={peer} size={96} />
        <div className="name">{peer.title}</div>
        <div className="status">
          {peer.kind === 'user'
            ? formatPresence(peer.status)
            : formatCount(members, peer.kind === 'channel' ? 'دنبال‌کننده' : 'عضو')}
        </div>
      </div>

      <div className="panel-section">
        {full.about && (
          <div className="panel-row" style={{ display: 'block' }}>
            <div className="label">درباره</div>
            <div className="value" style={{ whiteSpace: 'pre-wrap' }}>{full.about}</div>
          </div>
        )}

        {peer.username && (
          <div className="panel-row">
            <div>
              <div className="label">نام کاربری</div>
              <div className="value" dir="ltr">@{peer.username}</div>
            </div>
            <Icon name="user" size={18} />
          </div>
        )}

        {peer.phone && (
          <div className="panel-row">
            <div>
              <div className="label">شماره</div>
              <div className="value" dir="ltr">+{toFaDigits(peer.phone)}</div>
            </div>
          </div>
        )}

        <div className="panel-row">
          <span>اعلان‌ها</span>
          <button
            className={dialog?.muted ? 'switch' : 'switch on'}
            onClick={() => void setMuted(peer.id, !dialog?.muted)}
            aria-label="تغییر وضعیت اعلان"
            type="button"
          />
        </div>
      </div>
    </aside>
  );
}
