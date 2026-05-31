// Agent types
export type AgentStatus = 'active' | 'idle' | 'error' | 'disabled'
export type AgentType = 'llm' | 'tool' | 'supervisor' | 'custom'

export interface Agent {
  id: string
  name: string
  description: string
  type: AgentType
  status: AgentStatus
  model?: string
  tools: string[]
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
}

// Workflow types
export type WorkflowStatus = 'active' | 'draft' | 'archived'
export type NodeType = 'agent' | 'condition' | 'input' | 'output' | 'transform'

export interface WorkflowNode {
  id: string
  type: NodeType
  agent_id?: string
  config: Record<string, unknown>
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  condition?: string
}

export interface Workflow {
  id: string
  name: string
  description: string
  status: WorkflowStatus
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  created_at: string
  updated_at: string
}

// Execution types
export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ExecutionStep {
  id: string
  agent_id: string
  agent_name: string
  input: Record<string, unknown>
  output?: Record<string, unknown>
  status: ExecutionStatus
  started_at: string
  completed_at?: string
  error?: string
  tokens_used?: number
  duration_ms?: number
}

export interface Execution {
  id: string
  workflow_id?: string
  workflow_name?: string
  status: ExecutionStatus
  input: Record<string, unknown>
  output?: Record<string, unknown>
  steps: ExecutionStep[]
  started_at: string
  completed_at?: string
  error?: string
  total_tokens?: number
  duration_ms?: number
}

// Dashboard stats types
export interface DashboardStats {
  total_agents: number
  active_agents: number
  total_workflows: number
  active_workflows: number
  total_executions: number
  running_executions: number
  success_rate: number
  avg_duration_ms: number
}

export interface RecentActivity {
  id: string
  type: 'execution_started' | 'execution_completed' | 'execution_failed' | 'agent_created' | 'workflow_created'
  message: string
  timestamp: string
  metadata?: Record<string, unknown>
}

// User/auth types
export interface User {
  id: string
  name: string
  email: string
  avatar?: string
  role: 'admin' | 'operator' | 'viewer'
}

// API types
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface APIError {
  message: string
  code?: string
  details?: Record<string, unknown>
}

// Notification types
export type NotificationType = 'info' | 'success' | 'warning' | 'error'

export interface Notification {
  id: string
  type: NotificationType
  title: string
  message: string
  read: boolean
  timestamp: string
}

// Theme
export type Theme = 'light' | 'dark'

// ─── Canvas / Workflow Builder types ─────────────────────────────────────────

export type AgentRole = 'analyst' | 'researcher' | 'writer' | 'processor'

export type CanvasNodeType = 'agent' | 'condition' | 'start' | 'end'

export interface CanvasNode {
  id: string
  type: CanvasNodeType
  label: string
  role?: AgentRole
  x: number
  y: number
  condition?: string
  agentId?: string
}

export interface CanvasEdge {
  id: string
  source: string
  target: string
  branch?: 'true' | 'false'
  label?: string
}

export interface ValidationError {
  type: 'cycle' | 'orphan' | 'missing_output'
  message: string
  nodeIds?: string[]
}

// ─── Agent Builder form types ─────────────────────────────────────────────────

export type ModelOption =
  | 'claude-sonnet-4-6'
  | 'claude-opus-4-8'
  | 'claude-haiku-4-5'
  | 'gpt-4o'
  | 'gpt-4o-mini'
  | 'llama-3.3-70b-versatile'

export type ToolOption =
  | 'web_search'
  | 'file_read'
  | 'email_send'
  | 'calendar'
  | 'sql'
  | 'code_executor'
  | 'slack'
  | 'github'
  | 'document_reader'
  | 'image_gen'

export interface AgentFormData {
  name: string
  role: AgentRole
  systemPrompt: string
  model: ModelOption
  tools: ToolOption[]
  memorySize: number
}

// ─── Execution Monitor types ──────────────────────────────────────────────────

export type NodeRunStatus = 'idle' | 'running' | 'completed' | 'error' | 'skipped'

export interface ExecutionNodeStatus {
  nodeId: string
  status: NodeRunStatus
  startedAt?: string
  completedAt?: string
  durationMs?: number
  tokensUsed?: number
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  error?: string
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  timestamp: string       // ISO
  level: LogLevel
  nodeId: string
  nodeName: string
  message: string
  data?: Record<string, unknown>
}

export interface LiveMetrics {
  nodesTotal: number
  nodesCompleted: number
  nodesFailed: number
  totalDurationMs: number
  tokensUsed: number
  estimatedCostUsd: number
  currentNodeLabel: string | null
  successRate: number
}

export type MonitorStatus = 'idle' | 'running' | 'paused' | 'completed' | 'failed' | 'stopped'

// WebSocket message envelope sent by the backend
export interface WSMessage {
  type: 'node_status' | 'log' | 'metrics_update' | 'execution_complete' | 'execution_error' | 'ping'
  executionId: string
  nodeStatus?: ExecutionNodeStatus
  log?: LogEntry
  metrics?: Partial<LiveMetrics>
  error?: string
}

// ─── Dashboard v2 types ───────────────────────────────────────────────────────

export type ExecutionRecordStatus = 'success' | 'failed' | 'running'

export interface ExecutionRecord {
  id: string
  workflowId: string
  workflowName: string
  startedAt: string        // ISO
  duration_ms: number
  status: ExecutionRecordStatus
  tokensUsed: number
}

export interface DashboardStatsV2 {
  totalExecutions: number
  successRate: number
  avgDurationMs: number
  tokensToday: number
  tokensCostToday: number
}

export interface TimelineDataPoint {
  date: string             // "Jan 01"
  success: number
  failed: number
}

export interface TokenDataPoint {
  date: string             // "Mon"
  input: number
  output: number
}

export interface WorkflowStat {
  name: string
  count: number
  successRate: number
}

export interface RecentAgent {
  id: string
  name: string
  role: AgentRole
  model?: string
  lastRunAt: string        // ISO
  status: 'idle' | 'running'
}
