/**
 * Agent API — typed wrappers matching backend /api/v1/agents endpoints
 */

import { apiClient } from './client'

// ── Backend response types (matches FastAPI schemas) ──────────────────────────

export interface BackendAgent {
  id: string
  user_id: string
  name: string
  role: string
  system_prompt: string
  model: string
  status: 'active' | 'paused' | 'archived'
  tools: string[]
  created_at: string
  stats?: {
    total_executions: number
    successful_executions: number
    failed_executions: number
  }
}

export interface AgentListResponse {
  total: number
  items: BackendAgent[]
  has_more: boolean
}

export interface CreateAgentPayload {
  name: string          // 3–50 chars
  role: string
  system_prompt: string // 20–2000 chars
  model: string
  tools: string[]
}

export interface UpdateAgentPayload {
  name?: string
  role?: string
  system_prompt?: string
  model?: string
  status?: 'active' | 'paused' | 'archived'
  tools?: string[]
}

// ── API functions ─────────────────────────────────────────────────────────────

export const agentsApi = {
  list(params?: {
    skip?: number
    limit?: number
    role?: string
    status?: string
  }): Promise<AgentListResponse> {
    return apiClient.get('/agents', params)
  },

  get(id: string): Promise<BackendAgent> {
    return apiClient.get(`/agents/${id}`)
  },

  create(payload: CreateAgentPayload): Promise<BackendAgent> {
    return apiClient.post('/agents', payload)
  },

  update(id: string, payload: UpdateAgentPayload): Promise<BackendAgent> {
    return apiClient.patch(`/agents/${id}`, payload)
  },

  delete(id: string): Promise<void> {
    return apiClient.delete(`/agents/${id}`)
  },
}
