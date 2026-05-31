import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft, Pause, Square, RotateCcw, Download, Share2,
  CheckCircle, XCircle, Clock, Loader, Zap, TrendingUp,
  AlertTriangle, Wifi, WifiOff,
} from 'lucide-react'
import clsx from 'clsx'
import LiveCanvas from './LiveCanvas'
import LogsPanel from './LogsPanel'
import { useWebSocket } from '../hooks/useWebSocket'
import type {
  CanvasNode, CanvasEdge, ExecutionNodeStatus, LogEntry,
  LiveMetrics, MonitorStatus, NodeRunStatus,
} from '../types'

// ─── Demo workflow (used when no canvas data in localStorage) ─────────────────

const DEMO_NODES: CanvasNode[] = [
  { id: 'start',   type: 'start',     label: 'Start',          x: 60,   y: 240 },
  { id: 'extract', type: 'agent',     label: 'Extract Data',   x: 200,  y: 150, role: 'processor' },
  { id: 'enrich',  type: 'agent',     label: 'Enrich Data',    x: 400,  y: 240, role: 'analyst'   },
  { id: 'cond1',   type: 'condition', label: 'Records > 0?',   x: 580,  y: 240, condition: 'records > 0' },
  { id: 'analyze', type: 'agent',     label: 'Analyze Data',   x: 720,  y: 150, role: 'analyst'   },
  { id: 'report',  type: 'agent',     label: 'Gen. Report',    x: 920,  y: 240, role: 'writer'    },
  { id: 'end',     type: 'end',       label: 'End',            x: 1100, y: 240 },
]

const DEMO_EDGES: CanvasEdge[] = [
  { id: 'e1', source: 'start',   target: 'extract' },
  { id: 'e2', source: 'extract', target: 'enrich' },
  { id: 'e3', source: 'enrich',  target: 'cond1' },
  { id: 'e4', source: 'cond1',   target: 'analyze', branch: 'true' },
  { id: 'e5', source: 'analyze', target: 'report' },
  { id: 'e6', source: 'report',  target: 'end' },
]

// Realistic log messages per node
const NODE_MESSAGES: Record<string, string[][]> = {
  extract: [
    ['info',  'Starting extraction from data source'],
    ['debug', 'Connecting to API endpoint'],
    ['info',  'Retrieved 142 records successfully'],
    ['debug', 'Parsing response payload'],
  ],
  enrich: [
    ['info',  'Enriching 142 records with metadata'],
    ['debug', 'Fetching geolocation for 87 entries'],
    ['warn',  '12 records missing optional fields'],
    ['info',  'Enrichment complete — 130 records enriched'],
  ],
  cond1: [
    ['info',  'Evaluating condition: records > 0'],
    ['info',  'Condition TRUE — proceeding to analysis'],
  ],
  analyze: [
    ['info',  'Running statistical analysis on enriched data'],
    ['debug', 'Computing aggregations…'],
    ['info',  'Analysis complete — 3 key insights identified'],
  ],
  report: [
    ['info',  'Generating markdown report'],
    ['debug', 'Rendering 3-page summary'],
    ['info',  'Report generated: execution_report.md (2.4 KB)'],
  ],
}

// Node run durations ms
const NODE_DURATIONS: Record<string, number> = {
  extract: 2800,
  enrich:  3400,
  cond1:   600,
  analyze: 4200,
  report:  2100,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function uid() { return Math.random().toString(36).slice(2, 9) }

function topoSort(nodes: CanvasNode[], edges: CanvasEdge[]): CanvasNode[] {
  const adj = new Map<string, string[]>()
  const inDeg = new Map<string, number>()
  nodes.forEach(n => { adj.set(n.id, []); inDeg.set(n.id, 0) })
  edges.forEach(e => {
    adj.get(e.source)?.push(e.target)
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1)
  })
  const q = nodes.filter(n => inDeg.get(n.id) === 0)
  const sorted: CanvasNode[] = []
  while (q.length > 0) {
    const n = q.shift()!
    sorted.push(n)
    for (const nb of adj.get(n.id) ?? []) {
      const d = (inDeg.get(nb) ?? 0) - 1
      inDeg.set(nb, d)
      if (d === 0) q.push(nodes.find(x => x.id === nb)!)
    }
  }
  return sorted
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}m ${s}s`
}

function useElapsed(startTime: Date | null, active: boolean): string {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!startTime || !active) return
    const tick = () => setElapsed(Date.now() - startTime.getTime())
    tick()
    const id = setInterval(tick, 500)
    return () => clearInterval(id)
  }, [startTime, active])
  return formatDuration(elapsed)
}

// ─── Metrics Cards ────────────────────────────────────────────────────────────

const MetricCard = memo(({ icon: Icon, label, value, sub, color }: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string; value: string; sub?: string; color: string
}) => (
  <div className={clsx('flex items-center gap-2.5 p-3 rounded-xl border', color)}>
    <Icon size={16} className="shrink-0 opacity-70" />
    <div className="min-w-0">
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-sm font-bold text-gray-900 dark:text-white truncate">{value}</p>
      {sub && <p className="text-[10px] text-gray-400">{sub}</p>}
    </div>
  </div>
))
MetricCard.displayName = 'MetricCard'

function MetricsGrid({ metrics, elapsedLabel }: { metrics: LiveMetrics; elapsedLabel: string }) {
  const pct = metrics.nodesTotal > 0
    ? Math.round((metrics.nodesCompleted / metrics.nodesTotal) * 100)
    : 0

  return (
    <div className="p-3 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <MetricCard
          icon={CheckCircle} label="Progress"
          value={`${metrics.nodesCompleted}/${metrics.nodesTotal}`}
          sub={`${pct}% complete`}
          color="border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20"
        />
        <MetricCard
          icon={Clock} label="Duration"
          value={elapsedLabel}
          sub="elapsed"
          color="border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20"
        />
        <MetricCard
          icon={Zap} label="Tokens"
          value={metrics.tokensUsed.toLocaleString()}
          sub={`≈ $${metrics.estimatedCostUsd.toFixed(4)}`}
          color="border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20"
        />
        <MetricCard
          icon={TrendingUp} label="Success"
          value={`${metrics.successRate}%`}
          sub={metrics.nodesFailed > 0 ? `${metrics.nodesFailed} failed` : 'all passed'}
          color={metrics.nodesFailed > 0
            ? 'border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20'
            : 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20'}
        />
      </div>

      {/* Progress bar */}
      <div>
        <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-primary-400 to-primary-600 transition-all duration-500"
            style={{ width: `${pct}%` }}
            role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
          />
        </div>
      </div>

      {/* Current agent */}
      {metrics.currentNodeLabel && (
        <div className="flex items-center gap-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 px-3 py-2">
          <Loader size={12} className="text-blue-500 animate-spin shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-[10px] text-gray-500 dark:text-gray-400">Running now</p>
            <p className="text-xs font-semibold text-blue-700 dark:text-blue-300 truncate">{metrics.currentNodeLabel}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Execution Timeline (left sidebar) ───────────────────────────────────────

const STATUS_ICON: Record<NodeRunStatus, React.ComponentType<{ size?: number; className?: string }>> = {
  idle:      Clock,
  running:   Loader,
  completed: CheckCircle,
  error:     XCircle,
  skipped:   Clock,
}

const STATUS_COLOR: Record<NodeRunStatus, string> = {
  idle:      'text-gray-400',
  running:   'text-blue-500',
  completed: 'text-green-500',
  error:     'text-red-500',
  skipped:   'text-gray-400',
}

function TimelinePanel({ nodes, nodeStatuses, onNodeClick, highlightedNodeId }: {
  nodes: CanvasNode[]
  nodeStatuses: Map<string, ExecutionNodeStatus>
  onNodeClick: (id: string) => void
  highlightedNodeId: string | null
}) {
  const ordered = nodes.filter(n => n.type === 'agent' || n.type === 'condition' || n.type === 'start' || n.type === 'end')

  return (
    <aside className="w-52 shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 overflow-y-auto">
      <p className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 border-b border-gray-200 dark:border-gray-700">
        Timeline
      </p>
      <ol role="list" className="py-2 px-2 space-y-0.5">
        {ordered.map((node, idx) => {
          const st = nodeStatuses.get(node.id)
          const runStatus: NodeRunStatus = st?.status ?? 'idle'
          const Icon = STATUS_ICON[runStatus]
          const isHighlighted = highlightedNodeId === node.id

          return (
            <li key={node.id}>
              <button
                onClick={() => onNodeClick(node.id)}
                className={clsx(
                  'w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                  isHighlighted
                    ? 'bg-cyan-50 dark:bg-cyan-900/20 ring-1 ring-cyan-400'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-800',
                )}
                aria-current={isHighlighted ? 'true' : undefined}
              >
                <span className="text-[10px] tabular-nums text-gray-400 w-4 shrink-0">{idx + 1}</span>
                <Icon
                  size={13}
                  className={clsx('shrink-0', STATUS_COLOR[runStatus], runStatus === 'running' && 'animate-spin')}
                  aria-hidden="true"
                />
                <span className="flex-1 min-w-0 truncate font-medium text-gray-700 dark:text-gray-300">
                  {node.label}
                </span>
              </button>
              {st?.durationMs !== undefined && (
                <p className="pl-9 text-[9px] text-gray-400 tabular-nums">
                  {formatDuration(st.durationMs)}
                  {st.tokensUsed ? ` · ${st.tokensUsed.toLocaleString()} tok` : ''}
                </p>
              )}
            </li>
          )
        })}
      </ol>
    </aside>
  )
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const MONITOR_BADGE: Record<MonitorStatus, { label: string; cls: string }> = {
  idle:      { label: 'Idle',      cls: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' },
  running:   { label: 'Running',   cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' },
  paused:    { label: 'Paused',    cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' },
  completed: { label: 'Completed', cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' },
  failed:    { label: 'Failed',    cls: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300' },
  stopped:   { label: 'Stopped',   cls: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' },
}

// ─── Main ExecutionMonitor ────────────────────────────────────────────────────

interface ExecutionMonitorProps {
  executionId?: string
  workflowId?: string
  workflowName?: string
  /** If provided, connect to this WebSocket endpoint for live updates */
  wsUrl?: string
}

const DEFAULT_METRICS: LiveMetrics = {
  nodesTotal: 0, nodesCompleted: 0, nodesFailed: 0,
  totalDurationMs: 0, tokensUsed: 0, estimatedCostUsd: 0,
  currentNodeLabel: null, successRate: 100,
}

export default function ExecutionMonitor({
  executionId = 'demo',
  workflowName = 'Workflow',
  wsUrl,
}: ExecutionMonitorProps) {
  // Load canvas state from localStorage (set by WorkflowCanvas in Phase 2.2)
  const [nodes, setNodes] = useState<CanvasNode[]>(() => {
    try {
      const raw = localStorage.getItem(`workflow_canvas_${executionId}`)
      const parsed = raw ? (JSON.parse(raw) as { nodes?: CanvasNode[] }) : null
      if (parsed?.nodes && parsed.nodes.length > 2) return parsed.nodes
    } catch { /* fall through */ }
    return DEMO_NODES
  })

  const [edges, setEdges] = useState<CanvasEdge[]>(() => {
    try {
      const raw = localStorage.getItem(`workflow_canvas_${executionId}`)
      const parsed = raw ? (JSON.parse(raw) as { edges?: CanvasEdge[] }) : null
      if (parsed?.edges) return parsed.edges
    } catch { /* fall through */ }
    return DEMO_EDGES
  })

  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus>('idle')
  const [nodeStatuses, setNodeStatuses] = useState<Map<string, ExecutionNodeStatus>>(new Map())
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [metrics, setMetrics] = useState<LiveMetrics>({ ...DEFAULT_METRICS, nodesTotal: nodes.filter(n => n.type === 'agent' || n.type === 'condition').length })
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null)
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null)
  const [startTime, setStartTime] = useState<Date | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const pausedRef = useRef(false)

  const elapsedLabel = useElapsed(startTime, monitorStatus === 'running')

  // ── WebSocket (real backend) ──────────────────────────────────────────────

  const { status: wsStatus } = useWebSocket(wsUrl ?? null, {
    onMessage: msg => {
      if (msg.type === 'node_status' && msg.nodeStatus) {
        const ns = msg.nodeStatus
        setNodeStatuses(prev => new Map(prev).set(ns.nodeId, ns))
        if (ns.status === 'running') setCurrentNodeId(ns.nodeId)
        if (ns.status === 'completed' || ns.status === 'error') {
          setMetrics(prev => ({
            ...prev,
            nodesCompleted: prev.nodesCompleted + (ns.status === 'completed' ? 1 : 0),
            nodesFailed:    prev.nodesFailed    + (ns.status === 'error'     ? 1 : 0),
            tokensUsed:     prev.tokensUsed     + (ns.tokensUsed ?? 0),
          }))
        }
      }
      if (msg.type === 'log' && msg.log) {
        setLogs(prev => [...prev, msg.log!])
      }
      if (msg.type === 'execution_complete') {
        setMonitorStatus('completed')
        setCurrentNodeId(null)
      }
      if (msg.type === 'execution_error') {
        setMonitorStatus('failed')
        setErrorMsg(msg.error ?? 'Unknown error')
        setCurrentNodeId(null)
      }
    },
  })

  // ── Simulation (frontend-only when no WS) ────────────────────────────────

  const addLog = useCallback((
    level: LogEntry['level'],
    nodeId: string,
    nodeName: string,
    message: string,
    data?: Record<string, unknown>,
  ) => {
    setLogs(prev => [...prev, {
      id: uid(),
      timestamp: new Date().toISOString(),
      level, nodeId, nodeName, message, data,
    }])
  }, [])

  const stopSimulation = useCallback(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }, [])

  const runSimulation = useCallback((simNodes: CanvasNode[], simEdges: CanvasEdge[]) => {
    stopSimulation()
    pausedRef.current = false

    setNodeStatuses(new Map())
    setLogs([])
    setCurrentNodeId(null)
    setErrorMsg(null)
    setMetrics(prev => ({
      ...DEFAULT_METRICS,
      nodesTotal: simNodes.filter(n => n.type === 'agent' || n.type === 'condition').length,
      successRate: prev.successRate,
    }))

    setMonitorStatus('running')
    setStartTime(new Date())

    const sorted = topoSort(simNodes, simEdges)
      .filter(n => n.type === 'agent' || n.type === 'condition')

    let cumDelay = 400

    sorted.forEach((node, idx) => {
      const runDuration = NODE_DURATIONS[node.id] ?? (1200 + Math.random() * 2000)
      const messages = NODE_MESSAGES[node.id] ?? [
        ['info',  `Starting ${node.label}`],
        ['info',  `${node.label} completed`],
      ]
      const tokensForNode = Math.floor(200 + Math.random() * 800)

      // Start running
      const t1 = setTimeout(() => {
        if (pausedRef.current) return
        setNodeStatuses(prev => new Map(prev).set(node.id, {
          nodeId: node.id, status: 'running', startedAt: new Date().toISOString(),
        }))
        setCurrentNodeId(node.id)
        addLog('info', node.id, node.label, messages[0][1])
        setMetrics(prev => ({ ...prev, currentNodeLabel: node.label }))
      }, cumDelay)

      // Mid-run logs
      messages.slice(1).forEach((msg, mi) => {
        const t = setTimeout(() => {
          if (pausedRef.current) return
          addLog(msg[0] as LogEntry['level'], node.id, node.label, msg[1])
        }, cumDelay + (runDuration / (messages.length)) * (mi + 1))
        timers.current.push(t)
      })

      // Complete
      const t2 = setTimeout(() => {
        if (pausedRef.current) return
        setNodeStatuses(prev => new Map(prev).set(node.id, {
          nodeId: node.id, status: 'completed',
          startedAt: new Date(Date.now() - runDuration).toISOString(),
          completedAt: new Date().toISOString(),
          durationMs: runDuration,
          tokensUsed: tokensForNode,
          output: { status: 'ok', records: 142 },
        }))

        setMetrics(prev => {
          const completed = prev.nodesCompleted + 1
          const total = prev.nodesTotal
          const tokens = prev.tokensUsed + tokensForNode
          return {
            ...prev,
            nodesCompleted: completed,
            tokensUsed: tokens,
            estimatedCostUsd: tokens * 0.000012,
            successRate: Math.round((completed / total) * 100),
            currentNodeLabel: idx === sorted.length - 1 ? null : prev.currentNodeLabel,
          }
        })

        if (idx === sorted.length - 1) {
          setMonitorStatus('completed')
          setCurrentNodeId(null)
          addLog('info', node.id, node.label, '✓ Workflow execution completed successfully')
        }
      }, cumDelay + runDuration)

      timers.current.push(t1, t2)
      cumDelay += runDuration + 300
    })
  }, [addLog, stopSimulation])

  // Auto-start simulation on mount if no WS
  useEffect(() => {
    if (!wsUrl) runSimulation(nodes, edges)
    return stopSimulation
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handlePause = () => {
    pausedRef.current = !pausedRef.current
    setMonitorStatus(pausedRef.current ? 'paused' : 'running')
  }

  const handleStop = () => {
    stopSimulation()
    setMonitorStatus('stopped')
    setCurrentNodeId(null)
  }

  const handleRerun = () => {
    runSimulation(nodes, edges)
  }

  const handleExportLogs = () => {
    const content = JSON.stringify({ executionId, logs, nodeStatuses: Object.fromEntries(nodeStatuses) }, null, 2)
    const blob = new Blob([content], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `execution_${executionId}.json`
    a.click()
  }

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href).catch(() => { /* clipboard not available */ })
  }

  const handleNodeClick = (nodeId: string) => {
    setHighlightedNodeId(prev => prev === nodeId ? null : nodeId)
  }

  const badge = MONITOR_BADGE[monitorStatus]

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900">

      {/* ── Header ── */}
      <header className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <Link
          to="/executions"
          className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 rounded"
          aria-label="Back to executions"
        >
          <ArrowLeft size={16} />
        </Link>

        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-sm font-semibold text-gray-900 dark:text-white truncate">{workflowName}</h1>
          <span className="text-xs text-gray-400 font-mono">#{executionId.slice(0, 8)}</span>
          <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold', badge.cls)}>
            {monitorStatus === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 mr-1 animate-pulse" />}
            {badge.label}
          </span>
        </div>

        {startTime && (
          <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums ml-1">
            Started {startTime.toLocaleTimeString()} · {elapsedLabel}
          </span>
        )}

        {/* WS status indicator */}
        {wsUrl && (
          <span className={clsx('flex items-center gap-1 text-xs ml-1', wsStatus === 'connected' ? 'text-green-500' : 'text-gray-400')}
            title={`WebSocket: ${wsStatus}`} aria-label={`WebSocket ${wsStatus}`}>
            {wsStatus === 'connected' ? <Wifi size={12} /> : <WifiOff size={12} />}
          </span>
        )}

        <div className="flex items-center gap-1 ml-auto">
          <button
            onClick={handlePause}
            disabled={monitorStatus === 'completed' || monitorStatus === 'failed' || monitorStatus === 'stopped' || monitorStatus === 'idle'}
            className={clsx('toolbar-btn', monitorStatus === 'paused' && '!text-amber-500')}
            aria-label={monitorStatus === 'paused' ? 'Resume' : 'Pause'}
            title={monitorStatus === 'paused' ? 'Resume' : 'Pause'}
          >
            <Pause size={15} />
          </button>
          <button
            onClick={handleStop}
            disabled={monitorStatus !== 'running' && monitorStatus !== 'paused'}
            className="toolbar-btn"
            aria-label="Stop execution"
            title="Stop"
          >
            <Square size={15} />
          </button>
          <button
            onClick={handleRerun}
            className="toolbar-btn"
            aria-label="Re-run workflow"
            title="Re-run"
          >
            <RotateCcw size={15} />
          </button>

          <div className="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-1" aria-hidden="true" />

          <button onClick={handleExportLogs} className="toolbar-btn" aria-label="Export logs" title="Export logs">
            <Download size={15} />
          </button>
          <button onClick={handleShare} className="toolbar-btn" aria-label="Copy share link" title="Share">
            <Share2 size={15} />
          </button>
        </div>
      </header>

      {/* ── Error banner ── */}
      {(monitorStatus === 'failed' && errorMsg) && (
        <div className="flex items-center gap-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800" role="alert">
          <AlertTriangle size={16} className="text-red-500 shrink-0" aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-red-800 dark:text-red-300">Execution failed</p>
            <p className="text-xs text-red-700 dark:text-red-400 mt-0.5 font-mono truncate">{errorMsg}</p>
          </div>
          <button
            onClick={handleRerun}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          >
            <RotateCcw size={12} /> Retry
          </button>
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left: Timeline */}
        <TimelinePanel
          nodes={nodes}
          nodeStatuses={nodeStatuses}
          onNodeClick={handleNodeClick}
          highlightedNodeId={highlightedNodeId}
        />

        {/* Center: Live canvas */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          <div className="flex-1 min-h-0">
            <LiveCanvas
              nodes={nodes}
              edges={edges}
              nodeStatuses={nodeStatuses}
              currentNodeId={currentNodeId}
              highlightedNodeId={highlightedNodeId}
              onNodeClick={handleNodeClick}
            />
          </div>
        </div>

        {/* Right: Metrics + Logs */}
        <div className="w-72 shrink-0 flex flex-col border-l border-gray-200 dark:border-gray-700 overflow-hidden">
          <MetricsGrid metrics={metrics} elapsedLabel={elapsedLabel} />
          <div className="flex-1 min-h-0 border-t border-gray-200 dark:border-gray-700 relative">
            <LogsPanel
              logs={logs}
              highlightedNodeId={highlightedNodeId}
              onLogClick={handleNodeClick}
              className="h-full"
            />
          </div>
        </div>
      </div>
    </div>
  )
}
