/**
 * Tests for context/AppContext.tsx
 * Covers: initial state, dispatch actions, convenience hooks, notify helper.
 */

import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { type ReactNode } from 'react'
import { AppProvider, useAppContext, useNotifications } from '../context/AppContext'

function wrapper({ children }: { children: ReactNode }) {
  return <AppProvider>{children}</AppProvider>
}

// ── Initial state ─────────────────────────────────────────────────────────────

describe('AppContext initial state', () => {
  it('has null user by default', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    expect(result.current.state.user).toBeNull()
  })

  it('has null selectedWorkflow by default', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    expect(result.current.state.selectedWorkflow).toBeNull()
  })

  it('has empty notifications by default', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    expect(result.current.state.notifications).toHaveLength(0)
  })

  it('unreadCount is 0 initially', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    expect(result.current.unreadCount).toBe(0)
  })
})

// ── SET_USER ──────────────────────────────────────────────────────────────────

describe('SET_USER action', () => {
  it('sets user', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({
        type: 'SET_USER',
        payload: { id: 'u1', email: 'test@test.com', role: 'admin' },
      })
    })
    expect(result.current.state.user?.email).toBe('test@test.com')
  })

  it('clears user when payload is null', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({ type: 'SET_USER', payload: { id: 'u1', email: 'x@x.com', role: 'viewer' } })
    })
    act(() => {
      result.current.dispatch({ type: 'SET_USER', payload: null })
    })
    expect(result.current.state.user).toBeNull()
  })
})

// ── Notifications ─────────────────────────────────────────────────────────────

describe('Notification actions', () => {
  it('ADD_NOTIFICATION adds to list', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({
        type: 'ADD_NOTIFICATION',
        payload: { type: 'success', title: 'Done', message: 'Workflow created' },
      })
    })
    expect(result.current.state.notifications).toHaveLength(1)
    expect(result.current.state.notifications[0].title).toBe('Done')
    expect(result.current.state.notifications[0].read).toBe(false)
  })

  it('notify helper adds notification', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.notify('error', 'Oops', 'Something went wrong')
    })
    expect(result.current.state.notifications[0].type).toBe('error')
    expect(result.current.state.notifications[0].title).toBe('Oops')
  })

  it('unreadCount reflects unread count', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => { result.current.notify('info', 'A') })
    act(() => { result.current.notify('info', 'B') })
    expect(result.current.unreadCount).toBe(2)
  })

  it('MARK_NOTIFICATION_READ marks single notification', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => { result.current.notify('success', 'Test') })
    const id = result.current.state.notifications[0].id
    act(() => {
      result.current.dispatch({ type: 'MARK_NOTIFICATION_READ', payload: id })
    })
    expect(result.current.state.notifications[0].read).toBe(true)
    expect(result.current.unreadCount).toBe(0)
  })

  it('CLEAR_NOTIFICATIONS removes all', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => { result.current.notify('info', 'A') })
    act(() => { result.current.notify('info', 'B') })
    act(() => { result.current.dispatch({ type: 'CLEAR_NOTIFICATIONS' }) })
    expect(result.current.state.notifications).toHaveLength(0)
  })

  it('caps notifications at 50', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      for (let i = 0; i < 60; i++) {
        result.current.notify('info', `Notification ${i}`)
      }
    })
    expect(result.current.state.notifications).toHaveLength(50)
  })
})

// ── useNotifications hook ─────────────────────────────────────────────────────

describe('useNotifications', () => {
  it('markRead works', () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    act(() => { result.current.notify('success', 'Done') })
    const id = result.current.notifications[0].id
    act(() => { result.current.markRead(id) })
    expect(result.current.notifications[0].read).toBe(true)
  })

  it('clearAll works', () => {
    const { result } = renderHook(() => useNotifications(), { wrapper })
    act(() => { result.current.notify('info', 'X') })
    act(() => { result.current.clearAll() })
    expect(result.current.notifications).toHaveLength(0)
  })
})

// ── SET_EXECUTION ─────────────────────────────────────────────────────────────

describe('Execution actions', () => {
  const mockExecution = {
    id: 'exec-1',
    workflow_id: 'wf-1',
    status: 'running' as const,
    started_at: new Date().toISOString(),
    completed_at: null,
    result: null,
    error_log: null,
  }

  it('SET_EXECUTION sets current execution', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({ type: 'SET_EXECUTION', payload: mockExecution })
    })
    expect(result.current.state.currentExecution?.id).toBe('exec-1')
  })

  it('UPDATE_EXECUTION patches current execution', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({ type: 'SET_EXECUTION', payload: mockExecution })
    })
    act(() => {
      result.current.dispatch({
        type: 'UPDATE_EXECUTION',
        payload: { status: 'completed', completed_at: new Date().toISOString() },
      })
    })
    expect(result.current.state.currentExecution?.status).toBe('completed')
    expect(result.current.state.currentExecution?.id).toBe('exec-1') // unchanged
  })

  it('UPDATE_EXECUTION is no-op when no execution set', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    act(() => {
      result.current.dispatch({ type: 'UPDATE_EXECUTION', payload: { status: 'completed' } })
    })
    expect(result.current.state.currentExecution).toBeNull()
  })
})

// ── Error: missing provider ───────────────────────────────────────────────────

describe('useAppContext error', () => {
  it('throws when used outside AppProvider', () => {
    // Suppress expected console.error from React
    const consoleError = console.error
    console.error = () => {}
    expect(() => {
      renderHook(() => useAppContext())
    }).toThrow('useAppContext must be used inside <AppProvider>')
    console.error = consoleError
  })
})
