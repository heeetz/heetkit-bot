import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  outputDir: './node_modules/.tmp/playwright-results',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    browserName: 'chromium',
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `${process.platform === 'win32' ? 'npm.cmd' : 'npm'} run dev -- --host 127.0.0.1 --port 5174 --strictPort`,
    url: 'http://127.0.0.1:5174',
  },
})
