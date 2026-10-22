// The studio's build. `npm run dev` serves it at http://localhost:5173/studio/
// and proxies the platform's paths to PLATFORM_URL (default
// http://127.0.0.1:8000), so the session cookie and CSRF token work as they do
// in production. `npm run build` writes dist/ with its asset URLs under
// /static/studio/, where the platform serves its static files; the platform
// answers every /studio/ path with dist/index.html (content/api/studio.py),
// replacing the CSP nonce placeholder below on each request.
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const PLATFORM = process.env.PLATFORM_URL ?? 'http://127.0.0.1:8000';

export default defineConfig(({ command }) => ({
  base: command === 'build' ? (process.env.STUDIO_BASE ?? '/static/studio/') : '/studio/',
  plugins: [react()],
  html: { cspNonce: '__CSP_NONCE__' },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: {
    port: 5173,
    proxy: { '/api': PLATFORM, '/admin': PLATFORM, '/static': PLATFORM },
  },
}));
