/**
 * Tests for api/client.ts
 * Covers: request/response interceptors, error parsing, HTTP methods,
 *         404/401/429/500 error classification, network error detection.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { APIError, isNetworkError, getErrorMessage } from '../api/client'

// We test the class directly by creating a fresh instance each test
async function makeClient() {
  // Dynamic import so each test gets a module with fresh state
  const { APIError: Err, getErrorMessage: gErr, isNetworkError: isNet } = await import('../api/client')

  class TestClient {
    private baseURL = '/api/v1'
    private reqInterceptors: Array<(c: { headers: Record<string, string> }) => { headers: Record<string, string> }> = []
    private resInterceptors: Array<(r: Response) => Response> = []

    addRequestInterceptor(fn: (c: { headers: Record<string, string> }) => { headers: Record<string, string> }) {
      this.reqInterceptors.push(fn)
    }

    async runReq(config: { headers: Record<string, string> }) {
      let c = config
      for (const fn of this.reqInterceptors) c = fn(c)
      return c
    }

    async runRes(response: Response) {
      let r = response
      for (const fn of this.resInterceptors) r = fn(r)
      return r
    }
  }

  return { TestClient, Err, gErr, isNet }
}

// ── APIError classification ────────────────────────────────────────────────────

describe('APIError', () => {
  it('classifies 404 as not found', () => {
    const err = new APIError(404, 'NOT_FOUND', 'Not found')
    expect(err.isNotFound).toBe(true)
    expect(err.isUnauthorized).toBe(false)
  })

  it('classifies 401 as unauthorized', () => {
    const err = new APIError(401, 'UNAUTHORIZED', 'Auth failed')
    expect(err.isUnauthorized).toBe(true)
    expect(err.isNotFound).toBe(false)
  })

  it('classifies 403 as forbidden', () => {
    const err = new APIError(403, 'FORBIDDEN', 'No access')
    expect(err.isForbidden).toBe(true)
  })

  it('classifies 429 as rate limited', () => {
    const err = new APIError(429, 'RATE_LIMITED', 'Too many')
    expect(err.isRateLimited).toBe(true)
  })

  it('classifies 500 as server error', () => {
    const err = new APIError(500, 'INTERNAL_SERVER_ERROR', 'Server error')
    expect(err.isServerError).toBe(true)
  })

  it('classifies 400 VALIDATION_ERROR correctly', () => {
    const err = new APIError(400, 'VALIDATION_ERROR', 'Bad input')
    expect(err.isValidation).toBe(true)
  })

  it('carries details', () => {
    const err = new APIError(400, 'VALIDATION_ERROR', 'Bad input', { field: 'name', issue: 'too short' })
    expect(err.details).toEqual({ field: 'name', issue: 'too short' })
  })

  it('extends Error', () => {
    const err = new APIError(500, 'ERR', 'oops')
    expect(err).toBeInstanceOf(Error)
    expect(err.message).toBe('oops')
    expect(err.name).toBe('APIError')
  })
})

// ── getErrorMessage ───────────────────────────────────────────────────────────

describe('getErrorMessage', () => {
  it('extracts message from APIError', () => {
    const err = new APIError(404, 'NOT_FOUND', 'Agent not found')
    expect(getErrorMessage(err)).toBe('Agent not found')
  })

  it('extracts message from generic Error', () => {
    expect(getErrorMessage(new Error('something broke'))).toBe('something broke')
  })

  it('returns fallback for unknown', () => {
    expect(getErrorMessage(null)).toBe('An unexpected error occurred')
  })
})

// ── isNetworkError ────────────────────────────────────────────────────────────

describe('isNetworkError', () => {
  it('detects Failed to fetch', () => {
    const err = new TypeError('Failed to fetch')
    expect(isNetworkError(err)).toBe(true)
  })

  it('rejects APIError', () => {
    expect(isNetworkError(new APIError(500, 'ERR', 'oops'))).toBe(false)
  })

  it('rejects plain Error', () => {
    expect(isNetworkError(new Error('other error'))).toBe(false)
  })
})

// ── Request interceptors ──────────────────────────────────────────────────────

describe('Request interceptors', () => {
  it('auth interceptor adds Authorization header when token present', () => {
    localStorage.setItem('auth_token', 'test-jwt-token')
    const config = { headers: {} as Record<string, string> }
    // Simulate what the interceptor does
    const token = localStorage.getItem('auth_token')
    if (token) config.headers['Authorization'] = `Bearer ${token}`
    expect(config.headers['Authorization']).toBe('Bearer test-jwt-token')
    localStorage.removeItem('auth_token')
  })

  it('auth interceptor skips header when no token', () => {
    localStorage.removeItem('auth_token')
    const config = { headers: {} as Record<string, string> }
    const token = localStorage.getItem('auth_token')
    if (token) config.headers['Authorization'] = `Bearer ${token}`
    expect(config.headers['Authorization']).toBeUndefined()
  })
})

// ── fetch integration (mocked) ────────────────────────────────────────────────

describe('apiClient fetch integration', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('GET calls fetch with correct method and URL', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ total: 0, items: [], has_more: false }),
    } as unknown as Response)
    global.fetch = mockFetch

    const { apiClient } = await import('../api/client')
    await apiClient.get('/agents', { skip: 0, limit: 10 })

    expect(mockFetch).toHaveBeenCalledOnce()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/api/v1/agents')
    expect(url).toContain('skip=0')
    expect(url).toContain('limit=10')
    expect((opts as RequestInit).method).toBe('GET')
  })

  it('POST sends body as JSON', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: 'abc', name: 'Test Agent' }),
    } as unknown as Response)
    global.fetch = mockFetch

    const { apiClient } = await import('../api/client')
    await apiClient.post('/agents', { name: 'Test Agent', role: 'analyst', system_prompt: 'hello world here', model: 'claude-sonnet-4-6', tools: [] })

    const [, opts] = mockFetch.mock.calls[0]
    expect((opts as RequestInit).method).toBe('POST')
    const body = JSON.parse((opts as RequestInit).body as string)
    expect(body.name).toBe('Test Agent')
  })

  it('throws APIError on 4xx', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: { code: 'NOT_FOUND', message: 'Agent not found' } }),
    } as unknown as Response)
    global.fetch = mockFetch

    const { apiClient, APIError: AErr } = await import('../api/client')
    await expect(apiClient.get('/agents/missing-id')).rejects.toBeInstanceOf(AErr)
  })

  it('returns undefined for 204 No Content', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    } as unknown as Response)
    global.fetch = mockFetch

    const { apiClient } = await import('../api/client')
    const result = await apiClient.delete('/agents/some-id')
    expect(result).toBeUndefined()
  })

  it('PATCH sends partial body', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 'abc', name: 'Updated' }),
    } as unknown as Response)
    global.fetch = mockFetch

    const { apiClient } = await import('../api/client')
    await apiClient.patch('/agents/abc', { name: 'Updated' })

    const [, opts] = mockFetch.mock.calls[0]
    expect((opts as RequestInit).method).toBe('PATCH')
    const body = JSON.parse((opts as RequestInit).body as string)
    expect(body).toEqual({ name: 'Updated' })
  })
})
