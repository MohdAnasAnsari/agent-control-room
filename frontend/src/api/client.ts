/**
 * API Client — fetch-based with interceptor pattern
 *
 * Provides:
 *  • Request interceptors (e.g. attach auth token)
 *  • Response interceptors (e.g. 401 redirect, retry logic)
 *  • Typed error objects matching backend {"error":{"code","message","details"}}
 *  • Convenience methods: get / post / patch / put / delete
 *  • Automatic query-string serialization
 *
 * Usage:
 *   import { apiClient } from './client'
 *   const agents = await apiClient.get<PaginatedResponse<Agent>>('/agents')
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export interface APIErrorPayload {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}

export class APIError extends Error {
  code: string
  details?: Record<string, unknown>
  status: number

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'APIError'
    this.status = status
    this.code = code
    this.details = details
  }

  get isNotFound()       { return this.status === 404 }
  get isUnauthorized()   { return this.status === 401 }
  get isForbidden()      { return this.status === 403 }
  get isRateLimited()    { return this.status === 429 }
  get isServerError()    { return this.status >= 500 }
  get isValidation()     { return this.status === 400 && this.code === 'VALIDATION_ERROR' }
}

export interface RequestConfig {
  headers: Record<string, string>
  signal?: AbortSignal
}

type RequestInterceptor = (config: RequestConfig) => RequestConfig | Promise<RequestConfig>
type ResponseInterceptor = (response: Response) => Response | Promise<Response>

// ── Client class ──────────────────────────────────────────────────────────────

class APIClient {
  private readonly baseURL: string
  private readonly requestInterceptors: RequestInterceptor[] = []
  private readonly responseInterceptors: ResponseInterceptor[] = []

  constructor(baseURL: string) {
    this.baseURL = baseURL.replace(/\/$/, '')
  }

  /** Register a function to run before every request. */
  addRequestInterceptor(fn: RequestInterceptor): void {
    this.requestInterceptors.push(fn)
  }

  /** Register a function to run on every successful response. */
  addResponseInterceptor(fn: ResponseInterceptor): void {
    this.responseInterceptors.push(fn)
  }

  private buildURL(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
    const url = new URL(`${this.baseURL}${path}`, window.location.origin)
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
      })
    }
    return url.pathname + url.search
  }

  private async runRequestInterceptors(config: RequestConfig): Promise<RequestConfig> {
    let c = config
    for (const interceptor of this.requestInterceptors) {
      c = await interceptor(c)
    }
    return c
  }

  private async runResponseInterceptors(response: Response): Promise<Response> {
    let r = response
    for (const interceptor of this.responseInterceptors) {
      r = await interceptor(r)
    }
    return r
  }

  private async parseError(response: Response): Promise<APIError> {
    try {
      const payload: APIErrorPayload = await response.json()
      const { code, message, details } = payload.error ?? {}
      return new APIError(response.status, code ?? 'UNKNOWN', message ?? response.statusText, details)
    } catch {
      return new APIError(response.status, 'HTTP_ERROR', response.statusText)
    }
  }

  async request<T>(
    method: string,
    path: string,
    options: {
      body?: unknown
      params?: Record<string, string | number | boolean | undefined | null>
      signal?: AbortSignal
    } = {}
  ): Promise<T> {
    let config: RequestConfig = {
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      signal: options.signal,
    }

    config = await this.runRequestInterceptors(config)

    const { headers, signal } = config
    const url = this.buildURL(path, options.params)

    let response = await fetch(url, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal,
    })

    response = await this.runResponseInterceptors(response)

    if (!response.ok) {
      throw await this.parseError(response)
    }

    if (response.status === 204) return undefined as T
    return response.json() as Promise<T>
  }

  get<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>, signal?: AbortSignal): Promise<T> {
    return this.request<T>('GET', path, { params, signal })
  }

  post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>('POST', path, { body, signal })
  }

  patch<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>('PATCH', path, { body, signal })
  }

  put<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>('PUT', path, { body, signal })
  }

  delete<T = void>(path: string, signal?: AbortSignal): Promise<T> {
    return this.request<T>('DELETE', path, { signal })
  }
}

// ── Singleton ─────────────────────────────────────────────────────────────────

export const apiClient = new APIClient('/api/v1')

// ── Request interceptor: attach auth token ────────────────────────────────────
apiClient.addRequestInterceptor((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// ── Response interceptor: 401 → clear session ─────────────────────────────────
apiClient.addResponseInterceptor((response) => {
  if (response.status === 401) {
    localStorage.removeItem('auth_token')
    // Avoid redirect loop on the login page itself
    if (!window.location.pathname.startsWith('/login')) {
      window.dispatchEvent(new CustomEvent('auth:expired'))
    }
  }
  return response
})

// ── Response interceptor: 429 → dispatch event with retry-after seconds ──────
apiClient.addResponseInterceptor((response) => {
  if (response.status === 429) {
    const retryAfter = parseInt(response.headers.get('Retry-After') ?? '60', 10)
    window.dispatchEvent(
      new CustomEvent<RateLimitExceededDetail>('ratelimit:exceeded', {
        detail: { retryAfter: isNaN(retryAfter) ? 60 : retryAfter },
      })
    )
  }
  return response
})

export interface RateLimitExceededDetail {
  retryAfter: number
}

// ── Helpers for formatting errors user-facing ────────────────────────────────

export function getErrorMessage(err: unknown): string {
  if (err instanceof APIError) return err.message
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred'
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError && err.message === 'Failed to fetch'
}
