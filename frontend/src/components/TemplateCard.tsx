/**
 * TemplateCard — displayed in the template gallery grid.
 * Supports both agent and workflow templates via a union type.
 */

import clsx from 'clsx'
import { Star, Users, Copy, Bot, GitBranch, ArrowRight } from 'lucide-react'
import type { AgentTemplate, WorkflowTemplate } from '../api/templates'

type AnyTemplate = AgentTemplate | WorkflowTemplate

function isWorkflow(t: AnyTemplate): t is WorkflowTemplate {
  return 'node_count' in t
}

// ── Category badge colours ────────────────────────────────────────────────────

const CATEGORY_COLOURS: Record<string, string> = {
  Sales:     'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  Content:   'bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  Support:   'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  Analytics: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
}

function categoryColour(cat: string) {
  return CATEGORY_COLOURS[cat] ?? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
}

// ── Mini DAG diagram (workflow preview) ───────────────────────────────────────

function MiniDag({ nodeCount }: { nodeCount: number }) {
  const nodes = Math.min(nodeCount, 5)
  return (
    <div className="flex items-center justify-center gap-1 py-2">
      {Array.from({ length: nodes }).map((_, i) => (
        <div key={i} className="flex items-center gap-1">
          <div className="w-6 h-6 rounded-md bg-primary-100 dark:bg-primary-900/40 border border-primary-200 dark:border-primary-700 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full bg-primary-400 dark:bg-primary-500" />
          </div>
          {i < nodes - 1 && (
            <div className="w-4 h-px bg-gray-300 dark:bg-gray-600" />
          )}
        </div>
      ))}
      {nodeCount > 5 && (
        <span className="text-xs text-gray-400 ml-1">+{nodeCount - 5}</span>
      )}
    </div>
  )
}

// ── Agent icon collage (agent preview) ────────────────────────────────────────

function AgentPreview({ tools }: { tools: string[] }) {
  const shown = tools.slice(0, 4)
  const toolColours = ['bg-blue-100', 'bg-green-100', 'bg-purple-100', 'bg-amber-100']
  return (
    <div className="flex items-center justify-center gap-2 py-2">
      <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-900/40 border-2 border-primary-200 dark:border-primary-700 flex items-center justify-center">
        <Bot size={18} className="text-primary-500" />
      </div>
      {shown.length > 0 && (
        <div className="flex flex-col gap-1">
          {shown.map((tool, i) => (
            <span
              key={tool}
              className={clsx(
                'text-xs px-1.5 py-0.5 rounded font-mono',
                toolColours[i % toolColours.length],
                'dark:opacity-70'
              )}
            >
              {tool.replace('_', ' ')}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Rating stars ──────────────────────────────────────────────────────────────

function RatingStars({ rating }: { rating: number }) {
  const full = Math.floor(rating)
  const half = rating % 1 >= 0.5
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          size={12}
          className={clsx(
            i < full
              ? 'text-amber-400 fill-amber-400'
              : i === full && half
                ? 'text-amber-300 fill-amber-200'
                : 'text-gray-300 dark:text-gray-600'
          )}
        />
      ))}
    </div>
  )
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface TemplateCardProps {
  template: AnyTemplate
  onPreview: (template: AnyTemplate) => void
  onClone: (template: AnyTemplate) => void
  cloning?: boolean
}

export default function TemplateCard({ template, onPreview, onClone, cloning }: TemplateCardProps) {
  const wf = isWorkflow(template)

  return (
    <article
      className="group relative flex flex-col bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800
                 hover:border-primary-200 dark:hover:border-primary-700 hover:shadow-md dark:hover:shadow-primary-900/20
                 transition-all duration-200 overflow-hidden cursor-pointer"
      onClick={() => onPreview(template)}
      role="button"
      aria-label={`Preview ${template.name}`}
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onPreview(template) }}
    >
      {/* Preview area */}
      <div className="h-28 bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-800 dark:to-gray-850 border-b border-gray-100 dark:border-gray-800 flex items-center justify-center">
        {wf
          ? <MiniDag nodeCount={(template as WorkflowTemplate).node_count} />
          : <AgentPreview tools={(template as AgentTemplate).tools} />
        }
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 p-4 space-y-3">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className={clsx(
              'w-7 h-7 rounded-lg flex items-center justify-center shrink-0',
              wf ? 'bg-indigo-100 dark:bg-indigo-900/40' : 'bg-primary-100 dark:bg-primary-900/40'
            )}>
              {wf
                ? <GitBranch size={14} className="text-indigo-500" />
                : <Bot size={14} className="text-primary-500" />
              }
            </div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate">
              {template.name}
            </h3>
          </div>
          <span className={clsx('shrink-0 px-2 py-0.5 text-xs font-medium rounded-full', categoryColour(template.category))}>
            {template.category}
          </span>
        </div>

        {/* Description */}
        <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2 flex-1">
          {template.description}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1">
          {template.tags.slice(0, 3).map(tag => (
            <span key={tag} className="px-1.5 py-0.5 text-xs rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              {tag}
            </span>
          ))}
        </div>

        {/* Stats row */}
        <div className="flex items-center justify-between pt-1 border-t border-gray-50 dark:border-gray-800">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <RatingStars rating={template.rating} />
              <span className="text-xs text-gray-500">{template.rating.toFixed(1)}</span>
              <span className="text-xs text-gray-400">({template.rating_count})</span>
            </div>
            <div className="flex items-center gap-1 text-xs text-gray-400">
              <Users size={11} />
              <span>{template.clone_count}</span>
            </div>
          </div>

          {/* Clone button */}
          <button
            onClick={e => { e.stopPropagation(); onClone(template) }}
            disabled={cloning}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg
                       bg-primary-50 hover:bg-primary-100 dark:bg-primary-900/20 dark:hover:bg-primary-900/40
                       text-primary-600 dark:text-primary-400 transition-colors disabled:opacity-50
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            aria-label={`Clone ${template.name}`}
          >
            {cloning ? (
              <span className="w-3 h-3 rounded-full border-2 border-primary-400 border-t-transparent animate-spin" />
            ) : (
              <Copy size={12} />
            )}
            Clone
          </button>
        </div>
      </div>

      {/* Hover overlay arrow */}
      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
        <div className="bg-white dark:bg-gray-800 rounded-full p-1 shadow-sm border border-gray-100 dark:border-gray-700">
          <ArrowRight size={12} className="text-gray-400" />
        </div>
      </div>
    </article>
  )
}
