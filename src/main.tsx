import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyTheme } from './store/uiStore';
import './styles/theme.css';
import './styles/app.css';

// Stamp the stored theme before the first paint so there is no light flash.
applyTheme();

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
