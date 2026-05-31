/**
 * useExecutionMonitor — real-time execution monitoring
 *
 * Strategy:
 *   1. Load initial execution state from REST API
 *   2. Open WebSocket to /ws/executions/{id} for live node updates
 *   3. Fall back to polling GET /executions/{id} every 2s if WS fails
 *   4. Accumulate log entries from WSMessage events
 *   5. Close/cleanup on unmount or when execution reaches a terminal state
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { executionsApi, type BackendExecution, type BackendExecutionStep } from '../api/executions'
import { useWebSocket } from './useWebSocket'
import type { WSMessage, ExecutionNodeStatus, LogEntry } from '../types'
import { getErrorMessage } from '../api/client'

export type MonitorStatus = 'loading' | 'running' | 'completed' | 'failed' | 'error'

const TERMINAL: Set<string> = new Set(['completed', 'failed', 'halted', 'stopped'])
const POLL_INTERVAL_MS = 2500

export interface ExecutionMonitorState {
  execution: BackendExecution | null
  steps: BackendExecutionStep[]
  nodeStatuses: Map<string, ExecutionNodeStatus>
  logs: LogEntry[]
  monitorStatus: MonitorStatus
  wsStatus: string
  loading: boolean
  error: string | null
}

export function useExecutionMonitor(executionId: string | undefined) {
  const [execution, setExecution] = useState<BackendExecution | null>(null)
  const [steps, setSteps] = useState<BackendExecutionStep[]>([])
  const [nodeStatuses, setNodeStatuses] = useState<Map<string, ExecutionNodeStatus>>(new Map())
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus>('loading')

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isTerminalRef = useRef(false)

  // ── Initial load ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!executionId) return
    setLoading(true)
    setError(null)
    executionsApi.get(executionId).then(exec => {
      setExecution(exec)
      setSteps(exec.steps ?? [])
      const terminalNow = TERMINAL.has(exec.status)
      isTerminalRef.current = terminalNow
      setMonitorStatus(
        terminalNow
          ? exec.status === 'completed' ? 'completed' : 'failed'
          : 'running'
      )
    }).catch(err => {
      setError(getErrorMessage(err))
      setMonitorStatus('error')
    }).finally(() => {
      setLoading(false)
    })
  }, [executionId])

  // ── WebSocket message handler ────────────────────────────────────────────────
  const handleMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'node_status' && msg.nodeStatus) {
      setNodeStatuses(prev => {
        const next = new Map(prev)
        next.set(msg.nodeStatus!.nodeId, msg.nodeStatus!)
        return next
      })
    }

    if (msg.type === 'log' && msg.log) {
      setLogs(prev => [...prev, msg.log!].slice(-500))
    }

    if (msg.type === 'execution_complete') {
      isTerminalRef.current = true
      setExecution(prev => prev ? { ...prev, status: 'completed' } : prev)
      setMonitorStatus('completed')
    }

    if (msg.type === 'execution_error') {
      isTerminalRef.current = true
      setExecution(prev => prev ? { ...prev, status: 'failed', error_log: msg.error } : prev)
      setMonitorStatus('failed')
    }
  }, [])

  // ── WebSocket connection ─────────────────────────────────────────────────────
  const wsUrl = executionId && !isTerminalRef.current
    ? executionsApi.wsUrl(executionId)
    : null

  const { status: wsStatus } = useWebSocket(wsUrl, {
    onMessage: handleMessage,
    maxReconnects: 5,
    reconnectDelay: 1500,
    pollUrl: executionId ? `/api/v1/executions/${executionId}` : undefined,
  })

  // ── Polling fallback ─────────────────────────────────────────────────────────
  const startPolling = useCallback(() => {
    if (!executionId || pollTimerRef.current) return
    pollTimerRef.current = setInterval(async () => {
      if (isTerminalRef.current) {
        clearInterval(pollTimerRef.current!)
        pollTimerRef.current = null
        return
      }
      try {
        const exec = await executionsApi.get(executionId)
        setExecution(exec)
        setSteps(exec.steps ?? [])
        if (TERMINAL.has(exec.status)) {
          isTerminalRef.current = true
          setMonitorStatus(exec.status === 'completed' ? 'completed' : 'failed')
          clearInterval(pollTimerRef.current!)
          pollTimerRef.current = null
        }
      } catch { /* silent */ }
    }, POLL_INTERVAL_MS)
  }, [executionId])

  // Start polling when WS is unavailable
  useEffect(() => {
    if (wsStatus === 'unavailable') startPolling()
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [wsStatus, startPolling])

  const addLog = useCallback((entry: Omit<LogEntry, 'id' | 'timestamp'>) => {
    setLogs(prev => [
      ...prev,
      { ...entry, id: `log-${Date.now()}`, timestamp: new Date().toISOString() },
    ].slice(-500))
  }, [])

  return {
    execution,
    steps,
    nodeStatuses,
    logs,
    monitorStatus,
    wsStatus,
    loading,
    error,
    addLog,
    isTerminal: isTerminalRef.current,
  }
}
