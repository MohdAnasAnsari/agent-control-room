/**
 * Agent hooks — CRUD with 30s TTL cache, optimistic updates
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { agentsApi, type BackendAgent, type CreateAgentPayload, type UpdateAgentPayload } from '../api/agents'
import { getErrorMessage } from '../api/client'

const CACHE_TTL_MS = 30_000

// ── Simple in-memory cache ────────────────────────────────────────────────────
const listCache = {
  data: null as BackendAgent[] | null,
  total: 0,
  fetchedAt: 0,
  isValid(): boolean {
    return this.data !== null && Date.now() - this.fetchedAt < CACHE_TTL_MS
  },
  set(items: BackendAgent[], total: number) {
    this.data = items
    this.total = total
    this.fetchedAt = Date.now()
  },
  invalidate() {
    this.data = null
    this.fetchedAt = 0
  },
}

// ── useAgents ─────────────────────────────────────────────────────────────────

export interface UseAgentsOptions {
  skip?: number
  limit?: number
  role?: string
  status?: string
}

export function useAgents(options: UseAgentsOptions = {}) {
  const { skip = 0, limit = 20, role, status } = options
  const [agents, setAgents] = useState<BackendAgent[]>(listCache.data ?? [])
  const [total, setTotal] = useState(listCache.total)
  const [loading, setLoading] = useState(!listCache.isValid())
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetch = useCallback(async (force = false) => {
    if (!force && listCache.isValid()) {
      setAgents(listCache.data!)
      setTotal(listCache.total)
      setLoading(false)
      return
    }

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    setLoading(true)
    setError(null)
    try {
      const res = await agentsApi.list({ skip, limit, role, status })
      listCache.set(res.items, res.total)
      setAgents(res.items)
      setTotal(res.total)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(getErrorMessage(err))
      }
    } finally {
      setLoading(false)
    }
  }, [skip, limit, role, status])

  useEffect(() => {
    fetch()
    return () => abortRef.current?.abort()
  }, [fetch])

  const refetch = useCallback(() => {
    listCache.invalidate()
    return fetch(true)
  }, [fetch])

  return { agents, total, loading, error, refetch }
}

// ── useAgent (single) ─────────────────────────────────────────────────────────

export function useAgent(id: string | undefined) {
  const [agent, setAgent] = useState<BackendAgent | null>(null)
  const [loading, setLoading] = useState(!!id)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const data = await agentsApi.get(id)
      setAgent(data)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetch() }, [fetch])

  return { agent, loading, error, refetch: fetch }
}

// ── useCreateAgent ────────────────────────────────────────────────────────────

export function useCreateAgent() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (payload: CreateAgentPayload): Promise<BackendAgent | null> => {
    setLoading(true)
    setError(null)
    try {
      const agent = await agentsApi.create(payload)
      listCache.invalidate()
      return agent
    } catch (err) {
      setError(getErrorMessage(err))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}

// ── useUpdateAgent ────────────────────────────────────────────────────────────

export function useUpdateAgent() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (id: string, payload: UpdateAgentPayload): Promise<BackendAgent | null> => {
    setLoading(true)
    setError(null)
    try {
      const updated = await agentsApi.update(id, payload)
      listCache.invalidate()
      return updated
    } catch (err) {
      setError(getErrorMessage(err))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}

// ── useDeleteAgent ────────────────────────────────────────────────────────────

export function useDeleteAgent() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (id: string): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      await agentsApi.delete(id)
      listCache.invalidate()
      return true
    } catch (err) {
      setError(getErrorMessage(err))
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}
