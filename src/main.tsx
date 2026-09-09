import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { useAuthStore } from './store/authStore';
import { useChatStore } from './store/chatStore';
import { useUiStore, applyTheme } from './store/uiStore';
import './styles/theme.css';
import './styles/app.css';

// Stamp the stored theme before the first paint so there is no light flash.
applyTheme();

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

if (import.meta.env.DEV) {
  // Dev-only handle so the UI can be driven from a test harness without a live
  // Telegram connection. Stripped from production builds.
  (window as unknown as Record<string, unknown>).__lilika = {
    auth: useAuthStore,
    chat: useChatStore,
    ui: useUiStore,
  };
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
