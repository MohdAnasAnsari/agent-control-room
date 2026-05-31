import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Search, Trash2, AlertCircle, RefreshCw, ExternalLink } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { TableSkeleton } from '../components/Skeleton'
import { useExecutions, useDeleteExecution } from '../hooks/useExecutions'
import type { BackendExecution } from '../api/executions'

const STATUS_FILTERS = ['all', 'pending', 'running', 'completed', 'failed'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

function statusClass(s: string): string {
  const map: Record<string, string> = {
    completed: 'text-green-600 bg-green-50 dark:bg-green-900/20 dark:text-green-400',
    running:   'text-blue-600 bg-blue-50 dark:bg-blue-900/20 dark:text-blue-400',
    pending:   'text-yellow-600 bg-yellow-50 dark:bg-yellow-900/20 dark:text-yellow-400',
    failed:    'text-red-600 bg-red-50 dark:bg-red-900/20 dark:text-red-400',
    halted:    'text-orange-600 bg-orange-50 dark:bg-orange-900/20 dark:text-orange-400',
  }
  return map[s] ?? 'text-gray-600 bg-gray-50 dark:bg-gray-700 dark:text-gray-400'
}

function formatDuration(started: string | null, completed: string | null): string {
  if (!started) return '—'
  const endMs = completed ? new Date(completed).getTime() : Date.now()
  const ms = endMs - new Date(started).getTime()
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function Executions() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(0)
  const limit = 20

  const { executions, total, loading, error, refetch } = useExecutions({
    skip: page * limit,
    limit,
    status: statusFilter === 'all' ? undefined : statusFilter,
  })

  const { mutate: deleteExecution } = useDeleteExecution()

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return executions.filter(e =>
      !q || e.id.toLowerCase().includes(q) || e.workflow_id.toLowerCase().includes(q)
    )
  }, [executions, search])

  const handleDelete = async (e: BackendExecution) => {
    if (!confirm(`Delete execution ${e.id.slice(0, 8)}…?`)) return
    const ok = await deleteExecution(e.id)
    if (ok) {
      toast.success('Execution deleted')
      refetch()
    } else {
      toast.error('Failed to delete execution')
    }
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <main className="p-4 md:p-6 max-w-7xl mx-auto space-y-6" role="main">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Executions</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {loading ? 'Loading…' : `${total} total executions`}
          </p>
        </div>
        <button
          onClick={refetch}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700
                     px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            type="search"
            placeholder="Search by ID or workflow…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                       bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-sm">
          {STATUS_FILTERS.map(f => (
            <button
              key={f}
              onClick={() => { setStatusFilter(f); setPage(0) }}
              className={clsx(
                'px-3 py-2 capitalize transition-colors',
                statusFilter === f
                  ? 'bg-primary-500 text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800">
          <AlertCircle size={18} className="text-red-500" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          <button onClick={refetch} className="ml-auto text-sm text-red-600 hover:underline">Retry</button>
        </div>
      )}

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800 text-left">
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400">ID</th>
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400">Workflow</th>
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400">Status</th>
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400">Started</th>
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400">Duration</th>
              <th className="px-4 py-3 font-medium text-gray-500 dark:text-gray-400 text-right">Actions</th>
            </tr>
          </thead>
          {loading ? <TableSkeleton rows={8} cols={6} /> : (
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-gray-500 dark:text-gray-400">
                    No executions found
                  </td>
                </tr>
              ) : filtered.map(exec => (
                <tr key={exec.id} className="border-b border-gray-50 dark:border-gray-800/50 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-gray-600 dark:text-gray-400">{exec.id.slice(0, 8)}…</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400">{exec.workflow_id.slice(0, 8)}…</td>
                  <td className="px-4 py-3">
                    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-medium', statusClass(exec.status))}>
                      {exec.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatTime(exec.started_at)}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatDuration(exec.started_at, exec.completed_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <Link
                        to={`/executions/${exec.id}`}
                        className="p-1.5 rounded-lg text-gray-500 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors"
                      >
                        <ExternalLink size={14} />
                      </Link>
                      <button
                        onClick={() => handleDelete(exec)}
                        className="p-1.5 rounded-lg text-gray-500 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          )}
        </table>
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 dark:border-gray-800">
            <p className="text-xs text-gray-500">Page {page + 1} of {totalPages}</p>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                Previous
              </button>
              <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
