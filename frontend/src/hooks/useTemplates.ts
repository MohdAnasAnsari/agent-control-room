/**
 * Template hooks — list, search, clone agents and workflows
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  templatesApi,
  type AgentTemplate,
  type WorkflowTemplate,
  type TemplateSortOption,
  type ClonedAgent,
  type ClonedWorkflow,
} from '../api/templates'
import { getErrorMessage } from '../api/client'

// ── useAgentTemplates ─────────────────────────────────────────────────────────

export interface UseAgentTemplatesOptions {
  category?: string
  sort?: TemplateSortOption
  q?: string
}

export function useAgentTemplates(options: UseAgentTemplatesOptions = {}) {
  const { category, sort = 'popularity', q } = options
  const [templates, setTemplates] = useState<AgentTemplate[]>([])
  const [categories, setCategories] = useState<string[]>(['All'])
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
      const res = await templatesApi.listAgents({
        category: category === 'All' ? undefined : category,
        sort,
        q: q || undefined,
      })
      setTemplates(res.items)
      setCategories(res.categories)
      setTotal(res.total)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [category, sort, q])

  useEffect(() => {
    fetch()
    return () => abortRef.current?.abort()
  }, [fetch])

  return { templates, categories, total, loading, error, refetch: fetch }
}

// ── useWorkflowTemplates ──────────────────────────────────────────────────────

export function useWorkflowTemplates(options: UseAgentTemplatesOptions = {}) {
  const { category, sort = 'popularity', q } = options
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [categories, setCategories] = useState<string[]>(['All'])
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
      const res = await templatesApi.listWorkflows({
        category: category === 'All' ? undefined : category,
        sort,
        q: q || undefined,
      })
      setTemplates(res.items)
      setCategories(res.categories)
      setTotal(res.total)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [category, sort, q])

  useEffect(() => {
    fetch()
    return () => abortRef.current?.abort()
  }, [fetch])

  return { templates, categories, total, loading, error, refetch: fetch }
}

// ── useCloneAgentTemplate ─────────────────────────────────────────────────────

export function useCloneAgentTemplate() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clone = useCallback(async (templateId: string): Promise<ClonedAgent | null> => {
    setLoading(true)
    setError(null)
    try {
      return await templatesApi.cloneAgent(templateId)
    } catch (err) {
      setError(getErrorMessage(err))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { clone, loading, error }
}

// ── useCloneWorkflowTemplate ──────────────────────────────────────────────────

export function useCloneWorkflowTemplate() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clone = useCallback(async (templateId: string): Promise<ClonedWorkflow | null> => {
    setLoading(true)
    setError(null)
    try {
      return await templatesApi.cloneWorkflow(templateId)
    } catch (err) {
      setError(getErrorMessage(err))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  return { clone, loading, error }
}
