import { useState, useCallback, useEffect } from 'react'
import type { CanvasNode, CanvasEdge, ValidationError } from '../types'

function uid(): string {
  return Math.random().toString(36).slice(2, 9)
}

// ─── Validation ───────────────────────────────────────────────────────────────

function buildAdj(nodes: CanvasNode[], edges: CanvasEdge[]): Map<string, string[]> {
  const adj = new Map<string, string[]>()
  nodes.forEach(n => adj.set(n.id, []))
  edges.forEach(e => adj.get(e.source)?.push(e.target))
  return adj
}

function detectCycles(nodes: CanvasNode[], edges: CanvasEdge[]): Array<string[]> {
  const adj = buildAdj(nodes, edges)
  const visited = new Set<string>()
  const recStack = new Set<string>()
  const cycles: Array<string[]> = []
  const path: string[] = []

  function dfs(id: string): void {
    visited.add(id)
    recStack.add(id)
    path.push(id)
    for (const neighbor of adj.get(id) ?? []) {
      if (!visited.has(neighbor)) {
        dfs(neighbor)
      } else if (recStack.has(neighbor)) {
        const start = path.indexOf(neighbor)
        cycles.push([...path.slice(start), neighbor])
      }
    }
    path.pop()
    recStack.delete(id)
  }

  nodes.forEach(n => { if (!visited.has(n.id)) dfs(n.id) })
  return cycles
}

function findOrphans(nodes: CanvasNode[], edges: CanvasEdge[]): string[] {
  const startNode = nodes.find(n => n.type === 'start')
  if (!startNode) return nodes.filter(n => n.type !== 'start').map(n => n.id)

  const adj = buildAdj(nodes, edges)
  const reachable = new Set<string>()
  const queue = [startNode.id]

  while (queue.length > 0) {
    const id = queue.shift()!
    if (reachable.has(id)) continue
    reachable.add(id)
    for (const neighbor of adj.get(id) ?? []) queue.push(neighbor)
  }

  return nodes.filter(n => !reachable.has(n.id) && n.type !== 'start').map(n => n.id)
}

export function validateGraph(nodes: CanvasNode[], edges: CanvasEdge[]): ValidationError[] {
  const errors: ValidationError[] = []

  // Cycles
  detectCycles(nodes, edges).forEach(cycle => {
    const labels = cycle.map(id => nodes.find(n => n.id === id)?.label ?? id)
    errors.push({ type: 'cycle', message: `Cycle: ${labels.join(' → ')}`, nodeIds: cycle })
  })

  // Orphans
  const orphanIds = findOrphans(nodes, edges)
  if (orphanIds.length > 0) {
    const labels = orphanIds.map(id => nodes.find(n => n.id === id)?.label ?? id)
    errors.push({
      type: 'orphan',
      message: `No path from Start: ${labels.join(', ')}`,
      nodeIds: orphanIds,
    })
  }

  // Missing outputs (agent/condition with no outgoing edges)
  const sources = new Set(edges.map(e => e.source))
  nodes
    .filter(n => (n.type === 'agent' || n.type === 'condition') && !sources.has(n.id))
    .forEach(n => {
      errors.push({ type: 'missing_output', message: `"${n.label}" has no outgoing connection`, nodeIds: [n.id] })
    })

  return errors
}

// ─── Default canvas state ─────────────────────────────────────────────────────

const STORAGE_PREFIX = 'workflow_canvas_'

export const WORLD_W = 2400
export const WORLD_H = 1600

const DEFAULT_NODES: CanvasNode[] = [
  { id: 'start', type: 'start', label: 'Start', x: 100, y: 240 },
  { id: 'end',   type: 'end',   label: 'End',   x: 700, y: 240 },
]

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ConnectingState {
  sourceId: string
  worldX: number
  worldY: number
}

export interface ContextMenuState {
  screenX: number
  screenY: number
  nodeId: string
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useCanvas(workflowId = 'default') {
  const key = `${STORAGE_PREFIX}${workflowId}`

  const load = (): { nodes: CanvasNode[]; edges: CanvasEdge[]; zoom: number } => {
    try {
      const raw = localStorage.getItem(key)
      if (raw) return JSON.parse(raw) as { nodes: CanvasNode[]; edges: CanvasEdge[]; zoom: number }
    } catch { /* ignore */ }
    return { nodes: DEFAULT_NODES, edges: [], zoom: 1 }
  }

  const initial = load()

  const [nodes, setNodes] = useState<CanvasNode[]>(initial.nodes)
  const [edges, setEdges] = useState<CanvasEdge[]>(initial.edges)
  const [zoom, setZoomRaw] = useState(initial.zoom)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [connecting, setConnecting] = useState<ConnectingState | null>(null)
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [errors, setErrors] = useState<ValidationError[]>([])
  const [isDirty, setIsDirty] = useState(false)

  // Validate whenever graph changes
  useEffect(() => {
    setErrors(validateGraph(nodes, edges))
  }, [nodes, edges])

  // Auto-save every 10 s when dirty
  useEffect(() => {
    if (!isDirty) return
    const t = setTimeout(() => {
      localStorage.setItem(key, JSON.stringify({ nodes, edges, zoom }))
      setIsDirty(false)
    }, 10_000)
    return () => clearTimeout(t)
  }, [isDirty, nodes, edges, zoom, key])

  // ── Node ops ────────────────────────────────────────────────────────────────

  const addNode = useCallback((
    type: CanvasNode['type'],
    x: number,
    y: number,
    label?: string,
    role?: CanvasNode['role'],
  ): string => {
    const id = uid()
    const defaultLabel = type === 'agent' ? 'New Agent' : type === 'condition' ? 'Condition' : type
    setNodes(prev => [...prev, { id, type, label: label ?? defaultLabel, x, y, role }])
    setSelectedId(id)
    setIsDirty(true)
    return id
  }, [])

  const updateNode = useCallback((id: string, updates: Partial<CanvasNode>) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, ...updates } : n))
    setIsDirty(true)
  }, [])

  const deleteNode = useCallback((id: string) => {
    if (id === 'start' || id === 'end') return
    setNodes(prev => prev.filter(n => n.id !== id))
    setEdges(prev => prev.filter(e => e.source !== id && e.target !== id))
    setSelectedId(prev => prev === id ? null : prev)
    setIsDirty(true)
  }, [])

  const duplicateNode = useCallback((id: string) => {
    setNodes(prev => {
      const node = prev.find(n => n.id === id)
      if (!node || node.type === 'start' || node.type === 'end') return prev
      const copy: CanvasNode = { ...node, id: uid(), x: node.x + 40, y: node.y + 40 }
      setSelectedId(copy.id)
      return [...prev, copy]
    })
    setIsDirty(true)
  }, [])

  const insertConditionAfter = useCallback((nodeId: string) => {
    setNodes(prev => {
      const node = prev.find(n => n.id === nodeId)
      if (!node) return prev
      const condId = uid()
      const cond: CanvasNode = { id: condId, type: 'condition', label: 'Condition', x: node.x + 220, y: node.y }
      setEdges(prevEdges => {
        const outgoing = prevEdges.filter(e => e.source === nodeId)
        const rest = prevEdges.filter(e => e.source !== nodeId)
        return [
          ...rest,
          { id: uid(), source: nodeId, target: condId },
          ...outgoing.map(e => ({ ...e, id: uid(), source: condId })),
        ]
      })
      setSelectedId(condId)
      setIsDirty(true)
      return [...prev, cond]
    })
  }, [])

  // ── Edge ops ────────────────────────────────────────────────────────────────

  const addEdge = useCallback((source: string, target: string, branch?: 'true' | 'false') => {
    if (source === target) return
    setEdges(prev => {
      if (prev.some(e => e.source === source && e.target === target)) return prev
      return [...prev, { id: uid(), source, target, branch }]
    })
    setIsDirty(true)
  }, [])

  const deleteEdge = useCallback((id: string) => {
    setEdges(prev => prev.filter(e => e.id !== id))
    setIsDirty(true)
  }, [])

  // ── Canvas ops ──────────────────────────────────────────────────────────────

  const setZoom = useCallback((z: number) => {
    setZoomRaw(Math.max(0.5, Math.min(2, z)))
  }, [])

  const clearCanvas = useCallback(() => {
    setNodes(DEFAULT_NODES)
    setEdges([])
    setSelectedId(null)
    setIsDirty(true)
  }, [])

  const saveNow = useCallback(() => {
    localStorage.setItem(key, JSON.stringify({ nodes, edges, zoom }))
    setIsDirty(false)
  }, [key, nodes, edges, zoom])

  return {
    nodes, edges, zoom, selectedId, connecting, contextMenu, errors, isDirty,
    addNode, updateNode, deleteNode, duplicateNode, insertConditionAfter,
    addEdge, deleteEdge,
    setZoom, clearCanvas, saveNow,
    setSelectedId,
    setConnecting,
    setContextMenu,
    WORLD_W, WORLD_H,
    isValid: errors.length === 0,
  }
}

export type UseCanvasReturn = ReturnType<typeof useCanvas>
