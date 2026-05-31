import { memo, useRef, useEffect, useState } from 'react'
import { CheckCircle, XCircle, Bot, GitBranch } from 'lucide-react'
import clsx from 'clsx'
import type { CanvasNode, CanvasEdge, ExecutionNodeStatus, NodeRunStatus } from '../types'

// ─── Constants (mirror WorkflowCanvas) ───────────────────────────────────────

const NODE_W = 140
const NODE_H = 60
const COND_SIZE = 72
const CIRCLE_R = 20
const PAD = 48

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getOutputPort(node: CanvasNode) {
  if (node.type === 'start')     return { x: node.x + CIRCLE_R * 2, y: node.y + CIRCLE_R }
  if (node.type === 'end')       return { x: node.x, y: node.y + CIRCLE_R }
  if (node.type === 'condition') return { x: node.x + COND_SIZE, y: node.y + COND_SIZE / 2 }
  return { x: node.x + NODE_W, y: node.y + NODE_H / 2 }
}

function getInputPort(node: CanvasNode) {
  if (node.type === 'start')     return { x: node.x, y: node.y + CIRCLE_R }
  if (node.type === 'end')       return { x: node.x, y: node.y + CIRCLE_R }
  if (node.type === 'condition') return { x: node.x, y: node.y + COND_SIZE / 2 }
  return { x: node.x, y: node.y + NODE_H / 2 }
}

function bezier(x1: number, y1: number, x2: number, y2: number): string {
  const cx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${cx} ${y1} ${cx} ${y2} ${x2} ${y2}`
}

function calcFit(nodes: CanvasNode[], viewW: number, viewH: number) {
  if (nodes.length === 0) return { scale: 1, tx: PAD, ty: PAD }
  const xs = nodes.map(n => n.x)
  const ys = nodes.map(n => n.y)
  const minX = Math.min(...xs) - PAD
  const minY = Math.min(...ys) - PAD
  const maxX = Math.max(...xs) + NODE_W + PAD
  const maxY = Math.max(...ys) + NODE_H + PAD
  const cw = maxX - minX
  const ch = maxY - minY
  const scale = Math.min(viewW / cw, viewH / ch, 1.4) * 0.92
  const tx = (viewW / scale - cw) / 2 - minX
  const ty = (viewH / scale - ch) / 2 - minY
  return { scale, tx, ty }
}

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_RING: Record<NodeRunStatus, string> = {
  idle:      '',
  running:   'ring-2 ring-blue-400 dark:ring-blue-500',
  completed: 'ring-2 ring-green-400 dark:ring-green-500',
  error:     'ring-2 ring-red-400 dark:ring-red-500',
  skipped:   'ring-1 ring-gray-300 dark:ring-gray-600 opacity-50',
}

const STATUS_BG: Record<NodeRunStatus, string> = {
  idle:      'bg-gray-100 dark:bg-gray-700',
  running:   'bg-blue-50 dark:bg-blue-900/50',
  completed: 'bg-green-50 dark:bg-green-900/30',
  error:     'bg-red-50 dark:bg-red-900/40',
  skipped:   'bg-gray-50 dark:bg-gray-800',
}

const CURRENT_GLOW = 'shadow-[0_0_0_3px_rgba(6,182,212,0.5)] dark:shadow-[0_0_0_3px_rgba(22,189,202,0.35)]'

// ─── Status badge overlay ─────────────────────────────────────────────────────

function StatusBadge({ status }: { status: NodeRunStatus }) {
  if (status === 'idle' || status === 'skipped') return null
  if (status === 'running') {
    return (
      <div className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-blue-500 flex items-center justify-center">
        <span className="absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75 animate-ping" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500" />
      </div>
    )
  }
  if (status === 'completed') {
    return (
      <div className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-green-500 flex items-center justify-center">
        <CheckCircle size={10} className="text-white" />
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-500 flex items-center justify-center">
        <XCircle size={10} className="text-white" />
      </div>
    )
  }
  return null
}

// ─── Single node ─────────────────────────────────────────────────────────────

interface NodeViewProps {
  node: CanvasNode
  nodeStatus: ExecutionNodeStatus | undefined
  isCurrent: boolean
  isHighlighted: boolean
  onClick: (nodeId: string) => void
}

const LiveNodeView = memo(({ node, nodeStatus, isCurrent, isHighlighted, onClick }: NodeViewProps) => {
  const runStatus: NodeRunStatus = nodeStatus?.status ?? 'idle'

  if (node.type === 'start' || node.type === 'end') {
    const baseColor = node.type === 'start'
      ? 'border-green-500 bg-green-100 dark:bg-green-900/40 dark:border-green-400 text-green-800 dark:text-green-200'
      : 'border-red-500 bg-red-100 dark:bg-red-900/40 dark:border-red-400 text-red-800 dark:text-red-200'
    return (
      <div
        className={clsx('absolute flex items-center justify-center rounded-full border-2 text-xs font-bold cursor-pointer', baseColor,
          isCurrent && CURRENT_GLOW, isHighlighted && 'ring-2 ring-cyan-400')}
        style={{ left: node.x, top: node.y, width: CIRCLE_R * 2, height: CIRCLE_R * 2 }}
        onClick={() => onClick(node.id)}
        role="button" aria-label={`${node.label} node`}
      >
        {node.type === 'start' ? '▶' : '■'}
        <StatusBadge status={runStatus} />
      </div>
    )
  }

  if (node.type === 'condition') {
    return (
      <div
        className={clsx('absolute cursor-pointer', isCurrent && CURRENT_GLOW, isHighlighted && 'ring-2 ring-cyan-400 rounded')}
        style={{ left: node.x, top: node.y, width: COND_SIZE, height: COND_SIZE }}
        onClick={() => onClick(node.id)}
        role="button" aria-label={`Condition: ${node.label}`}
      >
        <div
          className={clsx('absolute inset-1 border-2 border-amber-400 dark:border-amber-500 transition-all', STATUS_BG[runStatus], STATUS_RING[runStatus])}
          style={{ transform: 'rotate(45deg)', borderRadius: 4 }}
        />
        <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <span className="text-xs font-bold text-amber-800 dark:text-amber-200">IF</span>
        </div>
        <StatusBadge status={runStatus} />
      </div>
    )
  }

  // Agent node
  const roleColorBorder: Record<string, string> = {
    analyst:    'border-blue-400',
    researcher: 'border-purple-400',
    writer:     'border-green-400',
    processor:  'border-orange-400',
    default:    'border-gray-400',
  }
  const borderCls = roleColorBorder[node.role ?? 'default']

  return (
    <div
      className={clsx(
        'absolute flex items-center justify-center gap-1.5 rounded-lg border-2 text-xs font-medium cursor-pointer select-none transition-all',
        borderCls,
        STATUS_BG[runStatus],
        STATUS_RING[runStatus],
        isCurrent && CURRENT_GLOW,
        isHighlighted && '!ring-2 !ring-cyan-400',
        runStatus === 'running' && 'animate-pulse-subtle',
      )}
      style={{ left: node.x, top: node.y, width: NODE_W, height: NODE_H }}
      onClick={() => onClick(node.id)}
      role="button" aria-label={`Agent: ${node.label} — ${runStatus}`}
    >
      <Bot size={12} className="shrink-0 opacity-60" aria-hidden="true" />
      <span className={clsx(
        'truncate max-w-[90px]',
        runStatus === 'completed' ? 'text-green-800 dark:text-green-200' :
        runStatus === 'error'     ? 'text-red-800 dark:text-red-200' :
        runStatus === 'running'   ? 'text-blue-800 dark:text-blue-200' :
        'text-gray-700 dark:text-gray-300',
      )}>
        {node.label}
      </span>
      <StatusBadge status={runStatus} />
    </div>
  )
})
LiveNodeView.displayName = 'LiveNodeView'

// ─── Edge (color by status) ───────────────────────────────────────────────────

function edgeColor(srcStatus: NodeRunStatus, tgtStatus: NodeRunStatus): string {
  if (srcStatus === 'completed' && (tgtStatus === 'running' || tgtStatus === 'completed')) return '#22c55e'
  if (srcStatus === 'error') return '#ef4444'
  return '#94a3b8'
}

// ─── Main LiveCanvas ──────────────────────────────────────────────────────────

interface LiveCanvasProps {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  nodeStatuses: Map<string, ExecutionNodeStatus>
  currentNodeId: string | null
  highlightedNodeId: string | null
  onNodeClick?: (nodeId: string) => void
}

export default function LiveCanvas({
  nodes,
  edges,
  nodeStatuses,
  currentNodeId,
  highlightedNodeId,
  onNodeClick,
}: LiveCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState({ scale: 1, tx: 0, ty: 0 })

  // Recalculate fit on mount and when nodes change
  useEffect(() => {
    const el = containerRef.current
    if (!el || nodes.length === 0) return
    const { width, height } = el.getBoundingClientRect()
    setFit(calcFit(nodes, width, height))
  }, [nodes])

  // Also recalculate on resize
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const e = entries[0]
      if (!e) return
      const { width, height } = e.contentRect
      setFit(calcFit(nodes, width, height))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [nodes])

  const WORLD_W = 2400
  const WORLD_H = 1600

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden bg-white dark:bg-gray-950">
      {/* Transform world */}
      <div
        style={{
          position: 'absolute',
          top: 0, left: 0,
          width: WORLD_W, height: WORLD_H,
          transform: `scale(${fit.scale}) translate(${fit.tx}px, ${fit.ty}px)`,
          transformOrigin: 'top left',
        }}
      >
        {/* SVG: grid + edges */}
        <svg
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
          width={WORLD_W} height={WORLD_H}
          aria-hidden="true"
        >
          <defs>
            <pattern id="live-sg" width="20" height="20" patternUnits="userSpaceOnUse">
              <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#f0f0f0" strokeWidth="0.5" />
            </pattern>
            <pattern id="live-bg" width="100" height="100" patternUnits="userSpaceOnUse">
              <rect width="100" height="100" fill="url(#live-sg)" />
              <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#e5e7eb" strokeWidth="0.8" />
            </pattern>
            <marker id="live-arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#94a3b8" />
            </marker>
            <marker id="live-arrow-green" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#22c55e" />
            </marker>
            <marker id="live-arrow-red" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="#ef4444" />
            </marker>
          </defs>

          <rect width="100%" height="100%" fill="url(#live-bg)" />

          {edges.map(edge => {
            const src = nodes.find(n => n.id === edge.source)
            const tgt = nodes.find(n => n.id === edge.target)
            if (!src || !tgt) return null
            const p1 = getOutputPort(src)
            const p2 = getInputPort(tgt)
            const srcSt: NodeRunStatus = nodeStatuses.get(src.id)?.status ?? 'idle'
            const tgtSt: NodeRunStatus = nodeStatuses.get(tgt.id)?.status ?? 'idle'
            const color = edgeColor(srcSt, tgtSt)
            const markerId = color === '#22c55e' ? 'live-arrow-green' : color === '#ef4444' ? 'live-arrow-red' : 'live-arrow'
            return (
              <path
                key={edge.id}
                d={bezier(p1.x, p1.y, p2.x, p2.y)}
                stroke={color}
                strokeWidth={srcSt === 'completed' && (tgtSt === 'running' || tgtSt === 'completed') ? 2.5 : 1.5}
                fill="none"
                markerEnd={`url(#${markerId})`}
                style={{ transition: 'stroke 0.4s, stroke-width 0.3s' }}
              />
            )
          })}
        </svg>

        {/* Nodes */}
        {nodes.map(node => (
          <LiveNodeView
            key={node.id}
            node={node}
            nodeStatus={nodeStatuses.get(node.id)}
            isCurrent={currentNodeId === node.id}
            isHighlighted={highlightedNodeId === node.id}
            onClick={id => onNodeClick?.(id)}
          />
        ))}
      </div>
    </div>
  )
}
