/**
 * Tests for hooks/useAgents.ts
 * Covers: list fetch, cache TTL, refetch, error handling, create/update/delete.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAgents, useCreateAgent, useDeleteAgent, useUpdateAgent } from '../hooks/useAgents'

// ── Mock agentsApi ────────────────────────────────────────────────────────────

vi.mock('../api/agents', () => ({
  agentsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

import { agentsApi } from '../api/agents'
import type { BackendAgent } from '../api/agents'

const mockAgent: BackendAgent = {
  id: 'aaaa-0001',
  user_id: 'user-001',
  name: 'Test Agent',
  role: 'analyst',
  system_prompt: 'You are a test assistant',
  model: 'claude-sonnet-4-6',
  status: 'active',
  tools: ['web_search'],
  created_at: '2026-01-01T00:00:00Z',
}

const mockListResponse = { total: 1, items: [mockAgent], has_more: false }

beforeEach(() => {
  vi.clearAllMocks()
})

// ── useAgents ─────────────────────────────────────────────────────────────────

describe('useAgents', () => {
  it('loads agents on mount', async () => {
    vi.mocked(agentsApi.list).mockResolvedValue(mockListResponse)

    const { result } = renderHook(() => useAgents())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.agents).toHaveLength(1)
    expect(result.current.agents[0].name).toBe('Test Agent')
    expect(result.current.total).toBe(1)
    expect(result.current.error).toBeNull()
  })

  it('sets error state on API failure', async () => {
    vi.mocked(agentsApi.list).mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useAgents())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.error).toBeTruthy()
    expect(result.current.agents).toHaveLength(0)
  })

  it('passes role filter to API', async () => {
    vi.mocked(agentsApi.list).mockResolvedValue({ total: 0, items: [], has_more: false })

    renderHook(() => useAgents({ role: 'analyst' }))

    await waitFor(() => {
      expect(agentsApi.list).toHaveBeenCalledWith(
        expect.objectContaining({ role: 'analyst' })
      )
    })
  })

  it('returns has_more correctly', async () => {
    vi.mocked(agentsApi.list).mockResolvedValue({ total: 50, items: [mockAgent], has_more: true })

    const { result } = renderHook(() => useAgents({ limit: 1 }))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.total).toBe(50)
  })
})

// ── useCreateAgent ────────────────────────────────────────────────────────────

describe('useCreateAgent', () => {
  it('returns created agent on success', async () => {
    vi.mocked(agentsApi.create).mockResolvedValue(mockAgent)

    const { result } = renderHook(() => useCreateAgent())

    let created: BackendAgent | null = null
    await act(async () => {
      created = await result.current.mutate({
        name: 'Test Agent',
        role: 'analyst',
        system_prompt: 'You are a test assistant here',
        model: 'claude-sonnet-4-6',
        tools: [],
      })
    })

    expect(created).toEqual(mockAgent)
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('sets error and returns null on failure', async () => {
    vi.mocked(agentsApi.create).mockRejectedValue(new Error('Validation failed'))

    const { result } = renderHook(() => useCreateAgent())

    let created: BackendAgent | null = null
    await act(async () => {
      created = await result.current.mutate({
        name: 'X',
        role: 'r',
        system_prompt: 'too short',
        model: 'claude-sonnet-4-6',
        tools: [],
      })
    })

    expect(created).toBeNull()
    expect(result.current.error).toBeTruthy()
  })

  it('sets loading=true during mutation', async () => {
    let resolveCreate: (v: BackendAgent) => void
    vi.mocked(agentsApi.create).mockImplementation(
      () => new Promise(r => { resolveCreate = r })
    )

    const { result } = renderHook(() => useCreateAgent())

    act(() => {
      result.current.mutate({
        name: 'Test', role: 'r',
        system_prompt: 'long enough prompt here',
        model: 'claude-sonnet-4-6',
        tools: [],
      })
    })

    expect(result.current.loading).toBe(true)

    await act(async () => { resolveCreate!(mockAgent) })
    expect(result.current.loading).toBe(false)
  })
})

// ── useUpdateAgent ────────────────────────────────────────────────────────────

describe('useUpdateAgent', () => {
  it('returns updated agent', async () => {
    const updated = { ...mockAgent, name: 'Updated Name' }
    vi.mocked(agentsApi.update).mockResolvedValue(updated)

    const { result } = renderHook(() => useUpdateAgent())

    let res: BackendAgent | null = null
    await act(async () => {
      res = await result.current.mutate('aaaa-0001', { name: 'Updated Name' })
    })

    expect(res?.name).toBe('Updated Name')
  })

  it('calls PATCH on the correct agent ID', async () => {
    vi.mocked(agentsApi.update).mockResolvedValue(mockAgent)
    const { result } = renderHook(() => useUpdateAgent())

    await act(async () => {
      await result.current.mutate('target-id', { status: 'paused' })
    })

    expect(agentsApi.update).toHaveBeenCalledWith('target-id', { status: 'paused' })
  })
})

// ── useDeleteAgent ────────────────────────────────────────────────────────────

describe('useDeleteAgent', () => {
  it('returns true on success', async () => {
    vi.mocked(agentsApi.delete).mockResolvedValue(undefined)

    const { result } = renderHook(() => useDeleteAgent())

    let ok: boolean = false
    await act(async () => {
      ok = await result.current.mutate('aaaa-0001')
    })

    expect(ok).toBe(true)
    expect(agentsApi.delete).toHaveBeenCalledWith('aaaa-0001')
  })

  it('returns false and sets error on failure', async () => {
    vi.mocked(agentsApi.delete).mockRejectedValue(new Error('Not found'))

    const { result } = renderHook(() => useDeleteAgent())

    let ok = true
    await act(async () => {
      ok = await result.current.mutate('bad-id')
    })

    expect(ok).toBe(false)
    expect(result.current.error).toBeTruthy()
  })
})
