import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

interface AuthUser {
  id: string
  email: string
  role: string
}

interface AuthState {
  user: AuthUser | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<AuthUser>
  logout: () => Promise<void>
  getToken: () => string | null
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function parseJwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

// ── Context ────────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    isAuthenticated: false,
    isLoading: true,  // true on mount while we attempt silent refresh
  })

  // Keep a ref so timer callbacks always read the latest token
  const tokenRef = useRef<string | null>(null)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearRefreshTimer = () => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
  }

  // Schedule auto-refresh 5 minutes before expiry
  const scheduleRefresh = useCallback((token: string) => {
    clearRefreshTimer()
    const exp = parseJwtExp(token)
    if (!exp) return
    const msUntilExpiry = exp * 1000 - Date.now()
    const refreshIn = msUntilExpiry - 5 * 60 * 1000  // 5 min before
    if (refreshIn <= 0) {
      // Already within 5 min window — refresh immediately
      silentRefresh()
      return
    }
    refreshTimerRef.current = setTimeout(() => silentRefresh(), refreshIn)
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const setAuth = useCallback((token: string, user: AuthUser) => {
    tokenRef.current = token
    setState({ user, accessToken: token, isAuthenticated: true, isLoading: false })
    scheduleRefresh(token)
  }, [scheduleRefresh])

  const clearAuth = useCallback(() => {
    tokenRef.current = null
    clearRefreshTimer()
    setState({ user: null, accessToken: null, isAuthenticated: false, isLoading: false })
  }, [])

  // Silent token refresh using httpOnly cookie (sent automatically by browser)
  const silentRefresh = useCallback(async () => {
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',  // sends refresh_token cookie
        headers: { 'Content-Type': 'application/json' },
      })
      if (!res.ok) {
        clearAuth()
        return
      }
      const data = await res.json()
      const newToken: string = data.access_token

      // Decode user from JWT payload (no second request needed)
      const payload = JSON.parse(atob(newToken.split('.')[1]))
      const user: AuthUser = { id: payload.user_id, email: payload.email, role: payload.role }
      setAuth(newToken, user)
    } catch {
      clearAuth()
    }
  }, [clearAuth, setAuth])

  // On mount: attempt silent refresh to restore session
  useEffect(() => {
    silentRefresh()
    return () => clearRefreshTimer()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Public API ─────────────────────────────────────────────────────────────

  const login = useCallback(async (email: string, password: string) => {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err?.error?.message ?? 'Login failed')
    }

    const data = await res.json()
    setAuth(data.access_token, data.user)
  }, [setAuth])

  const register = useCallback(async (email: string, password: string): Promise<AuthUser> => {
    const res = await fetch(`${BASE_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err?.error?.message ?? 'Registration failed')
    }

    return res.json()
  }, [])

  const logout = useCallback(async () => {
    try {
      await fetch(`${BASE_URL}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      })
    } finally {
      clearAuth()
    }
  }, [clearAuth])

  const getToken = useCallback(() => tokenRef.current, [])

  return (
    <AuthContext.Provider value={{ ...state, login, register, logout, getToken }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
