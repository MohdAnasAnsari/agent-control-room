/**
 * Templates page — /templates
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────┐
 *   │  Header: title + search + sort controls                 │
 *   ├───────────────┬─────────────────────────────────────────┤
 *   │  Category     │  Tab: Agents | Workflows                │
 *   │  sidebar      │  3-column grid of TemplateCards         │
 *   │               │                                         │
 *   └───────────────┴─────────────────────────────────────────┘
 *
 * Clicking a card opens the TemplatePreview modal.
 * "Clone" POST to backend → navigate to newly created resource.
 */

import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, SortAsc, Bot, GitBranch, AlertCircle, RefreshCw, Layers } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import TemplateCard from '../components/TemplateCard'
import TemplatePreview from '../components/TemplatePreview'
import { AgentGridSkeleton } from '../components/Skeleton'
import { useAgentTemplates, useWorkflowTemplates, useCloneAgentTemplate, useCloneWorkflowTemplate } from '../hooks/useTemplates'
import type { AgentTemplate, WorkflowTemplate, TemplateSortOption } from '../api/templates'

type AnyTemplate = AgentTemplate | WorkflowTemplate
type TabKey = 'agents' | 'workflows'

const SORT_OPTIONS: { value: TemplateSortOption; label: string }[] = [
  { value: 'popularity', label: 'Most Popular' },
  { value: 'rating',     label: 'Highest Rated' },
  { value: 'name',       label: 'Alphabetical' },
]

// ── Category sidebar ──────────────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, string> = {
  All:       '🌐',
  Sales:     '💼',
  Content:   '✍️',
  Support:   '🎧',
  Analytics: '📊',
}

function CategorySidebar({
  categories,
  selected,
  onSelect,
}: {
  categories: string[]
  selected: string
  onSelect: (cat: string) => void
}) {
  return (
    <aside className="w-44 shrink-0 space-y-1" role="navigation" aria-label="Category filter">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-3 mb-3">
        Categories
      </p>
      {categories.map(cat => (
        <button
          key={cat}
          onClick={() => onSelect(cat)}
          className={clsx(
            'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left',
            selected === cat
              ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
              : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
          )}
        >
          <span className="text-base leading-none">{CATEGORY_ICONS[cat] ?? '📦'}</span>
          <span>{cat}</span>
        </button>
      ))}
    </aside>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Templates() {
  const navigate = useNavigate()

  // Tab
  const [tab, setTab] = useState<TabKey>('agents')

  // Filters
  const [category, setCategory] = useState('All')
  const [sort, setSort] = useState<TemplateSortOption>('popularity')
  const [query, setQuery] = useState('')

  // Preview modal
  const [previewing, setPreviewing] = useState<AnyTemplate | null>(null)

  // Clone hooks
  const { clone: cloneAgent, loading: cloningAgent } = useCloneAgentTemplate()
  const { clone: cloneWorkflow, loading: cloningWorkflow } = useCloneWorkflowTemplate()
  const cloning = cloningAgent || cloningWorkflow

  // Data
  const agentData = useAgentTemplates({ category, sort, q: query })
  const workflowData = useWorkflowTemplates({ category, sort, q: query })

  const current = tab === 'agents' ? agentData : workflowData
  const categories = current.categories

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleClone = useCallback(async (template: AnyTemplate) => {
    const isWf = 'node_count' in template

    const promise = isWf
      ? cloneWorkflow(template.id)
      : cloneAgent(template.id)

    const result = await promise
    if (!result) {
      toast.error('Failed to clone template. Check your backend connection.')
      return
    }

    setPreviewing(null)

    if (isWf) {
      toast.success(`"${template.name}" cloned as workflow!`)
      navigate('/workflows')
    } else {
      toast.success(`"${result.name}" created!`)
      navigate('/agents')
    }
  }, [cloneAgent, cloneWorkflow, navigate])

  const handleTabChange = (t: TabKey) => {
    setTab(t)
    setCategory('All')  // reset category when switching tabs
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <main className="p-4 md:p-6 max-w-7xl mx-auto space-y-6" role="main">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-8 h-8 rounded-lg bg-primary-100 dark:bg-primary-900/40 flex items-center justify-center">
              <Layers size={18} className="text-primary-500" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Template Library</h1>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Pre-built agents and workflows ready to clone and customize
          </p>
        </div>

        {/* Search + sort */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
            <input
              type="search"
              placeholder="Search templates…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="pl-9 pr-4 py-2 w-52 rounded-lg border border-gray-200 dark:border-gray-700
                         bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div className="relative">
            <SortAsc className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" size={14} />
            <select
              value={sort}
              onChange={e => setSort(e.target.value as TemplateSortOption)}
              className="pl-8 pr-8 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                         bg-white dark:bg-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500
                         appearance-none cursor-pointer"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => { current.refetch(); toast('Refreshed') }}
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50
                       dark:hover:bg-gray-800 text-gray-500 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden w-fit">
        <button
          onClick={() => handleTabChange('agents')}
          className={clsx(
            'flex items-center gap-2 px-5 py-2.5 text-sm font-medium transition-colors',
            tab === 'agents'
              ? 'bg-primary-500 text-white'
              : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
          )}
        >
          <Bot size={16} />
          Agents
          <span className={clsx('px-1.5 py-0.5 text-xs rounded-full',
            tab === 'agents' ? 'bg-primary-400 text-white' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
          )}>
            {agentData.total}
          </span>
        </button>
        <button
          onClick={() => handleTabChange('workflows')}
          className={clsx(
            'flex items-center gap-2 px-5 py-2.5 text-sm font-medium transition-colors border-l border-gray-200 dark:border-gray-700',
            tab === 'workflows'
              ? 'bg-primary-500 text-white'
              : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
          )}
        >
          <GitBranch size={16} />
          Workflows
          <span className={clsx('px-1.5 py-0.5 text-xs rounded-full',
            tab === 'workflows' ? 'bg-primary-400 text-white' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
          )}>
            {workflowData.total}
          </span>
        </button>
      </div>

      {/* Content: sidebar + grid */}
      <div className="flex gap-6">
        {/* Category sidebar */}
        {categories.length > 1 && (
          <CategorySidebar
            categories={categories}
            selected={category}
            onSelect={setCategory}
          />
        )}

        {/* Grid area */}
        <div className="flex-1 min-w-0">
          {/* Error */}
          {current.error && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-red-50 dark:bg-red-900/20
                            border border-red-100 dark:border-red-800 mb-4">
              <AlertCircle size={18} className="text-red-500 shrink-0" />
              <p className="text-sm text-red-700 dark:text-red-400">{current.error}</p>
              <button onClick={current.refetch} className="ml-auto text-sm text-red-600 hover:underline">
                Retry
              </button>
            </div>
          )}

          {/* Loading */}
          {current.loading ? (
            <AgentGridSkeleton count={6} />
          ) : current.templates.length === 0 ? (
            <div className="text-center py-20 space-y-2">
              <p className="text-gray-400 text-sm">No templates found</p>
              {query && (
                <button
                  onClick={() => setQuery('')}
                  className="text-primary-500 text-sm hover:underline"
                >
                  Clear search
                </button>
              )}
            </div>
          ) : (
            <>
              <p className="text-xs text-gray-400 mb-4">
                {current.total} template{current.total !== 1 ? 's' : ''}
                {category !== 'All' ? ` in ${category}` : ''}
                {query ? ` matching "${query}"` : ''}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {(current.templates as AnyTemplate[]).map(t => (
                  <TemplateCard
                    key={t.id}
                    template={t}
                    onPreview={setPreviewing}
                    onClone={handleClone}
                    cloning={cloning && previewing?.id === t.id}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Preview modal */}
      {previewing && (
        <TemplatePreview
          template={previewing}
          onClose={() => setPreviewing(null)}
          onClone={handleClone}
          cloning={cloning}
        />
      )}
    </main>
  )
}
