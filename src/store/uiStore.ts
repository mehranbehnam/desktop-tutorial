/**
 * View-level preferences that survive reloads.
 */
import { create } from 'zustand';
import { readJSON, writeJSON } from '../lib/storage';

export type Theme = 'dark' | 'light' | 'system';
export type Accent = 'teal' | 'violet' | 'rose' | 'amber' | 'blue';

interface Prefs {
  theme: Theme;
  accent: Accent;
  fontScale: number;
  sendOnEnter: boolean;
  showAvatarsInGroups: boolean;
}

const KEY = 'lilika.prefs';

const DEFAULTS: Prefs = {
  theme: 'dark',
  accent: 'teal',
  fontScale: 1,
  sendOnEnter: true,
  showAvatarsInGroups: true,
};

interface UiState extends Prefs {
  /** Which side panel is open, if any. */
  panel: 'none' | 'profile' | 'settings';
  /** Narrow screens show either the list or the chat, never both. */
  mobileView: 'list' | 'chat';
  set: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
  openPanel: (panel: UiState['panel']) => void;
  setMobileView: (view: UiState['mobileView']) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  ...DEFAULTS,
  ...(readJSON<Partial<Prefs>>(KEY) ?? {}),
  panel: 'none',
  mobileView: 'list',

  set(key, value) {
    set({ [key]: value } as unknown as Partial<UiState>);
    const { theme, accent, fontScale, sendOnEnter, showAvatarsInGroups } = get();
    writeJSON(KEY, { theme, accent, fontScale, sendOnEnter, showAvatarsInGroups });
    applyTheme();
  },

  openPanel(panel) {
    set({ panel: get().panel === panel ? 'none' : panel });
  },

  setMobileView(mobileView) {
    set({ mobileView });
  },
}));

/** Writes the resolved theme onto <html> so CSS variables can switch on it. */
export function applyTheme(): void {
  const { theme, accent, fontScale } = useUiStore.getState();
  const resolved =
    theme === 'system'
      ? window.matchMedia('(prefers-color-scheme: light)').matches
        ? 'light'
        : 'dark'
      : theme;
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.dataset.accent = accent;
  root.style.setProperty('--font-scale', String(fontScale));
}

// Track the OS setting while the user is on "system".
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
  if (useUiStore.getState().theme === 'system') applyTheme();
});
