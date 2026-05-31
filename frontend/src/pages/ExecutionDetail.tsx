import { useParams, Link } from 'react-router-dom'
import { Circle, CheckCircle2, XCircle, Clock, Wifi, WifiOff, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { useExecutionMonitor } from '../hooks/useExecutionMonitor'
import { Skeleton } from '../components/Skeleton'
import type { BackendExecutionStep } from '../api/executions'

function StatusIcon({ status }: { status: string }) {
  const icons: Record<string, React.ReactNode> = {
    completed: <CheckCircle2 size={16} className="text-green-500" />,
    failed:    <XCircle size={16} className="text-red-500" />,
    running:   <Circle size={16} className="text-blue-500 animate-pulse" />,
  }
  return <>{icons[status] ?? <Circle size={16} className="text-gray-400" />}</>
}

function statusBadge(s: string) {
  const map: Record<string, string> = {
    completed: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    running:   'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    failed:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    pending:   'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
    halted:    'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  }
  return map[s] ?? map.pending
}

function fmt(ms: number | null) {
  if (!ms) return '—'
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function StepRow({ step, index }: { step: BackendExecutionStep; index: number }) {
  return (
    <div className="flex gap-4 py-4 border-b border-gray-50 dark:border-gray-800/50 last:border-0">
      <div className="flex flex-col items-center pt-0.5">
        <StatusIcon status={step.output ? 'completed' : 'pending'} />
        <div className="w-px flex-1 bg-gray-100 dark:bg-gray-800 mt-2" />
      </div>
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            Step {index + 1}
            {step.agent_id && (
              <span className="ml-2 font-mono text-xs text-gray-400">
                ({step.agent_id.slice(0, 8)}…)
              </span>
            )}
          </p>
          <div className="flex items-center gap-2 shrink-0 text-xs text-gray-500">
            {step.duration_ms !== null && <><Clock size={10} />{fmt(step.duration_ms)}</>}
            <span>{new Date(step.timestamp).toLocaleTimeString()}</span>
          </div>
        </div>
        {step.input && (
          <details>
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300 select-none">Input</summary>
            <pre className="mt-1 text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded p-2 overflow-x-auto">
              {JSON.stringify(step.input, null, 2)}
            </pre>
          </details>
        )}
        {step.output && (
          <details open>
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300 select-none">Output</summary>
            <pre className="mt-1 text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded p-2 overflow-x-auto max-h-48">
              {JSON.stringify(step.output, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  )
}

export default function ExecutionDetail() {
  const { id } = useParams<{ id: string }>()
  const { execution, steps, logs, wsStatus, loading, error } = useExecutionMonitor(id)

  if (loading) {
    return (
      <main className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </main>
    )
  }

  if (error || !execution) {
    return (
      <main className="p-8 text-center max-w-lg mx-auto space-y-4">
        <AlertCircle size={40} className="text-red-400 mx-auto" />
        <p className="text-red-600 dark:text-red-400">{error ?? 'Execution not found'}</p>
        <Link to="/executions" className="text-primary-500 hover:underline text-sm">← Back</Link>
      </main>
    )
  }

  const isRunning = ['pending', 'running'].includes(execution.status)
  const duration = execution.started_at && execution.completed_at
    ? new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()
    : null

  return (
    <main className="p-4 md:p-6 max-w-4xl mx-auto space-y-6" role="main">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/executions" className="hover:text-gray-700 dark:hover:text-gray-300">Executions</Link>
        <span>/</span>
        <span className="font-mono text-gray-700 dark:text-gray-200">{id!.slice(0, 8)}…</span>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <StatusIcon status={execution.status} />
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">Execution</h1>
              <span className={clsx('px-2.5 py-0.5 text-xs font-medium rounded-full', statusBadge(execution.status))}>
                {execution.status}
              </span>
            </div>
            <p className="text-xs font-mono text-gray-400">{execution.id}</p>
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-500">
            {wsStatus === 'connected' && <><Wifi size={12} className="text-green-500" /> Live</>}
            {wsStatus === 'unavailable' && <><WifiOff size={12} className="text-amber-400" /> Polling</>}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Workflow</p>
            <p className="text-sm font-mono text-gray-700 dark:text-gray-200">{execution.workflow_id.slice(0, 8)}…</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Started</p>
            <p className="text-sm text-gray-700 dark:text-gray-200">
              {execution.started_at ? new Date(execution.started_at).toLocaleTimeString() : '—'}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Duration</p>
            <p className="text-sm text-gray-700 dark:text-gray-200">
              {isRunning ? <span className="animate-pulse text-blue-500">Running…</span> : fmt(duration)}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Steps</p>
            <p className="text-sm text-gray-700 dark:text-gray-200">{steps.length}</p>
          </div>
        </div>

        {execution.error_log && (
          <div className="mt-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800">
            <p className="text-xs font-medium text-red-700 dark:text-red-400 mb-1">Error</p>
            <pre className="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap">{execution.error_log}</pre>
          </div>
        )}
      </div>

      {steps.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-6">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
            Execution Steps ({steps.length})
          </h2>
          {steps.map((s, i) => <StepRow key={s.id} step={s} index={i} />)}
        </div>
      )}

      {logs.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-6">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
            Live Logs ({logs.length})
          </h2>
          <div className="space-y-1 font-mono text-xs max-h-64 overflow-y-auto">
            {logs.map(log => (
              <div key={log.id} className="flex gap-2 text-gray-600 dark:text-gray-400">
                <span className="shrink-0 text-gray-400">{new Date(log.timestamp).toLocaleTimeString()}</span>
                <span className={clsx('shrink-0 uppercase font-bold w-10',
                  log.level === 'error' ? 'text-red-500' : log.level === 'warn' ? 'text-amber-500' : 'text-blue-500'
                )}>{log.level}</span>
                <span>[{log.nodeName}]</span>
                <span className="flex-1">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {isRunning && steps.length === 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-12 text-center">
          <Circle size={32} className="text-blue-400 animate-pulse mx-auto mb-3" />
          <p className="text-sm text-gray-500">Waiting for execution steps…</p>
        </div>
      )}
    </main>
  )
}
