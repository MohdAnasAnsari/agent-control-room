import { request } from '@playwright/test'

/**
 * Runs once before all tests.
 * Waits up to 60 s for the backend /health endpoint to respond so tests
 * don't fail with connection-refused when the stack is still starting.
 */
async function globalSetup(): Promise<void> {
  const backendURL = process.env.BACKEND_URL ?? 'http://localhost:8000'
  const ctx = await request.newContext()
  const deadline = Date.now() + 60_000

  while (Date.now() < deadline) {
    try {
      const res = await ctx.get(`${backendURL}/health`)
      if (res.ok()) {
        console.log(`Backend ready at ${backendURL}`)
        await ctx.dispose()
        return
      }
    } catch {
      // not yet reachable
    }
    await new Promise(r => setTimeout(r, 2000))
  }

  await ctx.dispose()
  throw new Error(`Backend at ${backendURL}/health did not become ready within 60 s`)
}

export default globalSetup
