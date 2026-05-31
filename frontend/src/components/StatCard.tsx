import { Link } from 'react-router-dom'
import clsx from 'clsx'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  iconColor: string
  trend?: { value: string; positive: boolean }
  to?: string
  loading?: boolean
}

export default function StatCard({
  label, value, sub, icon: Icon, iconColor, trend, to, loading = false,
}: StatCardProps) {
  if (loading) {
    return (
      <div className="rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-5" aria-hidden="true">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl skeleton" />
          <div className="flex-1 space-y-2">
            <div className="h-7 w-16 rounded skeleton" />
            <div className="h-4 w-28 rounded skeleton" />
          </div>
        </div>
      </div>
    )
  }

  const content = (
    <div className="flex items-center gap-4">
      <div className={clsx('flex items-center justify-center w-12 h-12 rounded-xl shrink-0', iconColor)}>
        <Icon size={22} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-2xl font-bold text-gray-900 dark:text-white leading-none">{value}</p>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{label}</p>
        {sub && <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{sub}</p>}
        {trend && (
          <p className={clsx(
            'text-xs font-medium mt-1',
            trend.positive ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400',
          )}>
            {trend.positive ? '↑' : '↓'} {trend.value}
          </p>
        )}
      </div>
    </div>
  )

  const cls = clsx(
    'block rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-5',
    'transition-all duration-150',
    to && 'hover:shadow-md hover:border-primary-300 dark:hover:border-primary-700 cursor-pointer',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
  )

  return to ? (
    <Link to={to} className={cls} aria-label={`${label}: ${value}`}>{content}</Link>
  ) : (
    <div className={cls} aria-label={`${label}: ${value}`}>{content}</div>
  )
}
