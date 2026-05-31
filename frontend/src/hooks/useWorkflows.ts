/**
 * Workflow hooks — CRUD + execute
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  workflowsApi,
  type BackendWorkflow,
  type CreateWorkflowPayload,
  type UpdateWorkflowPayload,
  type ExecuteWorkflowPayload,
  type ExecuteWorkflowResponse,
} from '../api/workflows'
import { getErrorMessage } from '../api/client'

const CACHE_TTL_MS = 30_000

const listCache = {
  data: null as BackendWorkflow[] | null,
  total: 0,
  fetchedAt: 0,
  isValid(): boolean {
    return this.data !== null && Date.now() - this.fetchedAt < CACHE_TTL_MS
  },
  set(items: BackendWorkflow[], total: number) {
    this.data = items; this.total = total; this.fetchedAt = Date.now()
  },
  invalidate() { this.data = null; this.fetchedAt = 0 },
}

// ── useWorkflows ──────────────────────────────────────────────────────────────

export function useWorkflows(params?: { skip?: number; limit?: number; is_active?: boolean }) {
  const { skip = 0, limit = 20, is_active } = params ?? {}
  const [workflows, setWorkflows] = useState<BackendWorkflow[]>(listCache.data ?? [])
  const [total, setTotal] = useState(listCache.total)
  const [loading, setLoading] = useState(!listCache.isValid())
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetch = useCallback(async (force = false) => {
    if (!force && listCache.isValid()) {
      setWorkflows(listCache.data!)
      setTotal(listCache.total)
      setLoading(false)
      return
    }
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setLoading(true)
    setError(null)
    try {
      const res = await workflowsApi.list({ skip, limit, is_active })
      listCache.set(res.items, res.total)
      setWorkflows(res.items)
      setTotal(res.total)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [skip, limit, is_active])

  useEffect(() => {
    fetch()
    return () => abortRef.current?.abort()
  }, [fetch])

  const refetch = useCallback(() => { listCache.invalidate(); return fetch(true) }, [fetch])

  return { workflows, total, loading, error, refetch }
}

// ── useWorkflow (single) ──────────────────────────────────────────────────────

export function useWorkflow(id: string | undefined) {
  const [workflow, setWorkflow] = useState<BackendWorkflow | null>(null)
  const [loading, setLoading] = useState(!!id)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    if (!id) return
    setLoading(true); setError(null)
    try {
      setWorkflow(await workflowsApi.get(id))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetch() }, [fetch])
  return { workflow, loading, error, refetch: fetch }
}

// ── useCreateWorkflow ─────────────────────────────────────────────────────────

export function useCreateWorkflow() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (payload: CreateWorkflowPayload): Promise<BackendWorkflow | null> => {
    setLoading(true); setError(null)
    try {
      const wf = await workflowsApi.create(payload)
      listCache.invalidate()
      return wf
    } catch (err) {
      setError(getErrorMessage(err)); return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}

// ── useUpdateWorkflow ─────────────────────────────────────────────────────────

export function useUpdateWorkflow() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (id: string, payload: UpdateWorkflowPayload): Promise<BackendWorkflow | null> => {
    setLoading(true); setError(null)
    try {
      const wf = await workflowsApi.update(id, payload)
      listCache.invalidate()
      return wf
    } catch (err) {
      setError(getErrorMessage(err)); return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}

// ── useExecuteWorkflow ────────────────────────────────────────────────────────

export function useExecuteWorkflow() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (
    id: string,
    payload?: ExecuteWorkflowPayload,
  ): Promise<ExecuteWorkflowResponse | null> => {
    setLoading(true); setError(null)
    try {
      return await workflowsApi.execute(id, payload)
    } catch (err) {
      setError(getErrorMessage(err)); return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}
