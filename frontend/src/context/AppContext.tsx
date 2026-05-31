/**
 * AppContext — global application state via Context + useReducer
 *
 * Holds:
 *  • currentExecution  — the execution being actively monitored
 *  • selectedWorkflow  — workflow selected on the canvas
 *  • notifications     — in-app notification queue
 *  • user              — authenticated user (stub for Phase 4 JWT)
 *
 * Usage:
 *   const { state, dispatch } = useAppContext()
 *   dispatch({ type: 'SET_EXECUTION', payload: execution })
 */

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  type ReactNode,
} from 'react'
import type { BackendExecution } from '../api/executions'
import type { BackendWorkflow } from '../api/workflows'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AppNotification {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message?: string
  timestamp: string
  read: boolean
}

export interface AppUser {
  id: string
  email: string
  role: 'admin' | 'operator' | 'viewer'
}

export interface AppState {
  user: AppUser | null
  selectedWorkflow: BackendWorkflow | null
  currentExecution: BackendExecution | null
  notifications: AppNotification[]
  sidebarCollapsed: boolean
}

type AppAction =
  | { type: 'SET_USER'; payload: AppUser | null }
  | { type: 'SET_WORKFLOW'; payload: BackendWorkflow | null }
  | { type: 'SET_EXECUTION'; payload: BackendExecution | null }
  | { type: 'UPDATE_EXECUTION'; payload: Partial<BackendExecution> }
  | { type: 'ADD_NOTIFICATION'; payload: Omit<AppNotification, 'id' | 'timestamp' | 'read'> }
  | { type: 'MARK_NOTIFICATION_READ'; payload: string }
  | { type: 'CLEAR_NOTIFICATIONS' }
  | { type: 'TOGGLE_SIDEBAR' }

// ── Initial state ─────────────────────────────────────────────────────────────

const INITIAL_STATE: AppState = {
  user: null,
  selectedWorkflow: null,
  currentExecution: null,
  notifications: [],
  sidebarCollapsed: false,
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_USER':
      return { ...state, user: action.payload }

    case 'SET_WORKFLOW':
      return { ...state, selectedWorkflow: action.payload }

    case 'SET_EXECUTION':
      return { ...state, currentExecution: action.payload }

    case 'UPDATE_EXECUTION':
      if (!state.currentExecution) return state
      return {
        ...state,
        currentExecution: { ...state.currentExecution, ...action.payload },
      }

    case 'ADD_NOTIFICATION': {
      const notification: AppNotification = {
        id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        timestamp: new Date().toISOString(),
        read: false,
        ...action.payload,
      }
      return {
        ...state,
        notifications: [notification, ...state.notifications].slice(0, 50),
      }
    }

    case 'MARK_NOTIFICATION_READ':
      return {
        ...state,
        notifications: state.notifications.map(n =>
          n.id === action.payload ? { ...n, read: true } : n
        ),
      }

    case 'CLEAR_NOTIFICATIONS':
      return { ...state, notifications: [] }

    case 'TOGGLE_SIDEBAR':
      return { ...state, sidebarCollapsed: !state.sidebarCollapsed }

    default:
      return state
  }
}

// ── Context ───────────────────────────────────────────────────────────────────

interface AppContextValue {
  state: AppState
  dispatch: React.Dispatch<AppAction>
  /** Shortcut: add an info notification */
  notify: (type: AppNotification['type'], title: string, message?: string) => void
  /** Unread notification count */
  unreadCount: number
}

const AppContext = createContext<AppContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE)

  const notify = useCallback(
    (type: AppNotification['type'], title: string, message?: string) => {
      dispatch({ type: 'ADD_NOTIFICATION', payload: { type, title, message } })
    },
    []
  )

  const unreadCount = state.notifications.filter(n => !n.read).length

  return (
    <AppContext.Provider value={{ state, dispatch, notify, unreadCount }}>
      {children}
    </AppContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppContext must be used inside <AppProvider>')
  return ctx
}

/** Convenience hook — only subscribes to the user slice. */
export function useCurrentUser(): AppUser | null {
  return useAppContext().state.user
}

/** Convenience hook — current execution being monitored. */
export function useCurrentExecution(): BackendExecution | null {
  return useAppContext().state.currentExecution
}

/** Convenience hook — notifications + helpers. */
export function useNotifications() {
  const { state, dispatch, notify, unreadCount } = useAppContext()
  const markRead = useCallback(
    (id: string) => dispatch({ type: 'MARK_NOTIFICATION_READ', payload: id }),
    [dispatch]
  )
  const clearAll = useCallback(
    () => dispatch({ type: 'CLEAR_NOTIFICATIONS' }),
    [dispatch]
  )
  return { notifications: state.notifications, unreadCount, notify, markRead, clearAll }
}
