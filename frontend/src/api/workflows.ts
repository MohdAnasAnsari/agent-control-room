/**
 * Workflow API — typed wrappers matching backend /api/v1/workflows endpoints
 */

import { apiClient } from './client'

// ── Backend response types ────────────────────────────────────────────────────

export interface BackendWorkflow {
  id: string
  user_id: string
  name: string
  dag_config: {
    nodes?: DagNode[]
    [key: string]: unknown
  }
  is_active: boolean
  created_at: string
}

export interface DagNode {
  id: string
  type: 'agent' | 'condition'
  agent_id?: string
  depends_on?: string[]
  condition?: string
  true_branch?: string
  false_branch?: string
  timeout_s?: number
}

export interface DagEdge {
  source: string
  target: string
}

export interface WorkflowListResponse {
  total: number
  items: BackendWorkflow[]
  has_more: boolean
}

export interface CreateWorkflowPayload {
  name: string
  nodes?: DagNode[]
  edges?: DagEdge[]
  dag_config?: Record<string, unknown>
}

export interface UpdateWorkflowPayload {
  name?: string
  nodes?: DagNode[]
  edges?: DagEdge[]
  is_active?: boolean
  dag_config?: Record<string, unknown>
}

export interface ExecuteWorkflowPayload {
  input_data?: Record<string, unknown>
  run_async?: boolean
}

export interface ExecuteWorkflowResponse {
  execution_id: string
  status: string
  result?: Record<string, unknown> | null
}

// ── API functions ─────────────────────────────────────────────────────────────

export const workflowsApi = {
  list(params?: {
    skip?: number
    limit?: number
    is_active?: boolean
  }): Promise<WorkflowListResponse> {
    return apiClient.get('/workflows', params)
  },

  get(id: string): Promise<BackendWorkflow> {
    return apiClient.get(`/workflows/${id}`)
  },

  create(payload: CreateWorkflowPayload): Promise<BackendWorkflow> {
    return apiClient.post('/workflows', payload)
  },

  update(id: string, payload: UpdateWorkflowPayload): Promise<BackendWorkflow> {
    return apiClient.patch(`/workflows/${id}`, payload)
  },

  delete(id: string): Promise<void> {
    return apiClient.delete(`/workflows/${id}`)
  },

  execute(id: string, payload?: ExecuteWorkflowPayload): Promise<ExecuteWorkflowResponse> {
    return apiClient.post(`/workflows/${id}/execute`, payload ?? {})
  },
}
