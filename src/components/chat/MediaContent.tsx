/**
 * Media inside a bubble.
 *
 * Photos auto-load (they're what people scroll for); everything heavier waits
 * for a tap so a long channel does not pull megabytes on open.
 */
import { useEffect, useState } from 'react';
import { Icon } from '../common/Icon';
import { Spinner } from '../common/Spinner';
import { formatSize, formatDuration, toFaDigits } from '../../lib/format';
import { downloadMessageMedia, cachedUrl, saveAs } from '../../lib/telegram/media';
import type { Message } from '../../lib/telegram/types';

interface Props {
  message: Message;
  onOpenImage: (url: string) => void;
}

export function MediaContent({ message, onOpenImage }: Props) {
  const media = message.media;
  const key = `media:${message.peerId}:${message.id}`;
  const [url, setUrl] = useState<string | null>(() => cachedUrl(key) ?? null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);

  const autoLoad = media?.kind === 'photo' || media?.kind === 'sticker';

  useEffect(() => {
    if (!media || !autoLoad || url || message.pending) return;
    let alive = true;
    setLoading(true);
    void downloadMessageMedia(message.peerId, message.id, media.mimeType ?? 'image/jpeg', (f) => {
      if (alive) setProgress(f);
    }).then((next) => {
      if (!alive) return;
      setUrl(next);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [media, autoLoad, url, message.peerId, message.id, message.pending]);

  if (!media) return null;

  async function load() {
    if (loading || url || !media) return;
    setLoading(true);
    const next = await downloadMessageMedia(
      message.peerId,
      message.id,
      media.mimeType ?? 'application/octet-stream',
      setProgress,
    );
    setUrl(next);
    setLoading(false);
  }

  switch (media.kind) {
    case 'photo':
    case 'gif': {
      const source = url ?? media.thumbUrl;
      // An empty src makes the browser re-request the page, so show a box
      // instead when neither the file nor its blur placeholder is here yet.
      if (!source) {
        return (
          <div
            className="media-placeholder"
            style={{ aspectRatio: media.width && media.height ? `${media.width}/${media.height}` : '4/3' }}
          >
            <Spinner />
          </div>
        );
      }
      return (
        <img
          className="media-photo"
          src={source}
          alt={message.text || 'تصویر'}
          width={media.width}
          height={media.height}
          style={{ filter: url ? undefined : 'blur(12px)', maxHeight: '60vh', objectFit: 'cover' }}
          onClick={() => url && onOpenImage(url)}
        />
      );
    }

    case 'sticker':
      return url ? (
        <img className="media-photo" src={url} alt={media.emoji ?? 'استیکر'} style={{ maxWidth: 180 }} />
      ) : (
        <div className="media-sticker">{media.emoji ?? '🙂'}</div>
      );

    case 'video':
      return url ? (
        <video className="media-photo" src={url} controls style={{ maxHeight: '60vh' }} />
      ) : (
        <button className="media-placeholder" onClick={load} type="button">
          {loading ? (
            <span>{toFaDigits(Math.round(progress * 100))}٪</span>
          ) : (
            <>
              <Icon name="download" size={28} />
              <span>ویدیو · {formatSize(media.size)}</span>
            </>
          )}
        </button>
      );

    case 'voice':
    case 'audio':
      return url ? (
        <audio src={url} controls style={{ width: '100%', minWidth: 220 }} />
      ) : (
        <button className="media-file" onClick={load} type="button">
          <span className="file-icon">
            <Icon name={loading ? 'clock' : 'download'} size={18} />
          </span>
          <span className="file-body">
            <span className="file-name">
              {media.kind === 'voice' ? 'پیام صوتی' : (media.fileName ?? 'فایل صوتی')}
            </span>
            <span className="file-meta">
              {formatDuration(media.duration)} · {formatSize(media.size)}
            </span>
          </span>
        </button>
      );

    default:
      return (
        <button
          className="media-file"
          onClick={() => (url ? saveAs(url, media.fileName ?? 'file') : void load())}
          type="button"
        >
          <span className="file-icon">
            <Icon name={url ? 'download' : loading ? 'clock' : 'file'} size={18} />
          </span>
          <span className="file-body">
            <span className="file-name">{media.fileName ?? 'فایل'}</span>
            <span className="file-meta">
              {loading ? `${toFaDigits(Math.round(progress * 100))}٪` : formatSize(media.size)}
            </span>
          </span>
        </button>
      );
  }
}
