import { defineConfig, devices } from '@playwright/test';

const backend = process.env.PLAYWRIGHT_BACKEND_URL || 'http://127.0.0.1:8000';
const frontend = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  use: {
    baseURL: frontend,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure'
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run alembic upgrade head && uv run uvicorn chess_coach_agent.api:app --host 127.0.0.1 --port 8000',
      url: `${backend}/api/health`,
      reuseExistingServer: true,
      timeout: 120_000
    },
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 4173',
      url: frontend,
      reuseExistingServer: true,
      timeout: 120_000
    }
  ]
});
