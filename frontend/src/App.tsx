import { Suspense, lazy, useState, useEffect, useCallback, useRef } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster, toast } from 'react-hot-toast'
import clsx from 'clsx'
import type { RateLimitExceededDetail } from './api/client'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import ProtectedRoute from './components/ProtectedRoute'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AppProvider } from './context/AppContext'
import { AuthProvider, useAuth } from './context/AuthContext'
import { setTokenAccessor } from './hooks/useAPI'
import type { Theme } from './types'

const Dashboard       = lazy(() => import('./pages/Dashboard'))
const Agents          = lazy(() => import('./pages/Agents'))
const Workflows       = lazy(() => import('./pages/Workflows'))
const Executions      = lazy(() => import('./pages/Executions'))
const ExecutionDetail = lazy(() => import('./pages/ExecutionDetail'))
const Templates       = lazy(() => import('./pages/Templates'))
const Settings        = lazy(() => import('./pages/Settings'))
const Login           = lazy(() => import('./pages/Login'))
const Register        = lazy(() => import('./pages/Register'))

function PageSkeleton() {
  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" aria-busy="true">
      <div className="h-8 w-48 rounded-lg bg-gray-200 dark:bg-gray-700 animate-pulse" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-gray-200 dark:bg-gray-700 animate-pulse" />
        ))}
      </div>
      <div className="h-64 rounded-xl bg-gray-200 dark:bg-gray-700 animate-pulse" />
    </div>
  )
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem('theme') as Theme | null
    if (stored) return stored
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggle = useCallback(() => setTheme(t => t === 'dark' ? 'light' : 'dark'), [])
  return { theme, toggle }
}

// Connects the API client's token accessor to the AuthContext
function TokenBridge() {
  const { getToken } = useAuth()
  useEffect(() => { setTokenAccessor(getToken) }, [getToken])
  return null
}

function AppShell() {
  const { theme, toggle } = useTheme()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileMenuOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // On auth:expired redirect to login
  useEffect(() => {
    const handler = () => {
      window.location.href = '/login'
    }
    window.addEventListener('auth:expired', handler)
    return () => window.removeEventListener('auth:expired', handler)
  }, [])

  // On ratelimit:exceeded — show toast with countdown, re-enable after window
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [rateLimitActive, setRateLimitActive] = useState(false)
  const [rateLimitSecondsLeft, setRateLimitSecondsLeft] = useState(0)

  useEffect(() => {
    const handler = (e: Event) => {
      const { retryAfter } = (e as CustomEvent<RateLimitExceededDetail>).detail
      const seconds = Math.max(1, retryAfter)

      setRateLimitActive(true)
      setRateLimitSecondsLeft(seconds)

      // Show initial toast
      toast.error(`Too many requests. Please wait ${seconds} second${seconds !== 1 ? 's' : ''}.`, {
        duration: Math.min(seconds * 1000, 10_000),
        id: 'rate-limit',
      })

      // Clear any existing countdown
      if (countdownRef.current) clearInterval(countdownRef.current)

      let remaining = seconds
      countdownRef.current = setInterval(() => {
        remaining -= 1
        setRateLimitSecondsLeft(remaining)
        if (remaining <= 0) {
          if (countdownRef.current) clearInterval(countdownRef.current)
          setRateLimitActive(false)
          setRateLimitSecondsLeft(0)
        }
      }, 1000)
    }

    window.addEventListener('ratelimit:exceeded', handler)
    return () => {
      window.removeEventListener('ratelimit:exceeded', handler)
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [])

  return (
    <div className={clsx('flex h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-white overflow-hidden')}>
      {/* Rate-limit banner — sits above all content when active */}
      {rateLimitActive && (
        <div
          role="alert"
          aria-live="polite"
          className="fixed top-0 inset-x-0 z-50 flex items-center justify-center gap-2 bg-amber-500 text-white text-sm font-medium py-2 px-4"
        >
          <span>Too many requests — please wait</span>
          <span className="tabular-nums font-bold">{rateLimitSecondsLeft}s</span>
          <span>before retrying.</span>
        </div>
      )}

      {/* Public routes — no shell chrome */}
      <Routes>
        <Route path="/login"    element={<Suspense fallback={<PageSkeleton />}><Login /></Suspense>} />
        <Route path="/register" element={<Suspense fallback={<PageSkeleton />}><Register /></Suspense>} />

        {/* Protected routes — full shell */}
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <>
                <Sidebar mobileOpen={mobileMenuOpen} onMobileClose={() => setMobileMenuOpen(false)} />
                <div className="flex flex-col flex-1 min-w-0 md:ml-64 transition-all duration-300">
                  <Header
                    theme={theme}
                    onThemeToggle={toggle}
                    onMobileMenuToggle={() => setMobileMenuOpen(v => !v)}
                  />
                  <div className="flex-1 overflow-y-auto flex flex-col">
                    <ErrorBoundary>
                      <Suspense fallback={<PageSkeleton />}>
                        <Routes>
                          <Route path="/"               element={<Dashboard />} />
                          <Route path="/agents"         element={<Agents />} />
                          <Route path="/agents/:id"     element={<Agents />} />
                          <Route path="/workflows"      element={<Workflows />} />
                          <Route path="/workflows/:id"  element={<Workflows />} />
                          <Route path="/executions"     element={<Executions />} />
                          <Route path="/executions/:id" element={<ExecutionDetail />} />
                          <Route path="/templates"      element={<Templates />} />
                          <Route path="/settings"       element={<Settings />} />
                          <Route path="*"               element={<Navigate to="/" replace />} />
                        </Routes>
                      </Suspense>
                    </ErrorBoundary>
                  </div>
                </div>
              </>
            </ProtectedRoute>
          }
        />
      </Routes>

      <Toaster
        position="top-right"
        toastOptions={{
          duration: 3000,
          style: {
            background: theme === 'dark' ? '#1f2937' : '#fff',
            color: theme === 'dark' ? '#f9fafb' : '#111827',
            border: '1px solid',
            borderColor: theme === 'dark' ? '#374151' : '#e5e7eb',
            fontSize: '14px',
          },
          success: { duration: 3000, iconTheme: { primary: '#10b981', secondary: '#fff' } },
          error:   { duration: 5000, iconTheme: { primary: '#ef4444', secondary: '#fff' } },
        }}
      />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <TokenBridge />
        <AppProvider>
          <AppShell />
        </AppProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
