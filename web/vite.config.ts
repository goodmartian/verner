import react from '@vitejs/plugin-react';
import { configDefaults, defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  build: {
    // the map library alone is about 1 MB; it loads in its own chunk
    chunkSizeWarningLimit: 1100,
  },
  server: {
    port: 5184,
    // the api; SENDA_API points it elsewhere
    proxy: { '/api': process.env.SENDA_API ?? 'http://127.0.0.1:8026' },
  },
  test: {
    maxWorkers: 4,
    exclude: [...configDefaults.exclude, 'e2e/**'],
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
    setupFiles: ['./src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
});
