import { useEffect } from 'react';
import { ApiSetup } from './components/setup/ApiSetup';
import { AuthScreen } from './components/auth/AuthScreen';
import { Sidebar } from './components/sidebar/Sidebar';
import { ChatView } from './components/chat/ChatView';
import { ProfilePanel } from './components/panels/ProfilePanel';
import { SettingsPanel } from './components/panels/SettingsPanel';
import { Spinner } from './components/common/Spinner';
import { branding } from './config';
import { useAuthStore } from './store/authStore';
import { useChatStore } from './store/chatStore';
import { useUiStore } from './store/uiStore';

export function App() {
  const stage = useAuthStore((s) => s.stage);
  const user = useAuthStore((s) => s.user);
  const boot = useAuthStore((s) => s.boot);

  useEffect(() => {
    void boot();
  }, [boot]);

  if (stage === 'booting') {
    return (
      <div className="boot-screen">
        <Spinner />
        <p style={{ color: 'var(--text-secondary)' }}>{branding.name} در حال آماده‌سازی…</p>
      </div>
    );
  }

  if (stage === 'needsCredentials') return <ApiSetup />;
  if (stage !== 'ready' || !user) return <AuthScreen />;

  return <Shell selfId={user.id} />;
}

function Shell({ selfId }: { selfId: string }) {
  const init = useChatStore((s) => s.init);
  const teardown = useChatStore((s) => s.teardown);
  const connected = useChatStore((s) => s.connected);
  const panel = useUiStore((s) => s.panel);
  const mobileView = useUiStore((s) => s.mobileView);

  useEffect(() => {
    void init(selfId);
    return () => teardown();
  }, [selfId, init, teardown]);

  return (
    <>
      {!connected && <div className="offline-banner">در حال اتصال دوباره…</div>}
      <div
        className={panel === 'none' ? 'shell' : 'shell with-panel'}
        data-mobile-view={mobileView}
      >
        <Sidebar />
        <ChatView />
        {panel === 'profile' && <ProfilePanel />}
        {panel === 'settings' && <SettingsPanel />}
      </div>
    </>
  );
}
