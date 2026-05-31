/**
 * TemplatePreview — modal that shows full template details + clone CTA.
 * Supports both agent and workflow templates via a discriminated union.
 */

import { useEffect } from 'react'
import clsx from 'clsx'
import {
  X, Star, Users, Copy, Bot, GitBranch,
  Tag, Wrench, ChevronRight,
} from 'lucide-react'
import type { AgentTemplate, WorkflowTemplate } from '../api/templates'

type AnyTemplate = AgentTemplate | WorkflowTemplate

function isWorkflow(t: AnyTemplate): t is WorkflowTemplate {
  return 'node_count' in t
}

// ── Rating display ────────────────────────────────────────────────────────────

function RatingStars({ rating, count }: { rating: number; count: number }) {
  const full = Math.floor(rating)
  const half = rating % 1 >= 0.5
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-0.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Star
            key={i}
            size={16}
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
      <span className="text-sm font-semibold text-gray-900 dark:text-white">{rating.toFixed(1)}</span>
      <span className="text-sm text-gray-500 dark:text-gray-400">from {count} reviews</span>
    </div>
  )
}

// ── Workflow DAG diagram ──────────────────────────────────────────────────────

function WorkflowDiagram({ template }: { template: WorkflowTemplate }) {
  const nodes = template.dag_config?.nodes ?? []
  const nodeTypeColour: Record<string, string> = {
    agent: 'bg-primary-100 dark:bg-primary-900/40 border-primary-300 dark:border-primary-600 text-primary-700 dark:text-primary-300',
    condition: 'bg-amber-100 dark:bg-amber-900/40 border-amber-300 dark:border-amber-600 text-amber-700 dark:text-amber-300',
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-4 space-y-2">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
        DAG Preview — {nodes.length} nodes
      </p>
      <div className="flex flex-col gap-2">
        {nodes.map((node, i) => (
          <div key={node.id} className="flex items-center gap-2">
            {i > 0 && (
              <div className="ml-4 w-0.5 h-2 bg-gray-200 dark:bg-gray-700 -mt-2 mb-0 absolute" />
            )}
            <div className={clsx(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium',
              nodeTypeColour[node.type] ?? nodeTypeColour.agent
            )}>
              {node.type === 'condition'
                ? <span className="font-mono">⬦</span>
                : <Bot size={12} />
              }
              <span>{node.label ?? node.id}</span>
            </div>
            {node.depends_on?.length > 0 && (
              <span className="text-xs text-gray-400 font-mono">
                ← {node.depends_on.join(', ')}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

interface TemplatePreviewProps {
  template: AnyTemplate
  onClose: () => void
  onClone: (template: AnyTemplate) => void
  cloning?: boolean
}

export default function TemplatePreview({
  template,
  onClose,
  onClone,
  cloning,
}: TemplatePreviewProps) {
  const wf = isWorkflow(template)

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Trap scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Preview: ${template.name}`}
    >
      <div
        className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-white dark:bg-gray-900
                   rounded-2xl shadow-2xl border border-gray-100 dark:border-gray-800"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={clsx(
              'w-9 h-9 rounded-xl flex items-center justify-center',
              wf ? 'bg-indigo-100 dark:bg-indigo-900/40' : 'bg-primary-100 dark:bg-primary-900/40'
            )}>
              {wf
                ? <GitBranch size={18} className="text-indigo-500" />
                : <Bot size={18} className="text-primary-500" />
              }
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-white">{template.name}</h2>
              <p className="text-xs text-gray-500">{template.category} template</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
                       hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Close preview"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-6">
          {/* Rating + popularity */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <RatingStars rating={template.rating} count={template.rating_count} />
            <div className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
              <Users size={15} />
              <span>Cloned <strong className="text-gray-900 dark:text-white">{template.clone_count}</strong> times</span>
            </div>
          </div>

          {/* Description */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">About</h3>
            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
              {template.description}
            </p>
          </div>

          {/* Tags */}
          {template.tags.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                <Tag size={11} /> Tags
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {template.tags.map(tag => (
                  <span key={tag}
                    className="px-2.5 py-1 text-xs rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Agent-specific */}
          {!wf && (() => {
            const a = template as AgentTemplate
            return (
              <>
                {/* Model */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Model</h3>
                  <code className="text-xs px-2.5 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                    {a.model}
                  </code>
                </div>

                {/* Tools */}
                {a.tools.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                      <Wrench size={11} /> Tools ({a.tools.length})
                    </h3>
                    <div className="flex flex-wrap gap-1.5">
                      {a.tools.map(t => (
                        <span key={t}
                          className="px-2.5 py-1 text-xs rounded-lg bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-mono">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* System prompt */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">System Prompt (read-only)</h3>
                  <pre className="text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-xl p-4
                                  whitespace-pre-wrap font-sans leading-relaxed max-h-48 overflow-y-auto">
                    {a.system_prompt}
                  </pre>
                </div>

                {/* Example I/O */}
                {Object.keys(a.example_input).length > 0 && (
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Example Input</h3>
                      <pre className="text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto">
                        {JSON.stringify(a.example_input, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Example Output</h3>
                      <pre className="text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto">
                        {JSON.stringify(a.example_output, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}
              </>
            )
          })()}

          {/* Workflow-specific */}
          {wf && (() => {
            const w = template as WorkflowTemplate
            return (
              <>
                <div className="flex items-center gap-6 text-sm">
                  <div>
                    <p className="text-xs text-gray-500">Nodes</p>
                    <p className="font-semibold text-gray-900 dark:text-white">{w.node_count}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Est. duration</p>
                    <p className="font-semibold text-gray-900 dark:text-white">
                      {w.estimated_duration_s < 60
                        ? `${w.estimated_duration_s}s`
                        : `${Math.round(w.estimated_duration_s / 60)}m`
                      }
                    </p>
                  </div>
                </div>
                <WorkflowDiagram template={w} />
              </>
            )
          })()}
        </div>

        {/* Footer CTA */}
        <div className="sticky bottom-0 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-800 px-6 py-4 flex items-center justify-between gap-4">
          <button
            onClick={onClose}
            className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1 hover:underline"
          >
            <ChevronRight size={14} className="rotate-180" />
            View other templates
          </button>

          <button
            onClick={() => onClone(template)}
            disabled={cloning}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold
                       bg-primary-500 hover:bg-primary-600 text-white transition-colors
                       disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2"
          >
            {cloning ? (
              <>
                <span className="w-4 h-4 rounded-full border-2 border-white/60 border-t-white animate-spin" />
                Cloning…
              </>
            ) : (
              <>
                <Copy size={16} />
                Clone {wf ? 'Workflow' : 'Agent'}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
