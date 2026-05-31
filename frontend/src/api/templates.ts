/**
 * Templates API — typed wrappers for /api/v1/templates endpoints
 */

import { apiClient } from './client'

// ── Shared template types ─────────────────────────────────────────────────────

export type TemplateCategory = 'All' | 'Sales' | 'Content' | 'Support' | 'Analytics'
export type TemplateSortOption = 'popularity' | 'rating' | 'name'

// ── Agent template ────────────────────────────────────────────────────────────

export interface AgentTemplate {
  id: string
  name: string
  description: string
  role: string
  category: TemplateCategory
  tags: string[]
  system_prompt: string
  model: string
  tools: string[]
  example_input: Record<string, unknown>
  example_output: Record<string, unknown>
  popularity: number
  clone_count: number
  rating: number
  rating_count: number
}

export interface AgentTemplateListResponse {
  total: number
  items: AgentTemplate[]
  categories: string[]
}

export interface ClonedAgent {
  id: string
  user_id: string
  name: string
  role: string
  system_prompt: string
  model: string
  status: string
  tools: string[]
  created_at: string
  cloned_from: string
}

// ── Workflow template ─────────────────────────────────────────────────────────

export interface WorkflowTemplateNode {
  id: string
  type: 'agent' | 'condition'
  agent_id: string | null
  agent_template_id?: string
  label: string
  depends_on: string[]
  condition?: string
  true_branch?: string
  false_branch?: string
  timeout_s?: number
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  category: TemplateCategory
  tags: string[]
  dag_config: { nodes: WorkflowTemplateNode[] }
  node_count: number
  popularity: number
  clone_count: number
  rating: number
  rating_count: number
  estimated_duration_s: number
}

export interface WorkflowTemplateListResponse {
  total: number
  items: WorkflowTemplate[]
  categories: string[]
}

export interface ClonedWorkflow {
  id: string
  user_id: string
  name: string
  dag_config: Record<string, unknown>
  is_active: boolean
  created_at: string
  cloned_from: string
}

// ── API functions ─────────────────────────────────────────────────────────────

export const templatesApi = {
  // Agents
  listAgents(params?: {
    category?: string
    sort?: TemplateSortOption
    q?: string
  }): Promise<AgentTemplateListResponse> {
    return apiClient.get('/templates/agents', params)
  },

  getAgent(id: string): Promise<AgentTemplate> {
    return apiClient.get(`/templates/agents/${id}`)
  },

  cloneAgent(id: string): Promise<ClonedAgent> {
    return apiClient.post(`/templates/agents/${id}/clone`)
  },

  // Workflows
  listWorkflows(params?: {
    category?: string
    sort?: TemplateSortOption
    q?: string
  }): Promise<WorkflowTemplateListResponse> {
    return apiClient.get('/templates/workflows', params)
  },

  getWorkflow(id: string): Promise<WorkflowTemplate> {
    return apiClient.get(`/templates/workflows/${id}`)
  },

  cloneWorkflow(id: string): Promise<ClonedWorkflow> {
    return apiClient.post(`/templates/workflows/${id}/clone`)
  },
}
