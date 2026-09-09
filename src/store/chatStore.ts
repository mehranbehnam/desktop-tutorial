/**
 * Chat list + open conversation.
 *
 * Messages live in a per-peer map keyed by peer id and are always kept sorted
 * oldest-first; the list component relies on that ordering for its day
 * separators and scroll anchoring.
 */
import { create } from 'zustand';
import * as dialogsApi from '../lib/telegram/dialogs';
import * as messagesApi from '../lib/telegram/messages';
import { subscribe, type UpdateHandlers } from '../lib/telegram/updates';
import type { Dialog, Message, Peer, PresenceStatus } from '../lib/telegram/types';

interface Conversation {
  messages: Message[];
  /** null once the whole history has been walked. */
  nextOffsetId: number | null;
  loading: boolean;
  loadedOnce: boolean;
}

interface ChatState {
  selfId: string;
  dialogs: Dialog[];
  dialogsLoading: boolean;
  dialogsCursor: dialogsApi.DialogPage['cursor'];
  activePeerId: string | null;
  activePeer: Peer | null;
  conversations: Record<string, Conversation>;
  typing: Record<string, { name: string; until: number }[]>;
  connected: boolean;
  searchQuery: string;
  searchResults: Peer[];
  replyTo: Message | null;
  drafts: Record<string, string>;

  init: (selfId: string) => Promise<void>;
  loadDialogs: (append?: boolean) => Promise<void>;
  openChat: (peer: Peer) => Promise<void>;
  closeChat: () => void;
  loadOlder: () => Promise<void>;
  send: (text: string) => Promise<void>;
  sendFile: (file: File, caption: string) => Promise<void>;
  remove: (ids: number[], forEveryone: boolean) => Promise<void>;
  setReplyTo: (message: Message | null) => void;
  setDraft: (peerId: string, text: string) => void;
  runSearch: (query: string) => Promise<void>;
  setPinned: (peerId: string, pinned: boolean) => Promise<void>;
  setMuted: (peerId: string, muted: boolean) => Promise<void>;
  teardown: () => void;
}

let unsubscribe: (() => void) | null = null;
let typingTimer: number | null = null;
/** Local ids for optimistic bubbles; kept far above real Telegram ids. */
let localSeq = -1;

const emptyConversation: Conversation = {
  messages: [],
  nextOffsetId: 0,
  loading: false,
  loadedOnce: false,
};

export const useChatStore = create<ChatState>((set, get) => ({
  selfId: '',
  dialogs: [],
  dialogsLoading: false,
  dialogsCursor: null,
  activePeerId: null,
  activePeer: null,
  conversations: {},
  typing: {},
  connected: true,
  searchQuery: '',
  searchResults: [],
  replyTo: null,
  drafts: {},

  async init(selfId) {
    set({ selfId });
    await get().loadDialogs();

    const handlers: UpdateHandlers = {
      onMessage(message) {
        const state = get();
        // Append to the open conversation, and bump the chat list either way.
        if (state.conversations[message.peerId]?.loadedOnce) {
          upsertMessage(set, get, message);
        }
        bumpDialog(set, get, message);
        if (state.activePeerId === message.peerId && !message.outgoing) {
          void dialogsApi.markRead(message.peerId, message.id).catch(() => undefined);
        }
      },
      onMessageEdited(message) {
        upsertMessage(set, get, message);
      },
      onMessagesDeleted(peerId, ids) {
        const removed = new Set(ids);
        set((state) => {
          const next: Record<string, Conversation> = {};
          for (const [key, conv] of Object.entries(state.conversations)) {
            if (peerId !== null && key !== peerId) {
              next[key] = conv;
              continue;
            }
            next[key] = { ...conv, messages: conv.messages.filter((m) => !removed.has(m.id)) };
          }
          return { conversations: next };
        });
      },
      onTyping(event) {
        const until = Date.now() + 6000;
        set((state) => {
          const current = (state.typing[event.peerId] ?? []).filter((t) => t.until > Date.now());
          const name = event.userName || nameOfUser(get(), event.userId);
          const merged = [...current.filter((t) => t.name !== name), { name, until }];
          return { typing: { ...state.typing, [event.peerId]: merged } };
        });
      },
      onPresence(userId, status) {
        set((state) => ({
          dialogs: state.dialogs.map((d) =>
            d.peer.kind === 'user' && d.peerId === userId
              ? { ...d, peer: { ...d.peer, status } }
              : d,
          ),
          activePeer:
            state.activePeer?.id === userId
              ? { ...state.activePeer, status: status as PresenceStatus }
              : state.activePeer,
        }));
      },
      onReadOutbox(peerId, maxId) {
        set((state) => ({
          dialogs: state.dialogs.map((d) =>
            d.peerId === peerId && d.lastMessage && d.lastMessage.id <= maxId
              ? { ...d, unreadCount: 0 }
              : d,
          ),
        }));
      },
      onConnectionChange(connected) {
        set({ connected });
      },
    };

    unsubscribe?.();
    unsubscribe = subscribe(selfId, handlers);

    // Expire stale "typing" chips even when no further update arrives.
    typingTimer = window.setInterval(() => {
      const now = Date.now();
      set((state) => {
        let changed = false;
        const next: ChatState['typing'] = {};
        for (const [peerId, entries] of Object.entries(state.typing)) {
          const alive = entries.filter((t) => t.until > now);
          if (alive.length !== entries.length) changed = true;
          if (alive.length) next[peerId] = alive;
        }
        return changed ? { typing: next } : {};
      });
    }, 2000);
  },

  async loadDialogs(append = false) {
    if (get().dialogsLoading) return;
    set({ dialogsLoading: true });
    try {
      const page = await dialogsApi.fetchDialogs(
        get().selfId,
        50,
        append ? get().dialogsCursor ?? undefined : undefined,
      );
      set((state) => {
        const merged = append ? dedupe([...state.dialogs, ...page.dialogs]) : page.dialogs;
        return { dialogs: merged, dialogsCursor: page.cursor, dialogsLoading: false };
      });
    } catch {
      set({ dialogsLoading: false });
    }
  },

  async openChat(peer) {
    set({ activePeerId: peer.id, activePeer: peer, replyTo: null });

    const existing = get().conversations[peer.id];
    if (!existing?.loadedOnce) {
      set((state) => ({
        conversations: { ...state.conversations, [peer.id]: { ...emptyConversation, loading: true } },
      }));
      try {
        const page = await messagesApi.fetchHistory(peer.id, get().selfId, 40, 0);
        set((state) => ({
          conversations: {
            ...state.conversations,
            [peer.id]: {
              messages: page.messages,
              nextOffsetId: page.nextOffsetId,
              loading: false,
              loadedOnce: true,
            },
          },
        }));
      } catch {
        set((state) => ({
          conversations: {
            ...state.conversations,
            [peer.id]: { ...emptyConversation, loading: false, loadedOnce: true },
          },
        }));
      }
    }

    const top = get().conversations[peer.id]?.messages.at(-1);
    if (top) void dialogsApi.markRead(peer.id, top.id).catch(() => undefined);
    set((state) => ({
      dialogs: state.dialogs.map((d) => (d.peerId === peer.id ? { ...d, unreadCount: 0 } : d)),
    }));
  },

  closeChat() {
    set({ activePeerId: null, activePeer: null, replyTo: null });
  },

  async loadOlder() {
    const { activePeerId, conversations, selfId } = get();
    if (!activePeerId) return;
    const conv = conversations[activePeerId];
    if (!conv || conv.loading || conv.nextOffsetId === null) return;

    set((state) => ({
      conversations: {
        ...state.conversations,
        [activePeerId]: { ...conv, loading: true },
      },
    }));

    try {
      const page = await messagesApi.fetchHistory(activePeerId, selfId, 40, conv.nextOffsetId);
      set((state) => {
        const current = state.conversations[activePeerId];
        return {
          conversations: {
            ...state.conversations,
            [activePeerId]: {
              messages: [...page.messages, ...current.messages],
              nextOffsetId: page.nextOffsetId,
              loading: false,
              loadedOnce: true,
            },
          },
        };
      });
    } catch {
      set((state) => ({
        conversations: {
          ...state.conversations,
          [activePeerId]: { ...state.conversations[activePeerId], loading: false },
        },
      }));
    }
  },

  async send(text) {
    const { activePeerId, selfId, replyTo } = get();
    const body = text.trim();
    if (!activePeerId || !body) return;

    const localId = localSeq--;
    const optimistic: Message = {
      id: localId,
      peerId: activePeerId,
      senderId: selfId,
      text: body,
      date: Math.floor(Date.now() / 1000),
      outgoing: true,
      pending: true,
      replyToId: replyTo?.id,
    };
    upsertMessage(set, get, optimistic);
    set({ replyTo: null });

    try {
      const sent = await messagesApi.sendText(activePeerId, body, selfId, {
        replyTo: replyTo?.id,
        localId,
      });
      replaceMessage(set, get, activePeerId, localId, sent);
      bumpDialog(set, get, sent);
    } catch {
      replaceMessage(set, get, activePeerId, localId, {
        ...optimistic,
        pending: false,
        failed: true,
      });
    }
  },

  async sendFile(file, caption) {
    const { activePeerId, selfId } = get();
    if (!activePeerId) return;

    const localId = localSeq--;
    const optimistic: Message = {
      id: localId,
      peerId: activePeerId,
      senderId: selfId,
      text: caption,
      date: Math.floor(Date.now() / 1000),
      outgoing: true,
      pending: true,
      media: { kind: file.type.startsWith('image/') ? 'photo' : 'document', fileName: file.name, size: file.size },
    };
    upsertMessage(set, get, optimistic);

    try {
      const sent = await messagesApi.sendFile(activePeerId, file, selfId, caption);
      replaceMessage(set, get, activePeerId, localId, sent);
      bumpDialog(set, get, sent);
    } catch {
      replaceMessage(set, get, activePeerId, localId, { ...optimistic, pending: false, failed: true });
    }
  },

  async remove(ids, forEveryone) {
    const { activePeerId } = get();
    if (!activePeerId) return;
    await messagesApi.deleteMessages(activePeerId, ids, forEveryone);
    const removed = new Set(ids);
    set((state) => ({
      conversations: {
        ...state.conversations,
        [activePeerId]: {
          ...state.conversations[activePeerId],
          messages: state.conversations[activePeerId].messages.filter((m) => !removed.has(m.id)),
        },
      },
    }));
  },

  setReplyTo(message) {
    set({ replyTo: message });
  },

  setDraft(peerId, text) {
    set((state) => ({ drafts: { ...state.drafts, [peerId]: text } }));
  },

  async runSearch(query) {
    set({ searchQuery: query });
    if (!query.trim()) {
      set({ searchResults: [] });
      return;
    }
    try {
      const { peers } = await dialogsApi.search(query);
      // Ignore a stale response if the box moved on while we were waiting.
      if (get().searchQuery === query) set({ searchResults: peers });
    } catch {
      set({ searchResults: [] });
    }
  },

  async setPinned(peerId, pinned) {
    set((state) => ({
      dialogs: sortDialogs(state.dialogs.map((d) => (d.peerId === peerId ? { ...d, pinned } : d))),
    }));
    try {
      await dialogsApi.togglePin(peerId, pinned);
    } catch {
      set((state) => ({
        dialogs: sortDialogs(
          state.dialogs.map((d) => (d.peerId === peerId ? { ...d, pinned: !pinned } : d)),
        ),
      }));
    }
  },

  async setMuted(peerId, muted) {
    set((state) => ({
      dialogs: state.dialogs.map((d) => (d.peerId === peerId ? { ...d, muted } : d)),
    }));
    try {
      await dialogsApi.toggleMute(peerId, muted);
    } catch {
      set((state) => ({
        dialogs: state.dialogs.map((d) => (d.peerId === peerId ? { ...d, muted: !muted } : d)),
      }));
    }
  },

  teardown() {
    unsubscribe?.();
    unsubscribe = null;
    if (typingTimer !== null) window.clearInterval(typingTimer);
    typingTimer = null;
  },
}));

type Setter = (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void;
type Getter = () => ChatState;

function upsertMessage(set: Setter, get: Getter, message: Message): void {
  const conv = get().conversations[message.peerId] ?? { ...emptyConversation, loadedOnce: true };
  const index = conv.messages.findIndex((m) => m.id === message.id);
  const messages =
    index >= 0
      ? conv.messages.map((m, i) => (i === index ? { ...m, ...message } : m))
      : [...conv.messages, message].sort((a, b) => a.date - b.date || a.id - b.id);

  set((state) => ({
    conversations: { ...state.conversations, [message.peerId]: { ...conv, messages } },
  }));
}

function replaceMessage(
  set: Setter,
  get: Getter,
  peerId: string,
  oldId: number,
  next: Message,
): void {
  const conv = get().conversations[peerId];
  if (!conv) return;
  const messages = conv.messages
    .map((m) => (m.id === oldId ? next : m))
    .sort((a, b) => a.date - b.date || a.id - b.id);
  set((state) => ({ conversations: { ...state.conversations, [peerId]: { ...conv, messages } } }));
}

/** Moves a chat to the top of the list and refreshes its preview line. */
function bumpDialog(set: Setter, get: Getter, message: Message): void {
  const state = get();
  const existing = state.dialogs.find((d) => d.peerId === message.peerId);
  if (!existing) {
    // A chat we have never seen — pull a fresh page rather than inventing one.
    void get().loadDialogs();
    return;
  }

  const isActive = state.activePeerId === message.peerId;
  const updated: Dialog = {
    ...existing,
    date: message.date,
    unreadCount:
      message.outgoing || isActive ? existing.unreadCount : existing.unreadCount + 1,
    lastMessage: {
      id: message.id,
      text: message.text || (message.media ? dialogsApi.mediaLabel(message.media.kind) : ''),
      date: message.date,
      outgoing: message.outgoing,
      senderName: message.senderName,
      mediaKind: message.media?.kind,
    },
  };

  set({
    dialogs: sortDialogs([updated, ...state.dialogs.filter((d) => d.peerId !== message.peerId)]),
  });
}

function sortDialogs(dialogs: Dialog[]): Dialog[] {
  return [...dialogs].sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.date - a.date);
}

function dedupe(dialogs: Dialog[]): Dialog[] {
  const seen = new Set<string>();
  return dialogs.filter((d) => (seen.has(d.peerId) ? false : (seen.add(d.peerId), true)));
}

function nameOfUser(state: ChatState, userId: string): string {
  return state.dialogs.find((d) => d.peerId === userId)?.peer.title ?? 'یک نفر';
}
