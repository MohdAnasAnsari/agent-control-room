import { test, expect, Page } from '@playwright/test'

// ── Helpers ───────────────────────────────────────────────────────────────────

const TEST_USER = {
  email: `e2e-${Date.now()}@test.local`,
  password: 'E2eTest!Pass1',
}

async function register(page: Page): Promise<void> {
  await page.goto('/register')
  await page.getByLabel(/email/i).fill(TEST_USER.email)
  await page.getByLabel(/password/i).first().fill(TEST_USER.password)
  await page.getByRole('button', { name: /register|sign up/i }).click()
  await expect(page).toHaveURL(/dashboard|\//, { timeout: 10_000 })
}

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel(/email/i).fill(TEST_USER.email)
  await page.getByLabel(/password/i).fill(TEST_USER.password)
  await page.getByRole('button', { name: /login|sign in/i }).click()
  await expect(page).toHaveURL(/dashboard|\//, { timeout: 10_000 })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Authentication', () => {
  test('user can register and land on dashboard', async ({ page }) => {
    await register(page)
    await expect(page.getByText(/dashboard|orchestrator/i)).toBeVisible()
  })

  test('user can log out and log back in', async ({ page }) => {
    await login(page)
    // Find and click logout (button, link, or menu item)
    const logoutBtn = page.getByRole('button', { name: /logout|sign out/i })
    await logoutBtn.click()
    await expect(page).toHaveURL(/login/)

    // Log back in
    await login(page)
    await expect(page).not.toHaveURL(/login/)
  })

  test('invalid credentials show an error', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel(/email/i).fill('nobody@nowhere.test')
    await page.getByLabel(/password/i).fill('wrong')
    await page.getByRole('button', { name: /login|sign in/i }).click()
    await expect(
      page.getByText(/invalid|incorrect|unauthorized|wrong/i)
    ).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('Agent Management', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('create a new agent', async ({ page }) => {
    await page.goto('/agents')
    await page.getByRole('button', { name: /create|new agent/i }).click()

    await page.getByLabel(/name/i).fill('E2E Test Agent')
    await page.getByLabel(/role/i).fill('Summarizer')
    // Fill in system prompt if the field exists
    const promptField = page.getByLabel(/system prompt/i)
    if (await promptField.count()) {
      await promptField.fill('You are a helpful summarizer agent created by E2E tests.')
    }

    await page.getByRole('button', { name: /save|create|submit/i }).click()

    await expect(
      page.getByText(/E2E Test Agent/i)
    ).toBeVisible({ timeout: 10_000 })
  })
})

test.describe('Workflow Creation → Execution → Monitoring', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('full workflow lifecycle', async ({ page }) => {
    // ── Step 1: Create workflow ──────────────────────────────────────────────
    await page.goto('/workflows')
    await page.getByRole('button', { name: /create|new workflow/i }).click()

    await page.getByLabel(/name/i).fill('E2E Smoke Workflow')
    await page.getByRole('button', { name: /save|create|submit/i }).click()

    await expect(
      page.getByText(/E2E Smoke Workflow/i)
    ).toBeVisible({ timeout: 10_000 })

    // ── Step 2: Execute the workflow ──────────────────────────────────────────
    const executeBtn = page.getByRole('button', { name: /execute|run/i }).first()
    await executeBtn.click()

    // The execution may require a prompt / input
    const promptInput = page.getByPlaceholder(/input|prompt|message/i)
    if (await promptInput.count()) {
      await promptInput.fill('Summarize: The quick brown fox jumps over the lazy dog.')
    }

    const confirmBtn = page.getByRole('button', { name: /confirm|run|execute|start/i })
    if (await confirmBtn.count()) {
      await confirmBtn.click()
    }

    // ── Step 3: Navigate to execution list and verify ─────────────────────────
    await page.goto('/executions')
    await expect(page.getByText(/pending|running|completed/i).first()).toBeVisible({
      timeout: 15_000,
    })
  })

  test('execution detail page renders without errors', async ({ page }) => {
    await page.goto('/executions')

    // Click the first execution row if any exist
    const firstRow = page.getByRole('row').nth(1)
    if (await firstRow.count()) {
      await firstRow.click()
      // Should land on a detail page (no 404 / unhandled error)
      await expect(page.getByRole('heading')).toBeVisible({ timeout: 5_000 })
    } else {
      test.skip()
    }
  })
})

test.describe('API Health', () => {
  test('backend /health returns 200', async ({ request }) => {
    const backendURL = process.env.BACKEND_URL ?? 'http://localhost:8000'
    const response = await request.get(`${backendURL}/health`)
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
  })

  test('frontend loads without console errors', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })

    await page.goto('/')
    // Allow minor React dev warnings; fail only on actual errors
    const criticalErrors = errors.filter(
      (e) => !e.includes('Warning:') && !e.includes('DevTools')
    )
    expect(criticalErrors).toHaveLength(0)
  })
})
