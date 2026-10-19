/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  // Amplify UI is one large chunk; acceptable for a single-user internal form.
  build: { chunkSizeWarningLimit: 1500 },
  test: { environment: 'jsdom' },
});
