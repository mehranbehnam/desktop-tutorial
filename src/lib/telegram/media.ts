/**
 * File and avatar downloads.
 *
 * Every blob URL we mint is cached by key and revoked on `releaseAll`, so a
 * long session does not leak the whole media history into memory.
 */
import { getClient } from './client';

const urls = new Map<string, string>();
const inFlight = new Map<string, Promise<string | null>>();

function cache(key: string, bytes: Uint8Array, mime: string): string {
  const url = URL.createObjectURL(new Blob([bytes as unknown as BlobPart], { type: mime }));
  urls.set(key, url);
  return url;
}

export function cachedUrl(key: string): string | undefined {
  return urls.get(key);
}

/** Small, cheap, and requested constantly — hence its own cache key space. */
export async function downloadAvatar(peerId: string): Promise<string | null> {
  const key = `avatar:${peerId}`;
  const hit = urls.get(key);
  if (hit) return hit;
  const pending = inFlight.get(key);
  if (pending) return pending;

  const task = (async () => {
    try {
      const client = getClient();
      const entity = await client.getEntity(peerId);
      const bytes = await client.downloadProfilePhoto(entity, { isBig: false });
      if (!bytes || bytes.length === 0) return null;
      return cache(key, bytes as Uint8Array, 'image/jpeg');
    } catch {
      return null;
    } finally {
      inFlight.delete(key);
    }
  })();

  inFlight.set(key, task);
  return task;
}

export interface DownloadHandle {
  url: string | null;
  cancelled: boolean;
}

export async function downloadMessageMedia(
  peerId: string,
  messageId: number,
  mime = 'application/octet-stream',
  onProgress?: (fraction: number) => void,
): Promise<string | null> {
  const key = `media:${peerId}:${messageId}`;
  const hit = urls.get(key);
  if (hit) return hit;
  const pending = inFlight.get(key);
  if (pending) return pending;

  const task = (async () => {
    try {
      const client = getClient();
      const entity = await client.getInputEntity(peerId);
      const [message] = await client.getMessages(entity, { ids: [messageId] });
      if (!message?.media) return null;
      const bytes = await client.downloadMedia(message, {
        progressCallback: onProgress
          ? ((downloaded: unknown, total: unknown) => {
              const d = Number(downloaded);
              const t = Number(total);
              if (t > 0) onProgress(d / t);
            }) as never
          : undefined,
      });
      if (!bytes || typeof bytes === 'string' || bytes.length === 0) return null;
      return cache(key, bytes as Uint8Array, mime);
    } catch {
      return null;
    } finally {
      inFlight.delete(key);
    }
  })();

  inFlight.set(key, task);
  return task;
}

/** Prompts a save dialog for an already-downloaded blob. */
export function saveAs(url: string, fileName: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function releaseAll(): void {
  for (const url of urls.values()) URL.revokeObjectURL(url);
  urls.clear();
  inFlight.clear();
}
