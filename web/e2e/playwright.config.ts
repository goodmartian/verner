import { defineConfig } from '@playwright/test';

// the tests look at the running app: the dev server on 5184 with the api on 8026 behind it
export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5184',
    locale: 'en-GB',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    // Google Chrome by default; `E2E_BUNDLED=1` uses the browser of `playwright install chromium`
    channel: process.env.E2E_BUNDLED ? undefined : 'chrome',
  },
});
