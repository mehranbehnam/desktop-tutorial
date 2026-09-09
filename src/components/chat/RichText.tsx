/**
 * Renders message text with Telegram entities applied.
 *
 * Entities can overlap and are given in UTF-16 offsets, which is exactly what
 * JS string indices are — so the text is split at every entity boundary and
 * each slice is wrapped by whichever entities cover it.
 */
import { Fragment, useState, type ReactNode } from 'react';
import type { TextEntity } from '../../lib/telegram/types';

interface Props {
  text: string;
  entities?: TextEntity[];
}

export function RichText({ text, entities }: Props) {
  if (!entities?.length) return <>{linkify(text)}</>;

  const boundaries = new Set<number>([0, text.length]);
  for (const entity of entities) {
    boundaries.add(entity.offset);
    boundaries.add(entity.offset + entity.length);
  }
  const points = [...boundaries].filter((p) => p >= 0 && p <= text.length).sort((a, b) => a - b);

  const parts: ReactNode[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const start = points[i];
    const end = points[i + 1];
    if (end <= start) continue;

    const slice = text.slice(start, end);
    const covering = entities.filter((e) => e.offset <= start && e.offset + e.length >= end);
    parts.push(<Fragment key={start}>{wrap(slice, covering)}</Fragment>);
  }
  return <>{parts}</>;
}

function wrap(slice: string, entities: TextEntity[]): ReactNode {
  return entities.reduce<ReactNode>((child, entity) => {
    switch (entity.kind) {
      case 'bold':
        return <strong>{child}</strong>;
      case 'italic':
        return <em>{child}</em>;
      case 'underline':
        return <u>{child}</u>;
      case 'strike':
        return <s>{child}</s>;
      case 'code':
        return <code dir="ltr">{child}</code>;
      case 'pre':
        return <pre dir="ltr">{child}</pre>;
      case 'spoiler':
        return <Spoiler>{child}</Spoiler>;
      case 'textUrl':
        return (
          <a href={entity.url} target="_blank" rel="noreferrer noopener">
            {child}
          </a>
        );
      case 'url':
        return (
          <a href={normaliseUrl(slice)} target="_blank" rel="noreferrer noopener">
            {child}
          </a>
        );
      case 'mention':
        return (
          <a href={`https://t.me/${slice.replace('@', '')}`} target="_blank" rel="noreferrer noopener">
            {child}
          </a>
        );
      case 'hashtag':
        return <span className="hashtag">{child}</span>;
      default:
        return child;
    }
  }, slice);
}

function Spoiler({ children }: { children: ReactNode }) {
  const [revealed, setRevealed] = useState(false);
  return (
    <span
      className={revealed ? 'spoiler revealed' : 'spoiler'}
      onClick={() => setRevealed(true)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && setRevealed(true)}
    >
      {children}
    </span>
  );
}

const URL_PATTERN = /(https?:\/\/[^\s]+|www\.[^\s]+)/g;

/** Fallback for servers that send bare links with no entity list. */
function linkify(text: string): ReactNode {
  const parts = text.split(URL_PATTERN);
  if (parts.length === 1) return text;
  return parts.map((part, index) =>
    URL_PATTERN.test(part) ? (
      <a key={index} href={normaliseUrl(part)} target="_blank" rel="noreferrer noopener" dir="ltr">
        {part}
      </a>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

function normaliseUrl(url: string): string {
  return url.startsWith('http') ? url : `https://${url}`;
}
