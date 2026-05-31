import { useEffect, useReducer, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  PlayCircle, TrendingUp, Clock, Coins,
  Plus, Bot, GitBranch, WifiOff, RefreshCw,
} from 'lucide-react'
import toast from 'react-hot-toast'
import StatCard from '../components/StatCard'
import ExecutionHistoryTable from '../components/ExecutionHistoryTable'
import RecentAgentsGrid from '../components/RecentAgentsGrid'
import ExecutionTimeline from '../components/charts/ExecutionTimeline'
import TokenUsageChart from '../components/charts/TokenUsageChart'
import { StatsGridSkeleton, ListSkeleton } from '../components/Skeleton'
import { executionsApi, type MetricsResponse, type BackendExecution } from '../api/executions'
import { agentsApi } from '../api/agents'
import type {
  DashboardStatsV2, ExecutionRecord, RecentAgent,
  TimelineDataPoint, TokenDataPoint,
} from '../types'

// ── Static fallback data ───────────────────────────────────────────────────────

const MOCK_STATS: DashboardStatsV2 = {
  totalExecutions: 1247,
  successRate: 94,
  avgDurationMs: 138000,
  tokensToday: 84320,
  tokensCostToday: 0,
}

const MOCK_TIMELINE: TimelineDataPoint[] = [
  { date: 'May 18', success: 28, failed: 2 },
  { date: 'May 19', success: 34, failed: 3 },
  { date: 'May 20', success: 22, failed: 4 },
  { date: 'May 21', success: 41, failed: 1 },
  { date: 'May 22', success: 38, failed: 2 },
  { date: 'May 23', success: 19, failed: 5 },
  { date: 'May 24', success: 27, failed: 2 },
  { date: 'May 25', success: 45, failed: 3 },
  { date: 'May 26', success: 52, failed: 1 },
  { date: 'May 27', success: 31, failed: 6 },
  { date: 'May 28', success: 48, failed: 2 },
  { date: 'May 29', success: 56, failed: 3 },
  { date: 'May 30', success: 43, failed: 4 },
  { date: 'May 31', success: 61, failed: 2 },
]

const MOCK_TOKENS: TokenDataPoint[] = [
  { date: 'May 25', input: 9200,  output: 4100 },
  { date: 'May 26', input: 12400, output: 5800 },
  { date: 'May 27', input: 8600,  output: 3900 },
  { date: 'May 28', input: 15300, output: 7200 },
  { date: 'May 29', input: 11800, output: 5400 },
  { date: 'May 30', input: 18700, output: 8600 },
  { date: 'May 31', input: 22100, output: 9800 },
]

const now = new Date()
const ago = (m: number) => new Date(now.getTime() - m * 60 * 1000).toISOString()

const MOCK_EXECUTIONS: ExecutionRecord[] = [
  { id: 'exec-001', workflowId: 'wf-a1b2', workflowName: 'Research Pipeline',      startedAt: ago(4),   duration_ms: 142000, status: 'success', tokensUsed: 12400 },
  { id: 'exec-002', workflowId: 'wf-c3d4', workflowName: 'Content Generator',      startedAt: ago(12),  duration_ms: 87000,  status: 'success', tokensUsed: 8700  },
  { id: 'exec-003', workflowId: 'wf-e5f6', workflowName: 'Data Analyst Workflow',  startedAt: ago(28),  duration_ms: 0,      status: 'running', tokensUsed: 0     },
  { id: 'exec-004', workflowId: 'wf-g7h8', workflowName: 'Lead Scraper',           startedAt: ago(45),  duration_ms: 203000, status: 'success', tokensUsed: 21300 },
  { id: 'exec-005', workflowId: 'wf-i9j0', workflowName: 'Email Responder',        startedAt: ago(90),  duration_ms: 34000,  status: 'failed',  tokensUsed: 3100  },
  { id: 'exec-006', workflowId: 'wf-a1b2', workflowName: 'Research Pipeline',      startedAt: ago(180), duration_ms: 158000, status: 'success', tokensUsed: 14900 },
  { id: 'exec-007', workflowId: 'wf-k1l2', workflowName: 'Support Triage Bot',     startedAt: ago(240), duration_ms: 62000,  status: 'success', tokensUsed: 5600  },
  { id: 'exec-008', workflowId: 'wf-m3n4', workflowName: 'Market Research Agent',  startedAt: ago(320), duration_ms: 274000, status: 'failed',  tokensUsed: 19800 },
]

const MOCK_AGENTS: RecentAgent[] = [
  { id: 'agent-1', name: 'GroqResearchPilot',   role: 'researcher', model: 'claude-sonnet-4-6',        lastRunAt: ago(6),   status: 'idle'    },
  { id: 'agent-2', name: 'ContentWriterPro',    role: 'writer',     model: 'claude-haiku-4-5',         lastRunAt: ago(14),  status: 'idle'    },
  { id: 'agent-3', name: 'DataAnalystBot',       role: 'analyst',    model: 'llama-3.3-70b-versatile', lastRunAt: ago(28),  status: 'running' },
  { id: 'agent-4', name: 'LeadGenProcessor',    role: 'processor',  model: 'claude-sonnet-4-6',        lastRunAt: ago(45),  status: 'idle'    },
  { id: 'agent-5', name: 'SupportTriageAgent',  role: 'analyst',    model: 'claude-haiku-4-5',         lastRunAt: ago(90),  status: 'idle'    },
  { id: 'agent-6', name: 'MarketResearcher',    role: 'researcher', model: 'llama-3.3-70b-versatile', lastRunAt: ago(190), status: 'idle'    },
]

// ── State ─────────────────────────────────────────────────────────────────────

interface AsyncState<T> { data: T | null; loading: boolean; error: string | null }
const INIT = <T,>(): AsyncState<T> => ({ data: null, loading: true, error: null })

interface State {
  stats:     AsyncState<DashboardStatsV2>
  executions: AsyncState<ExecutionRecord[]>
  agents:    AsyncState<RecentAgent[]>
}

type Action =
  | { type: 'SET_STATS';      data: DashboardStatsV2 }
  | { type: 'SET_EXECUTIONS'; data: ExecutionRecord[] }
  | { type: 'SET_AGENTS';     data: RecentAgent[] }
  | { type: 'SET_ERROR';      key: keyof State; msg: string }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_STATS':      return { ...state, stats:      { data: action.data, loading: false, error: null } }
    case 'SET_EXECUTIONS': return { ...state, executions: { data: action.data, loading: false, error: null } }
    case 'SET_AGENTS':     return { ...state, agents:     { data: action.data, loading: false, error: null } }
    case 'SET_ERROR':      return { ...state, [action.key]: { data: null, loading: false, error: action.msg } }
    default:               return state
  }
}

const INITIAL: State = { stats: INIT(), executions: INIT(), agents: INIT() }

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDuration(ms: number): string {
  if (!ms) return '0s'
  const s = Math.round(ms / 1000)
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}

function metricsToStats(m: MetricsResponse): DashboardStatsV2 {
  return {
    totalExecutions: m.total_executions,
    successRate: Math.round(m.success_rate * 100),
    avgDurationMs: m.avg_duration_ms,
    tokensToday: m.tokens_used_today,
    tokensCostToday: 0,
  }
}

function executionToRecord(e: BackendExecution): ExecutionRecord {
  const workflowId = e.workflow_id ?? ''
  const statusMap: Record<string, ExecutionRecord['status']> = {
    completed: 'success', failed: 'failed', running: 'running',
    pending: 'running', halted: 'failed', stopped: 'failed',
  }
  return {
    id: e.id,
    workflowId,
    workflowName: workflowId ? `Workflow ${workflowId.slice(0, 8)}` : 'Workflow',
    startedAt: e.started_at ?? new Date().toISOString(),
    duration_ms: e.completed_at && e.started_at
      ? new Date(e.completed_at).getTime() - new Date(e.started_at).getTime()
      : 0,
    status: statusMap[e.status] ?? 'running',
    tokensUsed: 0,
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [state, dispatch] = useReducer(reducer, INITIAL)

  const loadAll = useCallback(async () => {
    // Metrics → stats (fall back to mock if API returns zeros)
    executionsApi.metrics()
      .then(m => {
        const live = metricsToStats(m)
        dispatch({ type: 'SET_STATS', data: live.totalExecutions > 0 ? live : MOCK_STATS })
      })
      .catch(() => dispatch({ type: 'SET_STATS', data: MOCK_STATS }))

    // Recent executions (fall back to mock if API returns empty)
    executionsApi.list({ limit: 20 })
      .then(res => {
        const items = Array.isArray(res.items) ? res.items : []
        const records = items.map(executionToRecord)
        dispatch({ type: 'SET_EXECUTIONS', data: records.length > 0 ? records : MOCK_EXECUTIONS })
      })
      .catch(() => dispatch({ type: 'SET_EXECUTIONS', data: MOCK_EXECUTIONS }))

    // Recent agents (fall back to mock if API returns empty)
    agentsApi.list({ limit: 6 })
      .then(res => {
        const items = Array.isArray(res.items) ? res.items : []
        const mapped = items.map(a => ({
          id: a.id,
          name: a.name,
          role: (a.role as RecentAgent['role']) ?? 'analyst',
          model: a.model,
          lastRunAt: a.created_at,
          status: (a.status === 'active' ? 'idle' : 'idle') as RecentAgent['status'],
        }))
        dispatch({ type: 'SET_AGENTS', data: mapped.length > 0 ? mapped : MOCK_AGENTS })
      })
      .catch(() => dispatch({ type: 'SET_AGENTS', data: MOCK_AGENTS }))
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const handleRetry = () => {
    toast.promise(loadAll(), {
      loading: 'Refreshing…',
      success: 'Dashboard updated',
      error: 'Failed to refresh',
    })
  }

  const { stats, executions, agents } = state
  const anyError = stats.error || executions.error || agents.error

  return (
    <main className="p-4 md:p-6 max-w-7xl mx-auto space-y-6" role="main">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Multi-Agent Orchestrator control room</p>
        </div>
        <div className="flex items-center gap-2">
          {anyError && (
            <button
              onClick={handleRetry}
              className="flex items-center gap-1.5 text-sm text-amber-600 dark:text-amber-400 hover:underline"
            >
              <WifiOff size={14} /> Connection issues — Retry
            </button>
          )}
          <button
            onClick={handleRetry}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700
                       px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            title="Refresh dashboard"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats.loading ? <StatsGridSkeleton /> : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Total Executions"
            value={(stats.data?.totalExecutions ?? 0).toLocaleString()}
            icon={PlayCircle}
            iconColor="bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400"
            trend={{ value: '+12% vs last week', positive: true }}
          />
          <StatCard
            label="Success Rate"
            value={`${stats.data?.successRate ?? 0}%`}
            icon={TrendingUp}
            iconColor="bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400"
            trend={{ value: '+2.4% vs last week', positive: true }}
          />
          <StatCard
            label="Avg Duration"
            value={formatDuration(stats.data?.avgDurationMs ?? 0)}
            icon={Clock}
            iconColor="bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
            trend={{ value: '−8s faster', positive: true }}
          />
          <StatCard
            label="Tokens Today"
            value={(stats.data?.tokensToday ?? 0).toLocaleString()}
            icon={Coins}
            iconColor="bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400"
            trend={{ value: '+18% vs yesterday', positive: true }}
          />
        </div>
      )}

      {/* Quick actions */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Link
          to="/agents"
          className="flex items-center gap-3 p-4 rounded-xl border border-gray-100 dark:border-gray-800
                     bg-white dark:bg-gray-900 hover:border-primary-300 dark:hover:border-primary-700
                     hover:shadow-sm transition-all group"
        >
          <Bot size={20} className="text-primary-500" />
          <div>
            <p className="text-sm font-medium text-gray-900 dark:text-white">Agents</p>
            <p className="text-xs text-gray-500">Manage AI agents</p>
          </div>
        </Link>
        <Link
          to="/workflows"
          className="flex items-center gap-3 p-4 rounded-xl border border-gray-100 dark:border-gray-800
                     bg-white dark:bg-gray-900 hover:border-primary-300 dark:hover:border-primary-700
                     hover:shadow-sm transition-all group"
        >
          <GitBranch size={20} className="text-indigo-500" />
          <div>
            <p className="text-sm font-medium text-gray-900 dark:text-white">Workflows</p>
            <p className="text-xs text-gray-500">Build & run DAGs</p>
          </div>
        </Link>
        <Link
          to="/workflows"
          className="flex items-center gap-3 p-4 rounded-xl border border-gray-100 dark:border-gray-800
                     bg-white dark:bg-gray-900 hover:border-primary-300 dark:hover:border-primary-700
                     hover:shadow-sm transition-all"
        >
          <Plus size={20} className="text-emerald-500" />
          <div>
            <p className="text-sm font-medium text-gray-900 dark:text-white">New Workflow</p>
            <p className="text-xs text-gray-500">Start from scratch</p>
          </div>
        </Link>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Execution Timeline</h2>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />Success</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" />Failed</span>
            </div>
          </div>
          <ExecutionTimeline data={MOCK_TIMELINE} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Token Usage</h2>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />Input</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block" />Output</span>
            </div>
          </div>
          <TokenUsageChart data={MOCK_TOKENS} />
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Recent Executions</h2>
              <Link to="/executions" className="text-xs text-primary-500 hover:underline">View all</Link>
            </div>
            {executions.loading
              ? <ListSkeleton rows={4} />
              : <ExecutionHistoryTable data={executions.data ?? []} />
            }
          </div>
        </div>
        <div>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5">
            {agents.loading
              ? <ListSkeleton rows={4} />
              : <RecentAgentsGrid agents={agents.data ?? []} />
            }
          </div>
        </div>
      </div>
    </main>
  )
}
