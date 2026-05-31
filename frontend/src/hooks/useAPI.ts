import { useState, useCallback, useRef } from 'react'
import type { APIError } from '../types'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Token accessor — set by AuthProvider so the API client can read the current token
// without importing useAuth (which would create a circular dep).
let _getToken: (() => string | null) | null = null

export function setTokenAccessor(fn: () => string | null) {
  _getToken = fn
}

export function getToken(): string | null {
  return _getToken?.() ?? null
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  params?: Record<string, string | number | boolean | undefined>
}

interface APIState<T> {
  data: T | null
  loading: boolean
  error: APIError | null
}

function buildURL(path: string, params?: Record<string, string | number | boolean | undefined>): string {
  const url = new URL(`${BASE_URL}${path}`)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) url.searchParams.set(key, String(value))
    })
  }
  return url.toString()
}

async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, params, ...rest } = options
  const url = buildURL(path, params)

  // Attach Bearer token when available
  const token = _getToken?.()
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

  const response = await fetch(url, {
    ...rest,
    credentials: 'include',  // needed for refresh_token cookie
    headers: {
      'Content-Type': 'application/json',
      ...authHeader,
      ...rest.headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401) {
    // Notify the app that auth has expired so it can redirect to login
    window.dispatchEvent(new CustomEvent('auth:expired'))
  }

  if (!response.ok) {
    let error: APIError
    try {
      error = await response.json()
    } catch {
      error = { message: `HTTP ${response.status}: ${response.statusText}` }
    }
    throw error
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function useAPI<T>() {
  const [state, setState] = useState<APIState<T>>({
    data: null,
    loading: false,
    error: null,
  })

  const abortRef = useRef<AbortController | null>(null)

  const execute = useCallback(async (path: string, options: RequestOptions = {}) => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    setState(prev => ({ ...prev, loading: true, error: null }))

    try {
      const data = await apiFetch<T>(path, {
        ...options,
        signal: abortRef.current.signal,
      })
      setState({ data, loading: false, error: null })
      return data
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      const error = err as APIError
      setState(prev => ({ ...prev, loading: false, error }))
      throw error
    }
  }, [])

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null })
  }, [])

  return { ...state, execute, reset }
}

// Debounce utility for search inputs
export function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const update = useCallback((v: T) => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setDebounced(v), delay)
  }, [delay])

  update(value)
  return debounced
}

// Convenience typed fetch helpers
export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    apiFetch<T>(path, { method: 'GET', params }),

  post: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: 'POST', body }),

  put: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: 'PUT', body }),

  patch: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: 'PATCH', body }),

  delete: <T>(path: string) =>
    apiFetch<T>(path, { method: 'DELETE' }),
}
