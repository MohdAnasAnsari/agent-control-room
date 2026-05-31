import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { Download, ChevronRight, ChevronDown, Filter, X } from 'lucide-react'
import clsx from 'clsx'
import type { LogEntry, LogLevel } from '../types'

// ─── Config ───────────────────────────────────────────────────────────────────

const LEVEL_STYLE: Record<LogLevel, { row: string; badge: string; label: string }> = {
  debug: { row: 'text-gray-400 dark:text-gray-500',  badge: 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400', label: 'DBG' },
  info:  { row: 'text-blue-700 dark:text-blue-300',  badge: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300', label: 'INF' },
  warn:  { row: 'text-amber-700 dark:text-amber-300', badge: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300', label: 'WRN' },
  error: { row: 'text-red-700 dark:text-red-300',    badge: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300', label: 'ERR' },
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toTimeString().slice(0, 8)
}

// ─── Single log row ───────────────────────────────────────────────────────────

interface LogRowProps {
  entry: LogEntry
  highlighted: boolean
  onClick: (entry: LogEntry) => void
}

const LogRow = memo(({ entry, highlighted, onClick }: LogRowProps) => {
  const [expanded, setExpanded] = useState(false)
  const st = LEVEL_STYLE[entry.level]
  const hasData = !!entry.data && Object.keys(entry.data).length > 0

  return (
    <div
      ref={highlighted ? el => el?.scrollIntoView({ block: 'nearest' }) : undefined}
      className={clsx(
        'group text-xs font-mono transition-colors',
        highlighted && 'bg-cyan-50 dark:bg-cyan-900/20',
      )}
    >
      <div
        className={clsx(
          'flex items-start gap-1.5 px-3 py-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/60',
          highlighted && 'hover:bg-cyan-100 dark:hover:bg-cyan-900/30',
        )}
        onClick={() => { onClick(entry); if (hasData) setExpanded(v => !v) }}
        role="button"
        aria-expanded={hasData ? expanded : undefined}
        aria-label={`Log: ${entry.message}`}
      >
        {/* Expand icon */}
        <span className="shrink-0 mt-0.5 w-3 text-gray-400">
          {hasData
            ? expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />
            : <span className="block w-2" />
          }
        </span>

        {/* Timestamp */}
        <span className="shrink-0 text-gray-400 dark:text-gray-500 tabular-nums w-16">
          {formatTime(entry.timestamp)}
        </span>

        {/* Level badge */}
        <span className={clsx('shrink-0 rounded px-1 py-0 text-[9px] font-bold uppercase tracking-wide', st.badge)}>
          {st.label}
        </span>

        {/* Agent name */}
        <span className="shrink-0 font-semibold text-gray-600 dark:text-gray-300 max-w-[80px] truncate" title={entry.nodeName}>
          {entry.nodeName}:
        </span>

        {/* Message */}
        <span className={clsx('flex-1 min-w-0 break-words', st.row)}>
          {entry.message}
        </span>
      </div>

      {/* Expanded JSON */}
      {expanded && hasData && (
        <pre className="px-8 pb-2 pt-0 text-[10px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/80 border-t border-gray-100 dark:border-gray-700 overflow-x-auto">
          {JSON.stringify(entry.data, null, 2)}
        </pre>
      )}
    </div>
  )
})
LogRow.displayName = 'LogRow'

// ─── LogsPanel ────────────────────────────────────────────────────────────────

interface LogsPanelProps {
  logs: LogEntry[]
  highlightedNodeId: string | null
  onLogClick: (nodeId: string) => void
  className?: string
}

const LEVELS: (LogLevel | 'all')[] = ['all', 'info', 'warn', 'error', 'debug']

export default function LogsPanel({ logs, highlightedNodeId, onLogClick, className }: LogsPanelProps) {
  const [levelFilter, setLevelFilter] = useState<LogLevel | 'all'>('all')
  const [nodeFilter, setNodeFilter] = useState<string | 'all'>('all')
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs.length, autoScroll])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    setAutoScroll(atBottom)
  }, [])

  const filtered = logs.filter(e => {
    if (levelFilter !== 'all' && e.level !== levelFilter) return false
    if (nodeFilter !== 'all' && e.nodeId !== nodeFilter) return false
    return true
  })

  // Unique nodes for filter dropdown
  const uniqueNodes = Array.from(new Map(logs.map(e => [e.nodeId, e.nodeName])).entries())

  const downloadLogs = (format: 'json' | 'txt') => {
    const content = format === 'json'
      ? JSON.stringify(logs, null, 2)
      : logs.map(e => `[${formatTime(e.timestamp)}] [${e.level.toUpperCase()}] ${e.nodeName}: ${e.message}`).join('\n')
    const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `execution-logs.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={clsx('flex flex-col min-h-0', className)}>
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
          Logs <span className="ml-1 font-normal text-gray-400">({filtered.length})</span>
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => downloadLogs('txt')}
            className="toolbar-btn !w-7 !h-7" title="Download .txt"
            aria-label="Download logs as TXT"
          >
            <Download size={12} />
          </button>
          <button
            onClick={() => downloadLogs('json')}
            className="toolbar-btn !w-7 !h-7" title="Download .json"
            aria-label="Download logs as JSON"
          >
            <span className="text-[9px] font-mono font-bold">JSON</span>
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5 bg-gray-50 dark:bg-gray-800/60 border-b border-gray-200 dark:border-gray-700 shrink-0">
        {/* Level filter pills */}
        <div className="flex gap-0.5" role="group" aria-label="Filter by level">
          {LEVELS.map(l => (
            <button
              key={l}
              onClick={() => setLevelFilter(l)}
              className={clsx(
                'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase transition-colors',
                levelFilter === l
                  ? 'bg-primary-500 text-white'
                  : 'text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
              )}
              aria-pressed={levelFilter === l}
            >
              {l === 'all' ? 'All' : LEVEL_STYLE[l as LogLevel].label}
            </button>
          ))}
        </div>

        {/* Node filter */}
        {uniqueNodes.length > 1 && (
          <div className="flex items-center gap-1 ml-auto">
            <Filter size={10} className="text-gray-400" aria-hidden="true" />
            <select
              value={nodeFilter}
              onChange={e => setNodeFilter(e.target.value)}
              className="text-[10px] bg-transparent border border-gray-200 dark:border-gray-600 rounded px-1 py-0.5 text-gray-600 dark:text-gray-400 focus:outline-none"
              aria-label="Filter by agent"
            >
              <option value="all">All agents</option>
              {uniqueNodes.map(([id, name]) => (
                <option key={id} value={id}>{name}</option>
              ))}
            </select>
            {nodeFilter !== 'all' && (
              <button onClick={() => setNodeFilter('all')} className="text-gray-400 hover:text-gray-600" aria-label="Clear agent filter">
                <X size={10} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Log rows */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto bg-white dark:bg-gray-900 divide-y divide-gray-100 dark:divide-gray-800"
        role="log"
        aria-live="polite"
        aria-label="Execution logs"
      >
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-xs text-gray-400 italic">
            {logs.length === 0 ? 'Waiting for execution to start…' : 'No logs match filter.'}
          </div>
        ) : (
          filtered.map(entry => (
            <LogRow
              key={entry.id}
              entry={entry}
              highlighted={highlightedNodeId === entry.nodeId}
              onClick={e => onLogClick(e.nodeId)}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true)
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
          }}
          className="absolute bottom-2 right-2 flex items-center gap-1 rounded-full bg-primary-500 text-white text-[10px] px-2 py-1 shadow-lg hover:bg-primary-600 transition-colors"
          aria-label="Jump to latest log"
        >
          ↓ Latest
        </button>
      )}
    </div>
  )
}
