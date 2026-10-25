import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './demo-e2e',
  use: { baseURL: 'http://127.0.0.1:4174', browserName: 'chromium', channel: process.env.PLAYWRIGHT_CHANNEL || undefined },
  webServer: {
    command: 'node ./node_modules/vite/bin/vite.js --mode demo --host 127.0.0.1 --port 4174 --strictPort',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: !process.env.CI,
  },
})
