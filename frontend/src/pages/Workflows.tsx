import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Play, AlertCircle, RefreshCw, ToggleLeft, ToggleRight } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { ListSkeleton } from '../components/Skeleton'
import { useWorkflows, useUpdateWorkflow, useExecuteWorkflow, useCreateWorkflow } from '../hooks/useWorkflows'
import type { BackendWorkflow } from '../api/workflows'

export default function Workflows() {
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)

  const { workflows, loading, error, refetch } = useWorkflows({ limit: 50 })
  const { mutate: updateWorkflow } = useUpdateWorkflow()
  const { mutate: executeWorkflow, loading: executing } = useExecuteWorkflow()
  const { mutate: createWorkflow, loading: creating } = useCreateWorkflow()

  const handleToggleActive = async (wf: BackendWorkflow) => {
    const result = await updateWorkflow(wf.id, { is_active: !wf.is_active })
    if (result) {
      toast.success(`Workflow ${result.is_active ? 'activated' : 'deactivated'}`)
      refetch()
    } else {
      toast.error('Failed to update workflow')
    }
  }

  const handleExecute = async (wf: BackendWorkflow) => {
    if (!wf.is_active) { toast.error('Workflow is inactive. Activate it first.'); return }
    const result = await executeWorkflow(wf.id, { input_data: {}, run_async: true })
    if (result) {
      toast.success(`Execution started`)
      navigate(`/executions/${result.execution_id}`)
    } else {
      toast.error('Failed to start workflow')
    }
  }

  const handleCreate = async (name: string) => {
    const wf = await createWorkflow({ name, nodes: [], edges: [] })
    if (wf) {
      toast.success(`Workflow "${wf.name}" created`)
      setShowCreate(false)
      refetch()
    } else {
      toast.error('Failed to create workflow')
    }
  }

  return (
    <main className="p-4 md:p-6 max-w-7xl mx-auto space-y-6" role="main">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Workflows</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {loading ? 'Loading…' : `${workflows.length} workflows`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={refetch}
            className="p-2 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-500 transition-colors">
            <RefreshCw size={16} />
          </button>
          <button onClick={() => setShowCreate(true)} disabled={creating}
            className="flex items-center gap-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 min-h-[44px]">
            <Plus size={16} /> New Workflow
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800">
          <AlertCircle size={18} className="text-red-500" />
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          <button onClick={refetch} className="ml-auto text-sm text-red-600 hover:underline">Retry</button>
        </div>
      )}

      {showCreate && (
        <QuickCreateForm onSubmit={handleCreate} onCancel={() => setShowCreate(false)} loading={creating} />
      )}

      {loading ? <ListSkeleton rows={5} /> : workflows.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <p className="text-gray-500 dark:text-gray-400">No workflows yet</p>
          <button onClick={() => setShowCreate(true)} className="text-primary-500 text-sm hover:underline">
            Create your first workflow
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {workflows.map(wf => (
            <WorkflowCard key={wf.id} workflow={wf}
              onToggle={() => handleToggleActive(wf)}
              onExecute={() => handleExecute(wf)}
              executing={executing}
            />
          ))}
        </div>
      )}
    </main>
  )
}

function WorkflowCard({ workflow, onToggle, onExecute, executing }: {
  workflow: BackendWorkflow
  onToggle: () => void
  onExecute: () => void
  executing: boolean
}) {
  const nodes = workflow.dag_config?.nodes?.length ?? 0
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-5 flex items-center gap-4">
      <div className={clsx('w-2 h-10 rounded-full shrink-0', workflow.is_active ? 'bg-green-400' : 'bg-gray-300 dark:bg-gray-600')} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-gray-900 dark:text-white truncate">{workflow.name}</h3>
          <span className={clsx('px-2 py-0.5 text-xs font-medium rounded-full shrink-0',
            workflow.is_active ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400'
              : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400')}>
            {workflow.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-0.5 font-mono">
          {workflow.id.slice(0, 12)}… · {nodes} node{nodes !== 1 ? 's' : ''}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={onToggle}
          className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          title={workflow.is_active ? 'Deactivate' : 'Activate'}>
          {workflow.is_active ? <ToggleRight size={18} className="text-green-500" /> : <ToggleLeft size={18} />}
        </button>
        <button onClick={onExecute} disabled={executing || !workflow.is_active}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-primary-50 hover:bg-primary-100 dark:bg-primary-900/20 dark:hover:bg-primary-900/30 text-primary-600 dark:text-primary-400 transition-colors disabled:opacity-40">
          <Play size={13} /> Run
        </button>
      </div>
    </div>
  )
}

function QuickCreateForm({ onSubmit, onCancel, loading }: {
  onSubmit: (name: string) => void; onCancel: () => void; loading: boolean
}) {
  const [name, setName] = useState('')
  const valid = name.trim().length >= 1
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-primary-200 dark:border-primary-800 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900 dark:text-white">New Workflow</h3>
      <input type="text" value={name} onChange={e => setName(e.target.value)}
        placeholder="My Research Pipeline" autoFocus
        onKeyDown={e => { if (e.key === 'Enter' && valid) onSubmit(name.trim()) }}
        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
      <div className="flex justify-end gap-2">
        <button onClick={onCancel}
          className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
          Cancel
        </button>
        <button onClick={() => valid && onSubmit(name.trim())} disabled={!valid || loading}
          className="px-4 py-2 text-sm rounded-lg bg-primary-500 hover:bg-primary-600 text-white transition-colors disabled:opacity-50">
          {loading ? 'Creating…' : 'Create'}
        </button>
      </div>
    </div>
  )
}
