/**
 * ErrorBoundary — catches render errors and shows a fallback UI.
 * Reports errors to Sentry when VITE_SENTRY_DSN is configured.
 * Use at page or section level, not around every component.
 */

import { Component, type ReactNode } from 'react'
import { RefreshCw, AlertTriangle } from 'lucide-react'
import { Sentry } from '../instrument'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  onReset?: () => void
}

interface State {
  hasError: boolean
  error: Error | null
  eventId: string | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null, eventId: null }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[ErrorBoundary] Render error:', error, info.componentStack)

    // Report to Sentry with component stack as extra context
    const eventId = Sentry.captureException(error, {
      extra: { componentStack: info.componentStack },
    })
    this.setState({ eventId: eventId ?? null })
  }

  reset = () => {
    this.setState({ hasError: false, error: null, eventId: null })
    this.props.onReset?.()
  }

  render() {
    if (!this.state.hasError) return this.props.children

    if (this.props.fallback) return this.props.fallback

    return (
      <div
        role="alert"
        className="flex flex-col items-center justify-center min-h-[300px] p-8 text-center space-y-4"
      >
        <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
          <AlertTriangle className="text-red-500" size={24} />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Something went wrong
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-sm">
            {this.state.error?.message ?? 'An unexpected error occurred'}
          </p>
          {this.state.eventId && (
            <p className="text-xs text-gray-400 dark:text-gray-600 mt-2 font-mono">
              Error ID: {this.state.eventId}
            </p>
          )}
        </div>
        <div className="flex gap-3">
          <button
            onClick={this.reset}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg
                       bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700
                       text-gray-700 dark:text-gray-200 transition-colors"
          >
            <RefreshCw size={14} />
            Try again
          </button>
          {this.state.eventId && (
            <button
              onClick={() =>
                Sentry.showReportDialog({ eventId: this.state.eventId! })
              }
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg
                         bg-red-50 hover:bg-red-100 dark:bg-red-900/20 dark:hover:bg-red-900/30
                         text-red-700 dark:text-red-400 transition-colors"
            >
              Report feedback
            </button>
          )}
        </div>
      </div>
    )
  }
}

/** Wraps a single page with an error boundary + automatic refetch on reset. */
export function PageErrorBoundary({ children }: { children: ReactNode }) {
  return <ErrorBoundary>{children}</ErrorBoundary>
}
