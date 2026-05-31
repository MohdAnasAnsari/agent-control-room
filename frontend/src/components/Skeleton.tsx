/**
 * Skeleton loading components — shimmer placeholders for every data shape.
 * Always render something; never show a bare empty state.
 */

import clsx from 'clsx'
import type { ReactNode } from 'react'

// ── Base shimmer ──────────────────────────────────────────────────────────────

interface SkeletonProps {
  className?: string
  rounded?: 'sm' | 'md' | 'lg' | 'full'
}

export function Skeleton({ className, rounded = 'md' }: SkeletonProps) {
  const radii = { sm: 'rounded', md: 'rounded-lg', lg: 'rounded-xl', full: 'rounded-full' }
  return (
    <div
      aria-hidden="true"
      className={clsx(
        'animate-pulse bg-gray-200 dark:bg-gray-700',
        radii[rounded],
        className
      )}
    />
  )
}

// ── Stat card skeleton ────────────────────────────────────────────────────────

export function StatCardSkeleton() {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5 space-y-3">
      <div className="flex items-start justify-between">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-9 w-9" rounded="lg" />
      </div>
      <Skeleton className="h-8 w-20" />
      <Skeleton className="h-3 w-36" />
    </div>
  )
}

// ── Agent card skeleton ───────────────────────────────────────────────────────

export function AgentCardSkeleton() {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5 space-y-4">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10" rounded="full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-20" />
        </div>
        <Skeleton className="h-5 w-14" rounded="full" />
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/5" />
      <div className="flex gap-2">
        <Skeleton className="h-5 w-16" rounded="full" />
        <Skeleton className="h-5 w-16" rounded="full" />
      </div>
    </div>
  )
}

// ── Table row skeleton ────────────────────────────────────────────────────────

export function TableRowSkeleton({ cols = 5 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className="h-4" style={{ width: `${60 + Math.random() * 30}%` } as React.CSSProperties} />
        </td>
      ))}
    </tr>
  )
}

export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRowSkeleton key={i} cols={cols} />
      ))}
    </tbody>
  )
}

// ── Grid skeleton ─────────────────────────────────────────────────────────────

export function AgentGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <AgentCardSkeleton key={i} />
      ))}
    </div>
  )
}

// ── Dashboard stats grid ──────────────────────────────────────────────────────

export function StatsGridSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)}
    </div>
  )
}

// ── Generic list skeleton ─────────────────────────────────────────────────────

export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-4 flex items-center gap-4">
          <Skeleton className="h-10 w-10" rounded="full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
          <Skeleton className="h-5 w-16" rounded="full" />
        </div>
      ))}
    </div>
  )
}

// ── Conditional wrapper ───────────────────────────────────────────────────────

interface WithSkeletonProps {
  loading: boolean
  skeleton: ReactNode
  children: ReactNode
}

/** Renders skeleton while loading, then swaps to children. */
export function WithSkeleton({ loading, skeleton, children }: WithSkeletonProps) {
  return <>{loading ? skeleton : children}</>
}
