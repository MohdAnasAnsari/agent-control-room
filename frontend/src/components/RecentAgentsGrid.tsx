import { Link } from 'react-router-dom'
import { Pencil, Loader2, FlaskConical, PenLine, Cpu, Search } from 'lucide-react'
import clsx from 'clsx'
import type { RecentAgent, AgentRole } from '../types'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)    return `${diff}s ago`
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ─── Role icons + colors ──────────────────────────────────────────────────────

const ROLE_CONFIG: Record<AgentRole, {
  Icon: React.ComponentType<{ size?: number; className?: string }>
  bg: string
  fg: string
  label: string
}> = {
  analyst:    { Icon: FlaskConical, bg: 'bg-blue-50 dark:bg-blue-900/30',   fg: 'text-blue-600 dark:text-blue-400',   label: 'Analyst' },
  writer:     { Icon: PenLine,      bg: 'bg-purple-50 dark:bg-purple-900/30', fg: 'text-purple-600 dark:text-purple-400', label: 'Writer' },
  processor:  { Icon: Cpu,          bg: 'bg-amber-50 dark:bg-amber-900/30',  fg: 'text-amber-600 dark:text-amber-400',  label: 'Processor' },
  researcher: { Icon: Search,       bg: 'bg-green-50 dark:bg-green-900/30',  fg: 'text-green-600 dark:text-green-400',  label: 'Researcher' },
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function AgentCardSkeleton() {
  return (
    <div className="rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4" aria-hidden="true">
      <div className="flex items-start justify-between mb-3">
        <div className="w-10 h-10 rounded-lg skeleton" />
        <div className="w-14 h-5 rounded-full skeleton" />
      </div>
      <div className="w-24 h-4 rounded skeleton mb-1.5" />
      <div className="w-16 h-3 rounded skeleton mb-3" />
      <div className="w-20 h-3 rounded skeleton" />
    </div>
  )
}

// ─── Single agent card ────────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: RecentAgent }) {
  const cfg = ROLE_CONFIG[agent.role]
  const { Icon } = cfg

  return (
    <div className="rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4 hover:shadow-md hover:border-primary-200 dark:hover:border-primary-700 transition-all group">
      {/* Top row: icon + status */}
      <div className="flex items-start justify-between mb-3">
        <div className={clsx('flex items-center justify-center w-10 h-10 rounded-lg', cfg.bg)}>
          <Icon size={18} className={cfg.fg} />
        </div>

        <span className={clsx(
          'flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium',
          agent.status === 'running'
            ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
            : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
        )}>
          {agent.status === 'running'
            ? <Loader2 size={9} className="animate-spin" />
            : <span className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500" />
          }
          {agent.status === 'running' ? 'Running' : 'Idle'}
        </span>
      </div>

      {/* Name + role */}
      <p className="font-semibold text-sm text-gray-900 dark:text-white">{agent.name}</p>
      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{cfg.label}</p>
      {agent.model && (
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">{agent.model}</p>
      )}

      {/* Footer: last run + edit */}
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Last run: <span className="text-gray-600 dark:text-gray-300">{timeAgo(agent.lastRunAt)}</span>
        </p>
        <Link
          to={`/agents/${agent.id}`}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors opacity-0 group-hover:opacity-100"
          aria-label={`Edit ${agent.name}`}
        >
          <Pencil size={11} />
          Edit
        </Link>
      </div>
    </div>
  )
}

// ─── Grid ─────────────────────────────────────────────────────────────────────

interface Props {
  agents: RecentAgent[]
  loading?: boolean
}

export default function RecentAgentsGrid({ agents, loading = false }: Props) {
  return (
    <section aria-labelledby="recent-agents-title">
      <div className="flex items-center justify-between mb-3">
        <h2 id="recent-agents-title" className="text-base font-semibold text-gray-900 dark:text-white">
          Recent Agents
        </h2>
        <Link
          to="/agents"
          className="text-sm text-primary-600 dark:text-primary-400 hover:underline focus-visible:outline-none focus-visible:underline"
        >
          View all
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <AgentCardSkeleton key={i} />)
          : agents.map(a => <AgentCard key={a.id} agent={a} />)
        }
      </div>
    </section>
  )
}
