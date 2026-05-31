import { memo } from 'react'
import { Link } from 'react-router-dom'
import { Bot, Wrench, GitBranch, Cpu, MoreVertical, Circle } from 'lucide-react'
import clsx from 'clsx'
import type { Agent, AgentStatus, AgentType } from '../types'

const STATUS_CONFIG: Record<AgentStatus, { label: string; color: string; dotColor: string }> = {
  active:   { label: 'Active',   color: 'text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/30',   dotColor: 'text-green-500' },
  idle:     { label: 'Idle',     color: 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800',         dotColor: 'text-gray-400' },
  error:    { label: 'Error',    color: 'text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/30',           dotColor: 'text-red-500' },
  disabled: { label: 'Disabled', color: 'text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30',  dotColor: 'text-amber-500' },
}

const TYPE_ICON: Record<AgentType, React.ComponentType<{ size?: number; className?: string }>> = {
  llm:        Bot,
  tool:       Wrench,
  supervisor: GitBranch,
  custom:     Cpu,
}

interface AgentCardProps {
  agent: Agent
  onMenuClick?: (agent: Agent) => void
}

const AgentCard = memo(({ agent, onMenuClick }: AgentCardProps) => {
  const status = STATUS_CONFIG[agent.status]
  const Icon = TYPE_ICON[agent.type]

  return (
    <article
      className="group relative flex flex-col gap-3 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4 hover:shadow-md hover:border-primary-200 dark:hover:border-primary-700 transition-all"
      aria-label={`Agent: ${agent.name}`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 shrink-0">
            <Icon size={20} />
          </div>
          <div className="min-w-0">
            <Link
              to={`/agents/${agent.id}`}
              className="text-sm font-semibold text-gray-900 dark:text-white hover:text-primary-600 dark:hover:text-primary-400 transition-colors truncate block focus-visible:outline-none focus-visible:underline"
            >
              {agent.name}
            </Link>
            <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{agent.type} agent</p>
          </div>
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', status.color)}>
            <Circle size={6} className={clsx('fill-current', status.dotColor)} aria-hidden="true" />
            {status.label}
          </span>

          {onMenuClick && (
            <button
              onClick={() => onMenuClick(agent)}
              className="opacity-0 group-hover:opacity-100 flex items-center justify-center w-7 h-7 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
              aria-label={`More options for ${agent.name}`}
            >
              <MoreVertical size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Description */}
      {agent.description && (
        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">{agent.description}</p>
      )}

      {/* Tools */}
      {agent.tools.length > 0 && (
        <div className="flex flex-wrap gap-1" aria-label="Available tools">
          {agent.tools.slice(0, 3).map(tool => (
            <span
              key={tool}
              className="inline-block px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-700 text-xs text-gray-600 dark:text-gray-300"
            >
              {tool}
            </span>
          ))}
          {agent.tools.length > 3 && (
            <span className="inline-block px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-700 text-xs text-gray-500">
              +{agent.tools.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-400 dark:text-gray-500 pt-1 border-t border-gray-100 dark:border-gray-700">
        {agent.model && <span className="font-mono truncate">{agent.model}</span>}
        <span className="ml-auto">
          {new Date(agent.updated_at).toLocaleDateString()}
        </span>
      </div>
    </article>
  )
})

AgentCard.displayName = 'AgentCard'
export default AgentCard
