/**
 * Peer avatar. Renders initials on a deterministic gradient immediately, then
 * swaps in the real photo once it downloads — avatars must never block paint.
 */
import { useEffect, useState } from 'react';
import { avatarColor, initials } from '../../lib/format';
import { downloadAvatar, cachedUrl } from '../../lib/telegram/media';
import type { Peer } from '../../lib/telegram/types';

interface AvatarProps {
  peer: Peer;
  size?: number;
  showPresence?: boolean;
}

export function Avatar({ peer, size = 48, showPresence = false }: AvatarProps) {
  const [url, setUrl] = useState<string | null>(() => cachedUrl(`avatar:${peer.id}`) ?? null);

  useEffect(() => {
    if (!peer.photoId) {
      setUrl(null);
      return;
    }
    let alive = true;
    const cached = cachedUrl(`avatar:${peer.id}`);
    if (cached) {
      setUrl(cached);
      return;
    }
    void downloadAvatar(peer.id).then((next) => {
      if (alive) setUrl(next);
    });
    return () => {
      alive = false;
    };
  }, [peer.id, peer.photoId]);

  const online = showPresence && peer.kind === 'user' && peer.status?.kind === 'online';

  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: url ? 'transparent' : avatarColor(peer.id),
      }}
      aria-hidden="true"
    >
      {url ? <img src={url} alt="" loading="lazy" /> : <span>{initials(peer.title)}</span>}
      {online && <span className="presence-dot" />}
    </div>
  );
}
