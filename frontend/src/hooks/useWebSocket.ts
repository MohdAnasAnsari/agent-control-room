import { useState, useEffect, useRef, useCallback } from 'react'
import type { WSMessage } from '../types'

export type WSStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error' | 'unavailable'

interface Options {
  /** ms before first reconnect attempt (doubles each try) */
  reconnectDelay?: number
  maxReconnects?: number
  onMessage?: (msg: WSMessage) => void
  onOpen?: () => void
  onClose?: () => void
  /** Polling URL used when WS is unavailable */
  pollUrl?: string
  pollInterval?: number
}

export function useWebSocket(url: string | null, options: Options = {}) {
  const {
    reconnectDelay = 1500,
    maxReconnects = 5,
    onMessage,
    onOpen,
    onClose,
    pollUrl,
    pollInterval = 2000,
  } = options

  const [status, setStatus] = useState<WSStatus>('idle')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectCount = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const usePoll = useRef(false)

  const stopPoll = useCallback(() => {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
  }, [])

  const startPoll = useCallback(() => {
    if (!pollUrl || pollTimer.current) return
    setStatus('connected')
    pollTimer.current = setInterval(async () => {
      try {
        const res = await fetch(pollUrl)
        if (!res.ok) return
        const msgs: WSMessage[] = await res.json()
        msgs.forEach(m => onMessage?.(m))
      } catch { /* ignore */ }
    }, pollInterval)
  }, [pollUrl, pollInterval, onMessage])

  const connect = useCallback(() => {
    if (!url || usePoll.current) return
    setStatus('connecting')

    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch {
      usePoll.current = true
      setStatus('unavailable')
      startPoll()
      return
    }

    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      reconnectCount.current = 0
      onOpen?.()
    }

    ws.onmessage = evt => {
      try {
        const data = JSON.parse(typeof evt.data === 'string' ? evt.data : '') as WSMessage
        onMessage?.(data)
      } catch { /* malformed frame */ }
    }

    ws.onclose = evt => {
      setStatus('disconnected')
      onClose?.()
      // Normal close (1000) or forced stop — don't reconnect
      if (evt.code === 1000) return
      if (reconnectCount.current < maxReconnects) {
        reconnectCount.current++
        const delay = reconnectDelay * 2 ** (reconnectCount.current - 1)
        reconnectTimer.current = setTimeout(connect, delay)
      } else {
        // WS unavailable — fall back to polling
        usePoll.current = true
        setStatus('unavailable')
        startPoll()
      }
    }

    ws.onerror = () => {
      setStatus('error')
      ws.close()
    }
  }, [url, reconnectDelay, maxReconnects, onMessage, onOpen, onClose, startPoll])

  useEffect(() => {
    if (url) connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      stopPoll()
      wsRef.current?.close(1000)
    }
  }, [url]) // eslint-disable-line react-hooks/exhaustive-deps

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    stopPoll()
    wsRef.current?.close(1000)
    setStatus('disconnected')
  }, [stopPoll])

  const reconnect = useCallback(() => {
    usePoll.current = false
    reconnectCount.current = 0
    disconnect()
    setTimeout(connect, 100)
  }, [disconnect, connect])

  return { status, send, disconnect, reconnect }
}
