/**
 * Execution hooks — list, detail, delete, metrics
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { executionsApi, type BackendExecution, type MetricsResponse } from '../api/executions'
import { getErrorMessage } from '../api/client'

// ── useExecutions ─────────────────────────────────────────────────────────────

export function useExecutions(params?: {
  skip?: number
  limit?: number
  status?: string
  workflow_id?: string
}) {
  const { skip = 0, limit = 20, status, workflow_id } = params ?? {}
  const [executions, setExecutions] = useState<BackendExecution[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fetch = useCallback(async () => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setLoading(true)
    setError(null)
    try {
      const res = await executionsApi.list({ skip, limit, status, workflow_id })
      setExecutions(res.items)
      setTotal(res.total)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [skip, limit, status, workflow_id])

  useEffect(() => {
    fetch()
    return () => abortRef.current?.abort()
  }, [fetch])

  return { executions, total, loading, error, refetch: fetch }
}

// ── useExecution (single) ─────────────────────────────────────────────────────

export function useExecution(id: string | undefined) {
  const [execution, setExecution] = useState<BackendExecution | null>(null)
  const [loading, setLoading] = useState(!!id)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    if (!id) return
    setLoading(true); setError(null)
    try {
      setExecution(await executionsApi.get(id))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetch() }, [fetch])
  return { execution, loading, error, refetch: fetch }
}

// ── useDeleteExecution ────────────────────────────────────────────────────────

export function useDeleteExecution() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (id: string): Promise<boolean> => {
    setLoading(true); setError(null)
    try {
      await executionsApi.delete(id)
      return true
    } catch (err) {
      setError(getErrorMessage(err)); return false
    } finally {
      setLoading(false)
    }
  }, [])

  return { mutate, loading, error }
}

// ── useMetrics ────────────────────────────────────────────────────────────────

export function useMetrics() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      setMetrics(await executionsApi.metrics())
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetch() }, [fetch])
  return { metrics, loading, error, refetch: fetch }
}
