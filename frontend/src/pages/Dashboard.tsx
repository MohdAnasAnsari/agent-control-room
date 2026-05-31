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
import TopWorkflowsChart from '../components/charts/TopWorkflowsChart'
import { StatsGridSkeleton, ListSkeleton } from '../components/Skeleton'
import { executionsApi, type MetricsResponse, type BackendExecution } from '../api/executions'
import { agentsApi } from '../api/agents'
import type {
  DashboardStatsV2, ExecutionRecord, RecentAgent,
  TimelineDataPoint, TokenDataPoint, WorkflowStat,
} from '../types'

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
  const statusMap: Record<string, ExecutionRecord['status']> = {
    completed: 'success', failed: 'failed', running: 'running',
    pending: 'running', halted: 'failed', stopped: 'failed',
  }
  return {
    id: e.id,
    workflowId: e.workflow_id,
    workflowName: `Workflow ${e.workflow_id.slice(0, 8)}`,
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
    // Metrics → stats
    executionsApi.metrics()
      .then(m => dispatch({ type: 'SET_STATS', data: metricsToStats(m) }))
      .catch(err => {
        console.error(err)
        dispatch({ type: 'SET_ERROR', key: 'stats', msg: 'Failed to load metrics' })
      })

    // Recent executions
    executionsApi.list({ limit: 20 })
      .then(res => dispatch({ type: 'SET_EXECUTIONS', data: res.items.map(executionToRecord) }))
      .catch(() => dispatch({ type: 'SET_ERROR', key: 'executions', msg: 'Failed to load executions' }))

    // Recent agents
    agentsApi.list({ limit: 6 })
      .then(res => dispatch({
        type: 'SET_AGENTS',
        data: res.items.map(a => ({
          id: a.id,
          name: a.name,
          role: (a.role as RecentAgent['role']) ?? 'analyst',
          model: a.model,
          lastRunAt: a.created_at,
          status: (a.status === 'active' ? 'idle' : 'idle') as RecentAgent['status'],
        })),
      }))
      .catch(() => dispatch({ type: 'SET_ERROR', key: 'agents', msg: 'Failed to load agents' }))
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
            title="Total Executions"
            value={stats.data?.totalExecutions ?? 0}
            icon={<PlayCircle size={20} className="text-primary-500" />}
            trend="up"
          />
          <StatCard
            title="Success Rate"
            value={`${stats.data?.successRate ?? 0}%`}
            icon={<TrendingUp size={20} className="text-green-500" />}
            trend="up"
          />
          <StatCard
            title="Avg Duration"
            value={formatDuration(stats.data?.avgDurationMs ?? 0)}
            icon={<Clock size={20} className="text-blue-500" />}
          />
          <StatCard
            title="Tokens Today"
            value={(stats.data?.tokensToday ?? 0).toLocaleString()}
            icon={<Coins size={20} className="text-purple-500" />}
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
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">Execution Timeline</h2>
          <ExecutionTimeline data={[]} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">Token Usage</h2>
          <TokenUsageChart data={[]} />
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
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Recent Agents</h2>
              <Link to="/agents" className="text-xs text-primary-500 hover:underline">View all</Link>
            </div>
            {agents.loading
              ? <ListSkeleton rows={4} />
              : <RecentAgentsGrid data={agents.data ?? []} />
            }
          </div>
        </div>
      </div>
    </main>
  )
}
