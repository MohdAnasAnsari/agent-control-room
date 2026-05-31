/**
 * Sentry instrumentation — must be imported BEFORE React and the app tree.
 * Import this as the very first line of main.tsx.
 *
 * Set VITE_SENTRY_DSN in your .env.* files to enable Sentry.
 * Leave empty (or unset) to disable — no errors or traces are sent.
 */
import * as Sentry from '@sentry/react'

const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined

if (dsn) {
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,        // "development" | "production"
    release: import.meta.env.VITE_APP_VERSION as string | undefined,

    integrations: [
      // Automatically instrument React Router v7 routes as transactions
      Sentry.browserTracingIntegration(),
      // Capture console.error calls as breadcrumbs
      Sentry.breadcrumbsIntegration({ console: true }),
      // Session replay: record 10% of sessions, 100% of sessions with errors
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],

    // Performance: capture 10% of page-load transactions in production
    tracesSampleRate: import.meta.env.PROD ? 0.1 : 1.0,

    // Session replay
    replaysSessionSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,

    // Don't send PII (emails, IPs) unless explicitly tagged
    sendDefaultPii: false,

    // Ignore noise from browser extensions and common 3rd-party errors
    ignoreErrors: [
      'ResizeObserver loop limit exceeded',
      'ResizeObserver loop completed with undelivered notifications',
      /^Network Error$/,
      /^Failed to fetch$/,
      /^Load failed$/,
    ],

    beforeSend(event) {
      // Strip auth tokens from request headers before sending to Sentry
      if (event.request?.headers) {
        delete event.request.headers['Authorization']
      }
      return event
    },
  })
}

export { Sentry }
