/**
 * Execution API — typed wrappers matching backend /api/v1/executions endpoints
 */

import { apiClient } from './client'

// ── Backend response types ────────────────────────────────────────────────────

export interface BackendExecutionStep {
  id: string
  execution_id: string
  agent_id: string | null
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  duration_ms: number | null
  timestamp: string
}

export interface BackendExecution {
  id: string
  workflow_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'halted' | 'stopped'
  started_at: string | null
  completed_at: string | null
  result: Record<string, unknown> | null
  error_log: string | null
  steps?: BackendExecutionStep[]
}

export interface ExecutionListResponse {
  total: number
  items: BackendExecution[]
  has_more: boolean
}

export interface MetricsResponse {
  total_executions: number
  success_rate: number
  avg_duration_ms: number
  tokens_used_today: number
}

// ── API functions ─────────────────────────────────────────────────────────────

export const executionsApi = {
  list(params?: {
    skip?: number
    limit?: number
    status?: string
    workflow_id?: string
  }): Promise<ExecutionListResponse> {
    return apiClient.get('/executions', params)
  },

  get(id: string): Promise<BackendExecution> {
    return apiClient.get(`/executions/${id}`)
  },

  delete(id: string): Promise<void> {
    return apiClient.delete(`/executions/${id}`)
  },

  metrics(): Promise<MetricsResponse> {
    return apiClient.get('/metrics')
  },

  /** Returns the URL to the NDJSON log stream for an execution. */
  logsUrl(id: string): string {
    return `/api/v1/executions/${id}/logs`
  },

  /** Returns the WebSocket URL for live execution monitoring. */
  wsUrl(id: string): string {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = import.meta.env.VITE_API_URL
      ? new URL(import.meta.env.VITE_API_URL as string).host
      : window.location.host
    return `${protocol}://${host}/ws/executions/${id}`
  },
}
