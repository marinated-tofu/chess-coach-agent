import { defineConfig, devices } from '@playwright/test';

const backend = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000';
const frontend = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: './e2e',
  testMatch: ['demo-walkthrough.spec.ts', 'presentation-screenshots.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 480_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  outputDir: './demo-recordings',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: frontend,
    // Fail fast on a missing element instead of burning the whole 8-minute budget.
    actionTimeout: 20_000,
    headless: true,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    video: {
      mode: 'on',
      size: { width: 1440, height: 900 }
    },
    launchOptions: {
      slowMo: 150
    },
    trace: 'off',
    screenshot: 'off'
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1
      }
    }
  ],
  webServer: [
    {
      // The demo expects the already-populated backend; this only starts one if none is running.
      command: 'cd ../backend && uv run uvicorn chess_coach_agent.api:app --host 127.0.0.1 --port 8000',
      url: `${backend}/api/health`,
      reuseExistingServer: true,
      timeout: 120_000
    },
    {
      command: 'npm run dev',
      url: frontend,
      reuseExistingServer: true,
      timeout: 120_000
    }
  ]
});
