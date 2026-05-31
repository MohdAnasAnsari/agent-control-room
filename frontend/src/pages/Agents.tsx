import { useState, useMemo, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Plus, Search, RefreshCw, ArrowLeft, Trash2, Edit2, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import AgentCard from '../components/AgentCard'
import AgentBuilder from '../components/AgentBuilder'
import { AgentGridSkeleton } from '../components/Skeleton'
import { useAgents, useCreateAgent, useDeleteAgent, useUpdateAgent } from '../hooks/useAgents'
import type { AgentFormData } from '../types'
import type { BackendAgent } from '../api/agents'

// Status filter options matching backend values
const STATUS_FILTERS = [
  { value: 'all',     label: 'All' },
  { value: 'active',  label: 'Active' },
  { value: 'paused',  label: 'Paused' },
  { value: 'archived', label: 'Archived' },
] as const

// Map backend status to display
function statusBadge(status: string) {
  const map: Record<string, string> = {
    active:   'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    paused:   'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    archived: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  }
  return map[status] ?? map.active
}

function toFrontendAgent(a: BackendAgent) {
  return {
    id: a.id,
    name: a.name,
    description: `${a.role} — ${a.model}`,
    type: 'llm' as const,
    status: a.status === 'paused' ? 'idle' as const : a.status === 'archived' ? 'disabled' as const : 'active' as const,
    model: a.model,
    tools: a.tools,
    created_at: a.created_at,
    updated_at: a.created_at,
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Agents() {
  const { id } = useParams<{ id?: string }>()
  if (id) return <AgentDetail agentId={id} />
  return <AgentList />
}

function AgentList() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [builderOpen, setBuilderOpen] = useState(false)

  const { agents, loading, error, refetch } = useAgents({
    limit: 50,
    status: statusFilter === 'all' ? undefined : statusFilter,
  })

  const { mutate: createAgent, loading: creating } = useCreateAgent()
  const { mutate: deleteAgent } = useDeleteAgent()
  const { mutate: updateAgent } = useUpdateAgent()

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return agents.filter(a =>
      !q || a.name.toLowerCase().includes(q) || a.role.toLowerCase().includes(q)
    )
  }, [agents, search])

  const handleCreate = useCallback(async (data: AgentFormData) => {
    const result = await createAgent({
      name: data.name,
      role: data.role,
      system_prompt: data.systemPrompt,
      model: data.model,
      tools: data.tools,
    })
    if (result) {
      toast.success(`Agent "${result.name}" created`)
      setBuilderOpen(false)
      refetch()
    }
  }, [createAgent, refetch])

  const handleDelete = useCallback(async (id: string, name: string) => {
    if (!confirm(`Delete agent "${name}"?`)) return
    const ok = await deleteAgent(id)
    if (ok) {
      toast.success(`Agent "${name}" archived`)
      refetch()
    } else {
      toast.error('Failed to delete agent')
    }
  }, [deleteAgent, refetch])

  const handleToggleStatus = useCallback(async (id: string, currentStatus: string) => {
    const newStatus = currentStatus === 'active' ? 'paused' : 'active'
    const result = await updateAgent(id, { status: newStatus as 'active' | 'paused' })
    if (result) {
      toast.success(`Agent ${newStatus === 'active' ? 'activated' : 'paused'}`)
      refetch()
    }
  }, [updateAgent, refetch])

  return (
    <main className="p-4 md:p-6 max-w-7xl mx-auto space-y-6" role="main">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Agents</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {loading ? 'Loading…' : `${agents.length} agents total`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={refetch}
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50
                       dark:hover:bg-gray-800 text-gray-500 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
          <button
            onClick={() => setBuilderOpen(true)}
            disabled={creating}
            className="flex items-center gap-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white
                       px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 min-h-[44px]"
          >
            <Plus size={16} />
            New Agent
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            type="search"
            placeholder="Search agents…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                       bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={clsx(
                'px-3 py-2 text-sm transition-colors',
                statusFilter === f.value
                  ? 'bg-primary-500 text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800">
          <AlertCircle size={18} className="text-red-500 shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          <button onClick={refetch} className="ml-auto text-sm text-red-600 hover:underline">Retry</button>
        </div>
      )}

      {/* Agent grid */}
      {loading
        ? <AgentGridSkeleton count={6} />
        : filtered.length === 0
          ? (
            <div className="text-center py-16 space-y-3">
              <p className="text-gray-500 dark:text-gray-400">No agents found</p>
              <button onClick={() => setBuilderOpen(true)} className="text-primary-500 text-sm hover:underline">
                Create your first agent
              </button>
            </div>
          )
          : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filtered.map(agent => (
                <div key={agent.id} className="relative group">
                  <AgentCard agent={toFrontendAgent(agent)} />
                  {/* Hover actions */}
                  <div className="absolute top-3 right-3 hidden group-hover:flex items-center gap-1">
                    <button
                      onClick={() => handleToggleStatus(agent.id, agent.status)}
                      className="p-1.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700
                                 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                      title={agent.status === 'active' ? 'Pause' : 'Activate'}
                    >
                      <Edit2 size={12} />
                    </button>
                    <button
                      onClick={() => handleDelete(agent.id, agent.name)}
                      className="p-1.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700
                                 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                      title="Delete"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
      }

      <AgentBuilder
        open={builderOpen}
        onSave={handleCreate}
        onClose={() => setBuilderOpen(false)}
      />
    </main>
  )
}

function AgentDetail({ agentId }: { agentId: string }) {
  const { agent, loading, error } = useAgents({ limit: 1 })
  // Fallback to list and find by id
  const { agents } = useAgents({ limit: 50 })
  const found = agents.find(a => a.id === agentId)

  if (loading) return <div className="p-8 text-center text-gray-500">Loading agent…</div>
  if (error || !found) return (
    <div className="p-8 text-center">
      <p className="text-red-500 mb-4">{error ?? 'Agent not found'}</p>
      <Link to="/agents" className="text-primary-500 hover:underline">← Back to agents</Link>
    </div>
  )

  return (
    <main className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <Link to="/agents" className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
        <ArrowLeft size={16} /> Back
      </Link>
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">{found.name}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{found.role} — {found.model}</p>
          </div>
          <span className={clsx('px-2.5 py-1 text-xs font-medium rounded-full', statusBadge(found.status))}>
            {found.status}
          </span>
        </div>
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">System Prompt</p>
          <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-sans bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
            {found.system_prompt}
          </pre>
        </div>
        {found.tools.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Tools</p>
            <div className="flex flex-wrap gap-2">
              {found.tools.map(t => (
                <span key={t} className="px-2.5 py-1 text-xs rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
        {found.stats && (
          <div className="grid grid-cols-3 gap-4 pt-2 border-t border-gray-100 dark:border-gray-800">
            <div className="text-center">
              <p className="text-xl font-bold text-gray-900 dark:text-white">{found.stats.total_executions}</p>
              <p className="text-xs text-gray-500">Total runs</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-green-500">{found.stats.successful_executions}</p>
              <p className="text-xs text-gray-500">Successful</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-red-500">{found.stats.failed_executions}</p>
              <p className="text-xs text-gray-500">Failed</p>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
