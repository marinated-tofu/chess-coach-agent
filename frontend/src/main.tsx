import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

// `?theme=classic` brings back the original palette; `?theme=study` returns to the default.
function applyTheme() {
  try {
    const requested = new URLSearchParams(window.location.search).get('theme');
    if (requested) localStorage.setItem('theme', requested);
    const theme = requested ?? localStorage.getItem('theme');
    if (theme === 'classic') document.documentElement.dataset.theme = 'classic';
  } catch {
    // Storage can be blocked; the default palette still applies.
  }
}
applyTheme();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
