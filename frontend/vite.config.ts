import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  // xfwd passes the browser's host along so the backend can build the OAuth callback URL.
  const apiProxy = {
    '/api': { target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true, xfwd: true }
  };
  return {
    plugins: [react()],
    server: { proxy: apiProxy },
    preview: { proxy: apiProxy }
  };
});
