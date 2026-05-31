import { useState, useMemo, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  Search, Eye, RotateCcw, Trash2, ChevronUp, ChevronDown,
  ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight,
  CheckSquare, Square, AlertCircle, Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import type { ExecutionRecord, ExecutionRecordStatus } from '../types'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)   return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function formatDuration(ms: number): string {
  if (ms === 0) return '—'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function fmtTokens(n: number): string {
  if (n === 0) return '—'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<ExecutionRecordStatus, { label: string; cls: string; dot: string }> = {
  success: {
    label: 'Success',
    cls:  'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    dot:  'bg-green-500',
  },
  failed: {
    label: 'Failed',
    cls:  'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    dot:  'bg-red-500',
  },
  running: {
    label: 'Running',
    cls:  'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    dot:  'bg-blue-500',
  },
}

function StatusBadge({ status }: { status: ExecutionRecordStatus }) {
  const cfg = STATUS_CONFIG[status]
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium',
      cfg.cls,
    )}>
      {status === 'running'
        ? <Loader2 size={10} className="animate-spin" aria-hidden="true" />
        : <span className={clsx('w-1.5 h-1.5 rounded-full', cfg.dot)} aria-hidden="true" />
      }
      {cfg.label}
    </span>
  )
}

// ─── Sort control ─────────────────────────────────────────────────────────────

type SortKey = 'startedAt' | 'duration_ms' | 'status' | 'tokensUsed'
type SortDir = 'asc' | 'desc'

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (col !== sortKey) {
    return <ChevronUp size={12} className="text-gray-300 dark:text-gray-600" />
  }
  return sortDir === 'asc'
    ? <ChevronUp   size={12} className="text-primary-500" />
    : <ChevronDown size={12} className="text-primary-500" />
}

// ─── Skeleton row ─────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr aria-hidden="true">
      {[48, 160, 80, 80, 72, 56, 100].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className={`h-4 rounded skeleton`} style={{ width: w }} />
        </td>
      ))}
    </tr>
  )
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  data: ExecutionRecord[]
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

const PAGE_SIZE = 10

const STATUS_FILTERS: { value: ExecutionRecordStatus | 'all'; label: string }[] = [
  { value: 'all',     label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'failed',  label: 'Failed' },
  { value: 'running', label: 'Running' },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function ExecutionHistoryTable({ data, loading = false, error = null, onRetry }: Props) {
  const [search,       setSearch]       = useState('')
  const [statusFilter, setStatusFilter] = useState<ExecutionRecordStatus | 'all'>('all')
  const [sortKey,      setSortKey]      = useState<SortKey>('startedAt')
  const [sortDir,      setSortDir]      = useState<SortDir>('desc')
  const [page,         setPage]         = useState(1)
  const [selected,     setSelected]     = useState<Set<string>>(new Set())
  const [rows,         setRows]         = useState<ExecutionRecord[]>(data)

  // Sync when data prop changes
  useEffect(() => { setRows(data) }, [data])

  // Filtered + sorted
  const processed = useMemo(() => {
    const q = search.toLowerCase()
    let arr = rows.filter(r => {
      if (statusFilter !== 'all' && r.status !== statusFilter) return false
      if (q && !r.workflowName.toLowerCase().includes(q)) return false
      return true
    })

    arr = [...arr].sort((a, b) => {
      let cmp = 0
      if (sortKey === 'startedAt')   cmp = a.startedAt.localeCompare(b.startedAt)
      if (sortKey === 'duration_ms') cmp = a.duration_ms - b.duration_ms
      if (sortKey === 'status')      cmp = a.status.localeCompare(b.status)
      if (sortKey === 'tokensUsed')  cmp = a.tokensUsed - b.tokensUsed
      return sortDir === 'asc' ? cmp : -cmp
    })

    return arr
  }, [rows, search, statusFilter, sortKey, sortDir])

  const totalPages   = Math.max(1, Math.ceil(processed.length / PAGE_SIZE))
  const currentPage  = Math.min(page, totalPages)
  const pageRows     = processed.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  const toggleSort = useCallback((key: SortKey) => {
    setSortKey(prev => {
      if (prev === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
      else { setSortDir('desc') }
      return key
    })
    setPage(1)
  }, [])

  const allPageSelected = pageRows.length > 0 && pageRows.every(r => selected.has(r.id))
  const someSelected    = selected.size > 0

  const toggleSelectAll = () => {
    setSelected(prev => {
      const next = new Set(prev)
      if (allPageSelected) pageRows.forEach(r => next.delete(r.id))
      else                 pageRows.forEach(r => next.add(r.id))
      return next
    })
  }

  const toggleRow = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDelete = useCallback((id: string) => {
    setRows(prev => prev.filter(r => r.id !== id))
    setSelected(prev => { const n = new Set(prev); n.delete(id); return n })
  }, [])

  const handleBulkDelete = useCallback(() => {
    const ids = new Set(selected)
    setRows(prev => prev.filter(r => !ids.has(r.id)))
    setSelected(new Set())
    setPage(1)
  }, [selected])

  const handleFilterChange = (v: ExecutionRecordStatus | 'all') => {
    setStatusFilter(v)
    setPage(1)
    setSelected(new Set())
  }

  const handleSearch = (v: string) => {
    setSearch(v)
    setPage(1)
    setSelected(new Set())
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <section
      className="rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 overflow-hidden"
      aria-labelledby="history-title"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="history-title" className="text-base font-semibold text-gray-900 dark:text-white">
              Execution History
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {loading ? 'Loading…' : `${processed.length} executions`}
            </p>
          </div>

          {someSelected && (
            <button
              onClick={handleBulkDelete}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-sm font-medium hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors"
            >
              <Trash2 size={14} />
              Delete {selected.size} selected
            </button>
          )}
        </div>

        {/* Filters row */}
        <div className="flex flex-wrap items-center gap-3 mt-3">
          {/* Search */}
          <div className="relative flex items-center flex-1 min-w-48">
            <Search size={14} className="absolute left-3 text-gray-400 pointer-events-none" aria-hidden="true" />
            <input
              type="search"
              placeholder="Search by workflow name…"
              value={search}
              onChange={e => handleSearch(e.target.value)}
              className="w-full pl-8 pr-4 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              aria-label="Search executions"
            />
          </div>

          {/* Status filter pills */}
          <div
            className="flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-1"
            role="group"
            aria-label="Filter by status"
          >
            {STATUS_FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => handleFilterChange(f.value)}
                className={clsx(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                  statusFilter === f.value
                    ? 'bg-primary-500 text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700',
                )}
                aria-pressed={statusFilter === f.value}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="grid" aria-label="Execution history">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
              {/* Checkbox */}
              <th className="w-10 px-4 py-3 text-left">
                <button
                  onClick={toggleSelectAll}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                  aria-label={allPageSelected ? 'Deselect all' : 'Select all'}
                >
                  {allPageSelected
                    ? <CheckSquare size={16} className="text-primary-500" />
                    : <Square size={16} />
                  }
                </button>
              </th>

              {/* Workflow */}
              <th className="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
                Workflow
              </th>

              {/* Started — sortable */}
              <th className="px-4 py-3 text-left">
                <button
                  onClick={() => toggleSort('startedAt')}
                  className="flex items-center gap-1 font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                  Started <SortIcon col="startedAt" sortKey={sortKey} sortDir={sortDir} />
                </button>
              </th>

              {/* Duration — sortable */}
              <th className="px-4 py-3 text-left">
                <button
                  onClick={() => toggleSort('duration_ms')}
                  className="flex items-center gap-1 font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                  Duration <SortIcon col="duration_ms" sortKey={sortKey} sortDir={sortDir} />
                </button>
              </th>

              {/* Status — sortable */}
              <th className="px-4 py-3 text-left">
                <button
                  onClick={() => toggleSort('status')}
                  className="flex items-center gap-1 font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                  Status <SortIcon col="status" sortKey={sortKey} sortDir={sortDir} />
                </button>
              </th>

              {/* Tokens — sortable */}
              <th className="px-4 py-3 text-left">
                <button
                  onClick={() => toggleSort('tokensUsed')}
                  className="flex items-center gap-1 font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                >
                  Tokens <SortIcon col="tokensUsed" sortKey={sortKey} sortDir={sortDir} />
                </button>
              </th>

              {/* Actions */}
              <th className="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400 sr-only">
                Actions
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {/* Loading state */}
            {loading && Array.from({ length: PAGE_SIZE }).map((_, i) => <SkeletonRow key={i} />)}

            {/* Error state */}
            {!loading && error && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <div className="flex flex-col items-center gap-3">
                    <AlertCircle size={32} className="text-red-400" />
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {error}
                    </p>
                    {onRetry && (
                      <button
                        onClick={onRetry}
                        className="text-sm text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )}

            {/* Empty state */}
            {!loading && !error && processed.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <p className="text-gray-500 dark:text-gray-400 text-sm font-medium">
                      {rows.length === 0 ? 'No executions yet' : 'No results match your filters'}
                    </p>
                    <p className="text-gray-400 dark:text-gray-500 text-xs">
                      {rows.length === 0
                        ? 'Run a workflow to see execution history here.'
                        : 'Try adjusting your search or filter.'}
                    </p>
                    {(search || statusFilter !== 'all') && (
                      <button
                        onClick={() => { setSearch(''); setStatusFilter('all') }}
                        className="mt-2 text-sm text-primary-600 dark:text-primary-400 hover:underline"
                      >
                        Clear filters
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )}

            {/* Data rows */}
            {!loading && !error && pageRows.map(row => (
              <tr
                key={row.id}
                className={clsx(
                  'group hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors',
                  selected.has(row.id) && 'bg-primary-50/50 dark:bg-primary-900/10',
                )}
              >
                {/* Checkbox */}
                <td className="px-4 py-3">
                  <button
                    onClick={() => toggleRow(row.id)}
                    className="text-gray-400 hover:text-primary-500 transition-colors"
                    aria-label={`Select execution ${row.id}`}
                  >
                    {selected.has(row.id)
                      ? <CheckSquare size={15} className="text-primary-500" />
                      : <Square size={15} />
                    }
                  </button>
                </td>

                {/* Workflow name */}
                <td className="px-4 py-3">
                  <Link
                    to={`/executions/${row.id}`}
                    className="font-medium text-gray-900 dark:text-white hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  >
                    {row.workflowName}
                  </Link>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{row.id}</p>
                </td>

                {/* Started */}
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                  {timeAgo(row.startedAt)}
                </td>

                {/* Duration */}
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300 font-mono text-xs">
                  {row.status === 'running'
                    ? <span className="flex items-center gap-1 text-blue-600 dark:text-blue-400">
                        <Loader2 size={11} className="animate-spin" /> Running
                      </span>
                    : formatDuration(row.duration_ms)
                  }
                </td>

                {/* Status */}
                <td className="px-4 py-3">
                  <StatusBadge status={row.status} />
                </td>

                {/* Tokens */}
                <td className="px-4 py-3 text-gray-600 dark:text-gray-300 text-xs">
                  {fmtTokens(row.tokensUsed)}
                </td>

                {/* Actions */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Link
                      to={`/executions/${row.id}`}
                      className="flex items-center justify-center w-7 h-7 rounded text-gray-500 hover:text-primary-600 dark:hover:text-primary-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="View execution"
                    >
                      <Eye size={14} />
                    </Link>
                    <button
                      onClick={() => {/* stub: rerun */}}
                      className="flex items-center justify-center w-7 h-7 rounded text-gray-500 hover:text-green-600 dark:hover:text-green-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="Rerun execution"
                    >
                      <RotateCcw size={14} />
                    </button>
                    <button
                      onClick={() => handleDelete(row.id)}
                      className="flex items-center justify-center w-7 h-7 rounded text-gray-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="Delete execution"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {!loading && !error && processed.length > 0 && (
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, processed.length)} of {processed.length}
          </p>

          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(1)}
              disabled={currentPage === 1}
              className="flex items-center justify-center w-7 h-7 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="First page"
            ><ChevronsLeft size={14} /></button>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="flex items-center justify-center w-7 h-7 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Previous page"
            ><ChevronLeft size={14} /></button>

            {/* Page numbers */}
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              const pageNum = totalPages <= 5
                ? i + 1
                : currentPage <= 3
                  ? i + 1
                  : currentPage >= totalPages - 2
                    ? totalPages - 4 + i
                    : currentPage - 2 + i
              return (
                <button
                  key={pageNum}
                  onClick={() => setPage(pageNum)}
                  className={clsx(
                    'flex items-center justify-center w-7 h-7 rounded text-xs font-medium transition-colors',
                    pageNum === currentPage
                      ? 'bg-primary-500 text-white'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700',
                  )}
                  aria-label={`Page ${pageNum}`}
                  aria-current={pageNum === currentPage ? 'page' : undefined}
                >
                  {pageNum}
                </button>
              )
            })}

            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="flex items-center justify-center w-7 h-7 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Next page"
            ><ChevronRight size={14} /></button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={currentPage === totalPages}
              className="flex items-center justify-center w-7 h-7 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Last page"
            ><ChevronsRight size={14} /></button>
          </div>
        </div>
      )}
    </section>
  )
}
