import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E configuration.
 * Run with: npx playwright test (from e2e/ directory)
 * Requires the full docker-compose stack to be running.
 *
 * Set BASE_URL env var to point at a different environment:
 *   BASE_URL=https://staging.example.com npx playwright test
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },

  // Stop on first failure in CI; run all locally
  fullyParallel: !process.env.CI,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,

  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['junit', { outputFile: 'test-results/results.xml' }],
  ],

  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
  ],

  // Global setup: ensure the stack is reachable before running tests
  globalSetup: './global-setup.ts',
})
