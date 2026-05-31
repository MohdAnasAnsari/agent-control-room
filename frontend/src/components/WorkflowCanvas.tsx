import { useRef, useState, useCallback, useEffect, memo } from 'react'
import {
  Save, Trash2, ZoomIn, ZoomOut, RotateCcw, AlertCircle, CheckCircle,
  Download, Maximize2, Bot, GitBranch, Play,
} from 'lucide-react'
import clsx from 'clsx'
import { useCanvas, WORLD_W, WORLD_H } from '../hooks/useCanvas'
import type { CanvasNode, CanvasEdge, AgentRole, ValidationError } from '../types'

// ─── Constants ────────────────────────────────────────────────────────────────

const NODE_W = 140
const NODE_H = 60
const COND_SIZE = 72
const CIRCLE_R = 20
const PORT_R = 6

// ─── Helpers ──────────────────────────────────────────────────────────────────

function uid() { return Math.random().toString(36).slice(2, 9) }

function screenToWorld(clientX: number, clientY: number, container: HTMLDivElement, zoom: number) {
  const rect = container.getBoundingClientRect()
  return {
    x: (clientX - rect.left + container.scrollLeft) / zoom,
    y: (clientY - rect.top  + container.scrollTop)  / zoom,
  }
}

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

function bezierPath(x1: number, y1: number, x2: number, y2: number): string {
  const cx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${cx} ${y1} ${cx} ${y2} ${x2} ${y2}`
}

function getNodeColor(node: CanvasNode): string {
  if (node.type === 'start') return '#22c55e'
  if (node.type === 'end')   return '#ef4444'
  if (node.type === 'condition') return '#f59e0b'
  const roleMap: Record<AgentRole, string> = {
    analyst:    '#3b82f6',
    researcher: '#8b5cf6',
    writer:     '#22c55e',
    processor:  '#f97316',
  }
  return node.role ? (roleMap[node.role] ?? '#6b7280') : '#6b7280'
}

const ROLE_CLASSES: Record<AgentRole | 'default', string> = {
  analyst:    'border-blue-400   bg-blue-50    text-blue-800   dark:bg-blue-900/40  dark:border-blue-500  dark:text-blue-200',
  researcher: 'border-purple-400 bg-purple-50  text-purple-800 dark:bg-purple-900/40 dark:border-purple-500 dark:text-purple-200',
  writer:     'border-green-400  bg-green-50   text-green-800  dark:bg-green-900/40 dark:border-green-500  dark:text-green-200',
  processor:  'border-orange-400 bg-orange-50  text-orange-800 dark:bg-orange-900/40 dark:border-orange-500 dark:text-orange-200',
  default:    'border-gray-400   bg-gray-50    text-gray-800   dark:bg-gray-700    dark:border-gray-500  dark:text-gray-200',
}

const TEMPLATES: Array<{ type: CanvasNode['type']; role?: AgentRole; label: string; icon: React.ComponentType<{ size?: number }> }> = [
  { type: 'agent', role: 'analyst',    label: 'Analyst',    icon: Bot },
  { type: 'agent', role: 'researcher', label: 'Researcher', icon: Bot },
  { type: 'agent', role: 'writer',     label: 'Writer',     icon: Bot },
  { type: 'agent', role: 'processor',  label: 'Processor',  icon: Bot },
  { type: 'condition', label: 'Condition', icon: GitBranch },
]

// ─── Node rendering ───────────────────────────────────────────────────────────

interface NodeViewProps {
  node: CanvasNode
  selected: boolean
  hasError: boolean
  connecting: boolean
  onPointerDown: (e: React.PointerEvent, id: string) => void
  onPortClick: (e: React.MouseEvent, id: string, portType: 'input' | 'output') => void
  onContextMenu: (e: React.MouseEvent, id: string) => void
}

const NodeView = memo(({ node, selected, hasError, connecting, onPointerDown, onPortClick, onContextMenu }: NodeViewProps) => {
  const portBase = clsx(
    'absolute w-3 h-3 rounded-full bg-white border-2 border-current cursor-crosshair z-10 hover:scale-150 transition-transform',
    connecting && 'scale-150',
  )

  if (node.type === 'start' || node.type === 'end') {
    const color = node.type === 'start' ? 'border-green-500 bg-green-100 dark:bg-green-900/40 dark:border-green-400' : 'border-red-500 bg-red-100 dark:bg-red-900/40 dark:border-red-400'
    return (
      <div
        className={clsx(
          'absolute flex items-center justify-center rounded-full border-2 text-xs font-bold select-none cursor-default',
          color,
          node.type === 'start' ? 'text-green-800 dark:text-green-200' : 'text-red-800 dark:text-red-200',
          selected && 'ring-2 ring-offset-1 ring-primary-400',
          hasError && 'ring-2 ring-offset-1 ring-red-400',
        )}
        style={{ left: node.x, top: node.y, width: CIRCLE_R * 2, height: CIRCLE_R * 2 }}
        role="button"
        aria-label={`${node.label} node`}
        aria-pressed={selected}
        onPointerDown={e => onPointerDown(e, node.id)}
        onContextMenu={e => onContextMenu(e, node.id)}
      >
        {node.type === 'start' ? '▶' : '■'}
        {node.type === 'start' && (
          <div
            className={clsx(portBase, 'top-1/2 -translate-y-1/2 -right-1.5 translate-x-1/2 text-green-500')}
            onClick={e => onPortClick(e, node.id, 'output')}
            role="button" aria-label="Output port"
          />
        )}
        {node.type === 'end' && (
          <div
            className={clsx(portBase, 'top-1/2 -translate-y-1/2 -left-1.5 -translate-x-1/2 text-red-500')}
            onClick={e => onPortClick(e, node.id, 'input')}
            role="button" aria-label="Input port"
          />
        )}
      </div>
    )
  }

  if (node.type === 'condition') {
    return (
      <div
        className="absolute select-none"
        style={{ left: node.x, top: node.y, width: COND_SIZE, height: COND_SIZE }}
        onPointerDown={e => onPointerDown(e, node.id)}
        onContextMenu={e => onContextMenu(e, node.id)}
        role="button"
        aria-label={`Condition: ${node.label}`}
        aria-pressed={selected}
      >
        {/* Diamond shape */}
        <div
          className={clsx(
            'absolute inset-1 border-2 border-amber-400 bg-amber-50 dark:bg-amber-900/40 dark:border-amber-500',
            selected && 'ring-2 ring-primary-400',
            hasError && 'ring-2 ring-red-400',
          )}
          style={{ transform: 'rotate(45deg)', borderRadius: 4 }}
        />
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
          <span className="text-xs font-bold text-amber-800 dark:text-amber-200">IF</span>
          {node.condition && (
            <span className="text-[9px] text-amber-700 dark:text-amber-300 max-w-[52px] truncate">{node.condition}</span>
          )}
        </div>
        {/* Input port */}
        <div
          className={clsx(portBase, 'top-1/2 -translate-y-1/2 -left-1.5 -translate-x-1/2 text-amber-400')}
          onClick={e => onPortClick(e, node.id, 'input')}
          role="button" aria-label="Input port"
        />
        {/* Output port */}
        <div
          className={clsx(portBase, 'top-1/2 -translate-y-1/2 -right-1.5 translate-x-1/2 text-amber-400')}
          onClick={e => onPortClick(e, node.id, 'output')}
          role="button" aria-label="Output port (true)"
        />
      </div>
    )
  }

  // Agent node
  const roleClass = ROLE_CLASSES[node.role ?? 'default']
  return (
    <div
      className={clsx(
        'absolute flex items-center justify-center gap-1.5 rounded-lg border-2 text-xs font-medium cursor-move select-none transition-shadow hover:shadow-lg',
        roleClass,
        selected && '!border-primary-500 shadow-md ring-2 ring-primary-200 dark:ring-primary-800',
        hasError && '!border-red-400 ring-2 ring-red-200',
        'animate-[fadeIn_0.15s_ease]',
      )}
      style={{ left: node.x, top: node.y, width: NODE_W, height: NODE_H }}
      role="button"
      aria-label={`Agent: ${node.label}`}
      aria-pressed={selected}
      onPointerDown={e => onPointerDown(e, node.id)}
      onContextMenu={e => onContextMenu(e, node.id)}
    >
      <Bot size={13} className="shrink-0 opacity-70" aria-hidden="true" />
      <span className="truncate max-w-[90px]">{node.label}</span>
      {/* Input port */}
      <div
        className={clsx(portBase, 'top-1/2 -translate-y-1/2 -left-1.5 -translate-x-1/2')}
        style={{ borderColor: getNodeColor(node) }}
        onClick={e => onPortClick(e, node.id, 'input')}
        role="button" aria-label="Input port"
      />
      {/* Output port */}
      <div
        className={clsx(portBase, 'top-1/2 -translate-y-1/2 -right-1.5 translate-x-1/2')}
        style={{ borderColor: getNodeColor(node) }}
        onClick={e => onPortClick(e, node.id, 'output')}
        role="button" aria-label="Output port"
      />
    </div>
  )
})
NodeView.displayName = 'NodeView'

// ─── Minimap ──────────────────────────────────────────────────────────────────

const MINI_W = 168
const MINI_H = 112

function Minimap({ nodes, edges, containerRef, zoom }: {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  containerRef: React.RefObject<HTMLDivElement>
  zoom: number
}) {
  const sx = MINI_W / WORLD_W
  const sy = MINI_H / WORLD_H
  const container = containerRef.current

  return (
    <div
      className="absolute bottom-3 right-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/90 dark:bg-gray-900/90 shadow-md overflow-hidden"
      style={{ width: MINI_W, height: MINI_H }}
      aria-label="Minimap"
      aria-hidden="true"
    >
      <svg width={MINI_W} height={MINI_H}>
        {/* Edges */}
        {edges.map(e => {
          const src = nodes.find(n => n.id === e.source)
          const tgt = nodes.find(n => n.id === e.target)
          if (!src || !tgt) return null
          const p1 = getOutputPort(src)
          const p2 = getInputPort(tgt)
          return (
            <path
              key={e.id}
              d={bezierPath(p1.x * sx, p1.y * sy, p2.x * sx, p2.y * sy)}
              stroke="#94a3b8" strokeWidth={1} fill="none"
            />
          )
        })}
        {/* Nodes */}
        {nodes.map(n => {
          const color = getNodeColor(n)
          if (n.type === 'start' || n.type === 'end') {
            return <circle key={n.id} cx={(n.x + CIRCLE_R) * sx} cy={(n.y + CIRCLE_R) * sy} r={CIRCLE_R * sx * 1.5} fill={color} opacity={0.8} />
          }
          return (
            <rect
              key={n.id}
              x={n.x * sx} y={n.y * sy}
              width={(n.type === 'condition' ? COND_SIZE : NODE_W) * sx}
              height={(n.type === 'condition' ? COND_SIZE : NODE_H) * sy}
              fill={color} opacity={0.5} rx={2}
            />
          )
        })}
        {/* Viewport indicator */}
        {container && (
          <rect
            x={(container.scrollLeft / zoom) * sx}
            y={(container.scrollTop  / zoom) * sy}
            width={(container.clientWidth  / zoom) * sx}
            height={(container.clientHeight / zoom) * sy}
            fill="none" stroke="#3b82f6" strokeWidth={1.5}
          />
        )}
      </svg>
    </div>
  )
}

// ─── Context Menu ─────────────────────────────────────────────────────────────

interface ContextMenuProps {
  x: number; y: number; nodeId: string
  onEdit: () => void
  onDuplicate: () => void
  onInsertCondition: () => void
  onDelete: () => void
  onClose: () => void
}

function ContextMenu({ x, y, onEdit, onDuplicate, onInsertCondition, onDelete, onClose }: ContextMenuProps) {
  useEffect(() => {
    const close = () => onClose()
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [onClose])

  const items = [
    { label: 'Edit',                  action: onEdit,            cls: '' },
    { label: 'Duplicate',             action: onDuplicate,       cls: '' },
    { label: 'Insert condition after', action: onInsertCondition, cls: '' },
    { label: 'Delete',                action: onDelete,          cls: 'text-red-600 dark:text-red-400' },
  ]

  return (
    <div
      style={{ position: 'fixed', left: x, top: y }}
      className="z-50 w-48 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-xl py-1"
      role="menu"
      aria-label="Node actions"
      onPointerDown={e => e.stopPropagation()}
    >
      {items.map(item => (
        <button
          key={item.label}
          role="menuitem"
          onClick={() => { item.action(); onClose() }}
          className={clsx(
            'flex w-full items-center px-4 py-2 text-sm text-left hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors focus-visible:outline-none focus-visible:bg-gray-100 dark:focus-visible:bg-gray-700',
            item.cls || 'text-gray-700 dark:text-gray-300',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

// ─── Properties Panel ─────────────────────────────────────────────────────────

function PropertiesPanel({ node, onUpdate, onDelete }: {
  node: CanvasNode
  onUpdate: (id: string, updates: Partial<CanvasNode>) => void
  onDelete: (id: string) => void
}) {
  return (
    <aside
      className="w-56 shrink-0 flex flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-y-auto"
      aria-label="Properties panel"
    >
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Properties</h3>
      </div>
      <div className="flex-1 px-4 py-4 space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1" htmlFor="prop-label">Label</label>
          <input
            id="prop-label"
            type="text"
            value={node.label}
            onChange={e => onUpdate(node.id, { label: e.target.value })}
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        {node.type === 'agent' && (
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1" htmlFor="prop-role">Role</label>
            <select
              id="prop-role"
              value={node.role ?? ''}
              onChange={e => onUpdate(node.id, { role: e.target.value as AgentRole || undefined })}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="">— none —</option>
              <option value="analyst">Analyst</option>
              <option value="researcher">Researcher</option>
              <option value="writer">Writer</option>
              <option value="processor">Processor</option>
            </select>
          </div>
        )}

        {node.type === 'condition' && (
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1" htmlFor="prop-condition">Condition</label>
            <input
              id="prop-condition"
              type="text"
              value={node.condition ?? ''}
              onChange={e => onUpdate(node.id, { condition: e.target.value })}
              placeholder="e.g. score > 0.8"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        )}

        <div className="text-xs text-gray-400 space-y-1">
          <p>ID: <span className="font-mono">{node.id}</span></p>
          <p>Type: <span className="capitalize">{node.type}</span></p>
          <p>Pos: {Math.round(node.x)}, {Math.round(node.y)}</p>
        </div>
      </div>

      {node.type !== 'start' && node.type !== 'end' && (
        <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={() => onDelete(node.id)}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
          >
            <Trash2 size={14} />
            Delete node
          </button>
        </div>
      )}
    </aside>
  )
}

// ─── Validation Banner ────────────────────────────────────────────────────────

function ValidationBanner({ errors }: { errors: ValidationError[] }) {
  if (errors.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2 px-4 py-2 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800" role="alert" aria-live="polite">
      {errors.map((e, i) => (
        <span key={i} className="flex items-center gap-1 text-xs text-red-700 dark:text-red-400">
          <AlertCircle size={11} aria-hidden="true" /> {e.message}
        </span>
      ))}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface WorkflowCanvasProps {
  workflowId?: string
  workflowName?: string
  onSave?: (nodes: CanvasNode[], edges: CanvasEdge[]) => Promise<void>
}

export default function WorkflowCanvas({ workflowId = 'default', workflowName = 'Workflow', onSave }: WorkflowCanvasProps) {
  const canvas = useCanvas(workflowId)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef<{ nodeId: string; startClientX: number; startClientY: number; startNodeX: number; startNodeY: number } | null>(null)
  const [previewMouse, setPreviewMouse] = useState<{ x: number; y: number } | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<'success' | 'error' | null>(null)
  const [editingNode, setEditingNode] = useState<string | null>(null)

  // ── Drag-from-template ──────────────────────────────────────────────────────

  const handleTemplateDragStart = (
    e: React.DragEvent,
    type: CanvasNode['type'],
    role?: AgentRole,
    label?: string,
  ) => {
    e.dataTransfer.setData('application/json', JSON.stringify({ type, role, label }))
    e.dataTransfer.effectAllowed = 'copy'
  }

  const handleCanvasDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/json')
    if (!raw || !containerRef.current) return
    try {
      const { type, role, label } = JSON.parse(raw) as { type: CanvasNode['type']; role?: AgentRole; label?: string }
      const pos = screenToWorld(e.clientX, e.clientY, containerRef.current, canvas.zoom)
      canvas.addNode(type, Math.max(0, pos.x - NODE_W / 2), Math.max(0, pos.y - NODE_H / 2), label, role)
    } catch { /* invalid drag data */ }
  }

  // ── Node dragging ───────────────────────────────────────────────────────────

  const handleNodePointerDown = useCallback((e: React.PointerEvent, nodeId: string) => {
    if (canvas.connecting) return
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()

    canvas.setSelectedId(nodeId)
    canvas.setContextMenu(null)

    const node = canvas.nodes.find(n => n.id === nodeId)
    if (!node || node.type === 'start' || node.type === 'end') return

    dragging.current = {
      nodeId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startNodeX: node.x,
      startNodeY: node.y,
    }
  }, [canvas])

  const handleCanvasPointerMove = useCallback((e: React.PointerEvent) => {
    if (dragging.current && containerRef.current) {
      const { nodeId, startClientX, startClientY, startNodeX, startNodeY } = dragging.current
      const dx = (e.clientX - startClientX) / canvas.zoom
      const dy = (e.clientY - startClientY) / canvas.zoom
      canvas.updateNode(nodeId, {
        x: Math.max(0, Math.min(WORLD_W - NODE_W, startNodeX + dx)),
        y: Math.max(0, Math.min(WORLD_H - NODE_H, startNodeY + dy)),
      })
    }

    if (canvas.connecting && containerRef.current) {
      const pos = screenToWorld(e.clientX, e.clientY, containerRef.current, canvas.zoom)
      setPreviewMouse(pos)
    }
  }, [canvas])

  const handleCanvasPointerUp = useCallback(() => {
    dragging.current = null
  }, [])

  // ── Connection ports ────────────────────────────────────────────────────────

  const handlePortClick = useCallback((e: React.MouseEvent, nodeId: string, portType: 'input' | 'output') => {
    e.preventDefault()
    e.stopPropagation()

    if (!canvas.connecting && portType === 'output') {
      const node = canvas.nodes.find(n => n.id === nodeId)
      if (!node) return
      if (node.type === 'end') return
      const port = getOutputPort(node)
      canvas.setConnecting({ sourceId: nodeId, worldX: port.x, worldY: port.y })
      setPreviewMouse(port)
    } else if (canvas.connecting && portType === 'input') {
      if (canvas.connecting.sourceId !== nodeId) {
        canvas.addEdge(canvas.connecting.sourceId, nodeId)
      }
      canvas.setConnecting(null)
      setPreviewMouse(null)
    }
  }, [canvas])

  // Clicking canvas background cancels connecting
  const handleCanvasClick = useCallback((e: React.MouseEvent) => {
    if (canvas.connecting && e.target === e.currentTarget) {
      canvas.setConnecting(null)
      setPreviewMouse(null)
    }
    if ((e.target as Element).closest('[data-canvas-bg]')) {
      canvas.setSelectedId(null)
    }
  }, [canvas])

  // ── Context menu ────────────────────────────────────────────────────────────

  const handleNodeContextMenu = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.preventDefault()
    e.stopPropagation()
    canvas.setContextMenu({ screenX: e.clientX, screenY: e.clientY, nodeId })
  }, [canvas])

  // ── Keyboard shortcuts ──────────────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        canvas.setConnecting(null)
        canvas.setContextMenu(null)
        setPreviewMouse(null)
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && canvas.selectedId && !editingNode) {
        canvas.deleteNode(canvas.selectedId)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [canvas, editingNode])

  // ── Save ────────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    canvas.saveNow()
    if (!onSave) {
      setSaveMsg('success')
      setTimeout(() => setSaveMsg(null), 2500)
      return
    }
    setSaving(true)
    try {
      await onSave(canvas.nodes, canvas.edges)
      setSaveMsg('success')
    } catch {
      setSaveMsg('error')
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMsg(null), 2500)
    }
  }

  const handleExport = () => {
    const data = JSON.stringify({ nodes: canvas.nodes, edges: canvas.edges }, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${workflowName.replace(/\s+/g, '_')}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const selectedNode = canvas.nodes.find(n => n.id === canvas.selectedId)
  const errorNodeIds = new Set(canvas.errors.flatMap(e => e.nodeIds ?? []))

  return (
    <div className="flex flex-col h-full rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-900">

      {/* ── Toolbar ── */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0" role="toolbar" aria-label="Canvas toolbar">
        <span className="text-sm font-semibold text-gray-900 dark:text-white mr-2 truncate">{workflowName}</span>

        <div className="flex items-center gap-1 ml-auto">
          {/* Zoom controls */}
          <button onClick={() => canvas.setZoom(canvas.zoom - 0.1)} className="toolbar-btn" aria-label="Zoom out"><ZoomOut size={15} /></button>
          <span className="text-xs text-gray-500 w-10 text-center tabular-nums" aria-label={`Zoom: ${Math.round(canvas.zoom * 100)}%`}>
            {Math.round(canvas.zoom * 100)}%
          </span>
          <button onClick={() => canvas.setZoom(canvas.zoom + 0.1)} className="toolbar-btn" aria-label="Zoom in"><ZoomIn size={15} /></button>
          <button onClick={() => canvas.setZoom(1)} className="toolbar-btn" aria-label="Reset zoom"><Maximize2 size={15} /></button>

          <div className="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-1" aria-hidden="true" />

          <button onClick={canvas.clearCanvas} className="toolbar-btn" aria-label="Clear canvas"><RotateCcw size={15} /></button>
          <button onClick={handleExport} className="toolbar-btn" aria-label="Export JSON"><Download size={15} /></button>

          <div className="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-1" aria-hidden="true" />

          {/* Validation indicator */}
          {canvas.errors.length > 0 ? (
            <span className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400 font-medium">
              <AlertCircle size={13} aria-hidden="true" /> {canvas.errors.length} error{canvas.errors.length > 1 ? 's' : ''}
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 font-medium">
              <CheckCircle size={13} aria-hidden="true" /> Valid
            </span>
          )}

          <button
            onClick={handleSave}
            disabled={saving || !canvas.isValid}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[32px] ml-2',
              canvas.isValid && !saving
                ? 'bg-primary-500 hover:bg-primary-600'
                : 'bg-gray-300 dark:bg-gray-600 cursor-not-allowed',
              saveMsg === 'success' && '!bg-green-500',
              saveMsg === 'error' && '!bg-red-500',
            )}
            aria-label={saving ? 'Saving…' : 'Save workflow'}
          >
            <Save size={12} />
            {saving ? 'Saving…' : saveMsg === 'success' ? 'Saved!' : saveMsg === 'error' ? 'Error' : 'Save'}
          </button>
        </div>
      </div>

      {/* ── Validation errors ── */}
      <ValidationBanner errors={canvas.errors} />

      {/* ── Body: template panel + canvas + properties panel ── */}
      <div className="flex flex-1 min-h-0">

        {/* ── Left: templates ── */}
        <aside
          className="w-44 shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 overflow-y-auto"
          aria-label="Node templates"
        >
          <p className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-widest text-gray-400">Templates</p>
          <div className="px-2 pb-3 space-y-1.5">
            {TEMPLATES.map(t => {
              const roleClass = ROLE_CLASSES[t.role ?? 'default']
              const Icon = t.icon
              return (
                <div
                  key={`${t.type}-${t.role ?? ''}`}
                  draggable
                  onDragStart={e => handleTemplateDragStart(e, t.type, t.role, t.label)}
                  className={clsx(
                    'flex items-center gap-2 px-2.5 py-2 rounded-lg border-2 text-xs font-medium cursor-grab active:cursor-grabbing select-none transition-shadow hover:shadow-sm',
                    t.type === 'condition'
                      ? 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:border-amber-600 dark:text-amber-200'
                      : roleClass,
                  )}
                  role="button"
                  aria-label={`Drag to add ${t.label} node`}
                  title="Drag to canvas"
                >
                  <Icon size={13} className="shrink-0 opacity-70" />
                  {t.label}
                </div>
              )
            })}

            <hr className="border-gray-200 dark:border-gray-700 my-1" />
            <p className="text-[10px] text-gray-400 px-1">
              Drag onto canvas to add. Click a port to connect nodes.
            </p>
          </div>
        </aside>

        {/* ── Canvas viewport ── */}
        <div
          ref={containerRef}
          className={clsx(
            'flex-1 overflow-auto relative bg-white dark:bg-gray-950',
            canvas.connecting && 'cursor-crosshair',
          )}
          onPointerMove={handleCanvasPointerMove}
          onPointerUp={handleCanvasPointerUp}
          onDragOver={e => e.preventDefault()}
          onDrop={handleCanvasDrop}
          onClick={handleCanvasClick}
          aria-label="Workflow canvas"
          role="application"
        >
          {/* Scroll target (gives correct scrollable area for zoom) */}
          <div style={{ width: WORLD_W * canvas.zoom, height: WORLD_H * canvas.zoom, position: 'relative' }}>
            {/* World transform layer */}
            <div
              style={{
                position: 'absolute', top: 0, left: 0,
                width: WORLD_W, height: WORLD_H,
                transform: `scale(${canvas.zoom})`,
                transformOrigin: 'top left',
              }}
            >
              {/* SVG layer: grid + edges */}
              <svg
                style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
                width={WORLD_W} height={WORLD_H}
                aria-hidden="true"
              >
                <defs>
                  <pattern id="smallgrid" width="20" height="20" patternUnits="userSpaceOnUse">
                    <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#e5e7eb" strokeWidth="0.5" className="dark:stroke-gray-800" />
                  </pattern>
                  <pattern id="biggrid" width="100" height="100" patternUnits="userSpaceOnUse">
                    <rect width="100" height="100" fill="url(#smallgrid)" />
                    <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#e5e7eb" strokeWidth="1" className="dark:stroke-gray-700" />
                  </pattern>
                  <marker id="arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#94a3b8" />
                  </marker>
                  <marker id="arrow-preview" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#3b82f6" />
                  </marker>
                </defs>

                {/* Grid */}
                <rect width="100%" height="100%" fill="url(#biggrid)" data-canvas-bg />

                {/* Edges */}
                {canvas.edges.map(edge => {
                  const src = canvas.nodes.find(n => n.id === edge.source)
                  const tgt = canvas.nodes.find(n => n.id === edge.target)
                  if (!src || !tgt) return null
                  const p1 = getOutputPort(src)
                  const p2 = getInputPort(tgt)
                  const d = bezierPath(p1.x, p1.y, p2.x, p2.y)
                  return (
                    <g key={edge.id} style={{ pointerEvents: 'all' }}>
                      <path d={d} stroke="#94a3b8" strokeWidth={2} fill="none" markerEnd="url(#arrow)" />
                      {/* Wide invisible hit area */}
                      <path
                        d={d} stroke="transparent" strokeWidth={12} fill="none"
                        style={{ cursor: 'pointer' }}
                        onClick={ev => { ev.stopPropagation(); canvas.deleteEdge(edge.id) }}
                        aria-label={`Delete edge from ${src.label} to ${tgt.label}`}
                        role="button"
                      />
                      {/* Edge label (branch) */}
                      {edge.branch && (() => {
                        const midX = (p1.x + p2.x) / 2
                        const midY = (p1.y + p2.y) / 2
                        return (
                          <text x={midX} y={midY - 6} textAnchor="middle" fontSize={9} fill="#94a3b8">
                            {edge.branch}
                          </text>
                        )
                      })()}
                    </g>
                  )
                })}

                {/* Connection preview */}
                {canvas.connecting && previewMouse && (
                  <path
                    d={bezierPath(canvas.connecting.worldX, canvas.connecting.worldY, previewMouse.x, previewMouse.y)}
                    stroke="#3b82f6" strokeWidth={2} strokeDasharray="6 3"
                    fill="none" markerEnd="url(#arrow-preview)"
                    style={{ pointerEvents: 'none' }}
                  />
                )}
              </svg>

              {/* Nodes */}
              {canvas.nodes.map(node => (
                <NodeView
                  key={node.id}
                  node={node}
                  selected={canvas.selectedId === node.id}
                  hasError={errorNodeIds.has(node.id)}
                  connecting={canvas.connecting?.sourceId === node.id}
                  onPointerDown={handleNodePointerDown}
                  onPortClick={handlePortClick}
                  onContextMenu={handleNodeContextMenu}
                />
              ))}
            </div>
          </div>

          {/* Minimap */}
          <Minimap nodes={canvas.nodes} edges={canvas.edges} containerRef={containerRef} zoom={canvas.zoom} />

          {/* Connection hint */}
          {canvas.connecting && (
            <div className="absolute top-2 left-1/2 -translate-x-1/2 bg-primary-500 text-white text-xs rounded-full px-3 py-1 shadow pointer-events-none" aria-live="assertive">
              Click a node's input port to connect — Esc to cancel
            </div>
          )}
        </div>

        {/* ── Right: properties panel ── */}
        {selectedNode && (
          <PropertiesPanel
            node={selectedNode}
            onUpdate={(id, updates) => { canvas.updateNode(id, updates); setEditingNode(id) }}
            onDelete={canvas.deleteNode}
          />
        )}
      </div>

      {/* Context menu */}
      {canvas.contextMenu && (
        <ContextMenu
          x={canvas.contextMenu.screenX}
          y={canvas.contextMenu.screenY}
          nodeId={canvas.contextMenu.nodeId}
          onEdit={() => {
            canvas.setSelectedId(canvas.contextMenu!.nodeId)
            setEditingNode(canvas.contextMenu!.nodeId)
          }}
          onDuplicate={() => canvas.duplicateNode(canvas.contextMenu!.nodeId)}
          onInsertCondition={() => canvas.insertConditionAfter(canvas.contextMenu!.nodeId)}
          onDelete={() => canvas.deleteNode(canvas.contextMenu!.nodeId)}
          onClose={() => canvas.setContextMenu(null)}
        />
      )}
    </div>
  )
}
