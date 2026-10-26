// Vitest for the whole web workspace: the packages' and the studio's tests run
// in jsdom with Testing Library; no test reaches a network (the API client is
// given a fake fetch — test/harness.tsx).
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    include: ['packages/*/test/**/*.test.{ts,tsx}', 'studio/test/**/*.test.{ts,tsx}'],
  },
});
