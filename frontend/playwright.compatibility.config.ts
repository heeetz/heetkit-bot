import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

// Opt-in real-browser matrix; the regular desktop/CI suite keeps its existing browser.
export default defineConfig({
  ...baseConfig,
  testMatch: 'browser-server.spec.ts',
  use: { ...baseConfig.use, channel: undefined },
  projects: [
    { name: 'Chrome', use: { browserName: 'chromium', channel: 'chrome' } },
    { name: 'Firefox', use: { browserName: 'firefox', channel: undefined } },
  ],
})
