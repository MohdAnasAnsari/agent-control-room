import { useState, useEffect, useCallback } from 'react'
import { X, CheckCircle, AlertCircle, Info, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import type { AgentFormData, AgentRole, ModelOption, ToolOption } from '../types'

// ─── Config ───────────────────────────────────────────────────────────────────

const ROLES: { value: AgentRole; label: string; description: string }[] = [
  { value: 'analyst',    label: 'Analyst',    description: 'Analyses data and produces insights' },
  { value: 'researcher', label: 'Researcher', description: 'Searches and synthesises information' },
  { value: 'writer',     label: 'Writer',     description: 'Drafts, edits, and formats content' },
  { value: 'processor',  label: 'Processor',  description: 'Transforms and routes data' },
]

interface ModelMeta { label: string; provider: string; inputPer1M: string; outputPer1M: string; tier: 'fast' | 'balanced' | 'powerful' }
const MODELS: Record<ModelOption, ModelMeta> = {
  'claude-sonnet-4-6': { label: 'Claude Sonnet 4.6',  provider: 'Anthropic', inputPer1M: '$3.00',   outputPer1M: '$15.00',  tier: 'balanced' },
  'claude-opus-4-8':   { label: 'Claude Opus 4.8',    provider: 'Anthropic', inputPer1M: '$15.00',  outputPer1M: '$75.00',  tier: 'powerful' },
  'claude-haiku-4-5':  { label: 'Claude Haiku 4.5',   provider: 'Anthropic', inputPer1M: '$0.80',   outputPer1M: '$4.00',   tier: 'fast'     },
  'gpt-4o':            { label: 'GPT-4o',             provider: 'OpenAI',    inputPer1M: '$2.50',   outputPer1M: '$10.00',  tier: 'balanced' },
  'gpt-4o-mini':       { label: 'GPT-4o mini',        provider: 'OpenAI',    inputPer1M: '$0.15',   outputPer1M: '$0.60',   tier: 'fast'     },
  'groq-llama3':       { label: 'Groq Llama 3.1 70B', provider: 'Groq',      inputPer1M: '$0.59',   outputPer1M: '$0.79',   tier: 'fast'     },
}

const TIER_BADGE: Record<ModelMeta['tier'], string> = {
  fast:     'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  balanced: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  powerful: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
}

const TOOLS: { value: ToolOption; label: string; icon: string }[] = [
  { value: 'web_search',      label: 'Web Search',      icon: '🔍' },
  { value: 'file_read',       label: 'File Read',        icon: '📄' },
  { value: 'email_send',      label: 'Email Send',       icon: '📧' },
  { value: 'calendar',        label: 'Calendar',         icon: '📅' },
  { value: 'sql',             label: 'SQL',              icon: '🗄️' },
  { value: 'code_executor',   label: 'Code Executor',    icon: '⚡' },
  { value: 'slack',           label: 'Slack',            icon: '💬' },
  { value: 'github',          label: 'GitHub',           icon: '🐙' },
  { value: 'document_reader', label: 'Document Reader',  icon: '📚' },
  { value: 'image_gen',       label: 'Image Gen',        icon: '🎨' },
]

// ─── Validation ───────────────────────────────────────────────────────────────

interface FormErrors {
  name?: string
  systemPrompt?: string
}

function validate(data: AgentFormData): FormErrors {
  const errs: FormErrors = {}
  if (!data.name.trim()) errs.name = 'Name is required'
  else if (data.name.trim().length < 3) errs.name = 'Name must be at least 3 characters'
  if (!data.systemPrompt.trim()) errs.systemPrompt = 'System prompt is required'
  else if (data.systemPrompt.trim().length < 20) errs.systemPrompt = 'System prompt must be at least 20 characters'
  return errs
}

const PROMPT_LIMIT = 500

// ─── Sub-components ───────────────────────────────────────────────────────────

function FieldLabel({ htmlFor, children, required }: { htmlFor: string; children: React.ReactNode; required?: boolean }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
      {children}
      {required && <span className="text-red-500 ml-0.5" aria-hidden="true">*</span>}
    </label>
  )
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return (
    <p className="flex items-center gap-1 mt-1 text-xs text-red-600 dark:text-red-400" role="alert">
      <AlertCircle size={11} aria-hidden="true" /> {message}
    </p>
  )
}

function FieldValid({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <CheckCircle size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-green-500" aria-label="Valid" />
  )
}

const inputCls = 'w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent placeholder-gray-400 transition-colors'
const invalidCls = '!border-red-400 dark:!border-red-600 focus:!ring-red-400'

// ─── Main Component ───────────────────────────────────────────────────────────

interface AgentBuilderProps {
  open: boolean
  initial?: Partial<AgentFormData>
  onSave: (data: AgentFormData) => void
  onClose: () => void
}

const DEFAULT_FORM: AgentFormData = {
  name: '',
  role: 'analyst',
  systemPrompt: '',
  model: 'claude-sonnet-4-6',
  tools: [],
  memorySize: 30,
}

export default function AgentBuilder({ open, initial, onSave, onClose }: AgentBuilderProps) {
  const [form, setForm] = useState<AgentFormData>({ ...DEFAULT_FORM, ...initial })
  const [touched, setTouched] = useState<Partial<Record<keyof AgentFormData, boolean>>>({})
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (open) {
      setForm({ ...DEFAULT_FORM, ...initial })
      setTouched({})
      setSubmitted(false)
    }
  }, [open, initial])

  // Close on Esc
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  const errors = validate(form)
  const isValid = Object.keys(errors).length === 0

  const touch = (field: keyof AgentFormData) => setTouched(t => ({ ...t, [field]: true }))

  const set = useCallback(<K extends keyof AgentFormData>(key: K, value: AgentFormData[K]) => {
    setForm(prev => ({ ...prev, [key]: value }))
  }, [])

  const toggleTool = useCallback((tool: ToolOption) => {
    setForm(prev => ({
      ...prev,
      tools: prev.tools.includes(tool) ? prev.tools.filter(t => t !== tool) : [...prev.tools, tool],
    }))
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (!isValid) return
    onSave(form)
  }

  const showErr = (field: keyof FormErrors) =>
    (touched[field] || submitted) ? errors[field] : undefined

  const model = MODELS[form.model]
  const promptChars = form.systemPrompt.length

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="agent-builder-title"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <h2 id="agent-builder-title" className="text-lg font-semibold text-gray-900 dark:text-white">
            {initial?.name ? 'Edit Agent' : 'Create New Agent'}
          </h2>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-9 h-9 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body: form + preview */}
        <form onSubmit={handleSubmit} className="flex flex-1 overflow-hidden" noValidate>
          {/* ── Left: form ── */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 border-r border-gray-200 dark:border-gray-700">

            {/* Name */}
            <div>
              <FieldLabel htmlFor="agent-name" required>Name</FieldLabel>
              <div className="relative">
                <input
                  id="agent-name"
                  type="text"
                  value={form.name}
                  onChange={e => set('name', e.target.value)}
                  onBlur={() => touch('name')}
                  placeholder="e.g. SummaryBot"
                  className={clsx(inputCls, showErr('name') && invalidCls, 'pr-8')}
                  aria-describedby={showErr('name') ? 'name-error' : undefined}
                  aria-invalid={!!showErr('name')}
                />
                <FieldValid show={!errors.name && form.name.length >= 3} />
              </div>
              <div id="name-error"><FieldError message={showErr('name')} /></div>
            </div>

            {/* Role */}
            <div>
              <FieldLabel htmlFor="agent-role" required>Role</FieldLabel>
              <div className="relative">
                <select
                  id="agent-role"
                  value={form.role}
                  onChange={e => set('role', e.target.value as AgentRole)}
                  className={clsx(inputCls, 'appearance-none pr-8')}
                >
                  {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" aria-hidden="true" />
              </div>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {ROLES.find(r => r.value === form.role)?.description}
              </p>
            </div>

            {/* System Prompt */}
            <div>
              <FieldLabel htmlFor="agent-prompt" required>System Prompt</FieldLabel>
              <textarea
                id="agent-prompt"
                value={form.systemPrompt}
                onChange={e => set('systemPrompt', e.target.value.slice(0, PROMPT_LIMIT))}
                onBlur={() => touch('systemPrompt')}
                rows={5}
                placeholder="You are a helpful agent that..."
                className={clsx(inputCls, 'resize-none', showErr('systemPrompt') && invalidCls)}
                aria-describedby="prompt-count prompt-error"
                aria-invalid={!!showErr('systemPrompt')}
              />
              <div className="flex items-center justify-between mt-1">
                <div id="prompt-error"><FieldError message={showErr('systemPrompt')} /></div>
                <span
                  id="prompt-count"
                  className={clsx('text-xs ml-auto', promptChars >= PROMPT_LIMIT ? 'text-red-500' : 'text-gray-400')}
                >
                  {promptChars}/{PROMPT_LIMIT}
                </span>
              </div>
            </div>

            {/* Model */}
            <div>
              <FieldLabel htmlFor="agent-model" required>Model</FieldLabel>
              <div className="relative">
                <select
                  id="agent-model"
                  value={form.model}
                  onChange={e => set('model', e.target.value as ModelOption)}
                  className={clsx(inputCls, 'appearance-none pr-8')}
                >
                  {(Object.entries(MODELS) as [ModelOption, ModelMeta][]).map(([v, m]) => (
                    <option key={v} value={v}>{m.label} ({m.provider})</option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" aria-hidden="true" />
              </div>
            </div>

            {/* Tools */}
            <div>
              <FieldLabel htmlFor="tools-group">Tools</FieldLabel>
              <div
                id="tools-group"
                role="group"
                aria-label="Select tools"
                className="grid grid-cols-2 gap-2"
              >
                {TOOLS.map(tool => {
                  const checked = form.tools.includes(tool.value)
                  return (
                    <label
                      key={tool.value}
                      className={clsx(
                        'flex items-center gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-colors select-none',
                        checked
                          ? 'border-primary-400 bg-primary-50 dark:bg-primary-900/20 dark:border-primary-600'
                          : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleTool(tool.value)}
                        className="sr-only"
                        aria-label={tool.label}
                      />
                      <span className="text-base" aria-hidden="true">{tool.icon}</span>
                      <span className={clsx('text-sm', checked ? 'text-primary-700 dark:text-primary-300 font-medium' : 'text-gray-700 dark:text-gray-300')}>
                        {tool.label}
                      </span>
                      {checked && <CheckCircle size={12} className="ml-auto text-primary-500 shrink-0" aria-hidden="true" />}
                    </label>
                  )
                })}
              </div>
            </div>

            {/* Memory size */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <FieldLabel htmlFor="agent-memory">Memory Size</FieldLabel>
                <span className="text-sm font-semibold text-primary-600 dark:text-primary-400">{form.memorySize} msgs</span>
              </div>
              <input
                id="agent-memory"
                type="range"
                min={10}
                max={100}
                step={5}
                value={form.memorySize}
                onChange={e => set('memorySize', Number(e.target.value))}
                className="w-full h-2 rounded-full accent-primary-500 cursor-pointer"
                aria-valuemin={10}
                aria-valuemax={100}
                aria-valuenow={form.memorySize}
              />
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>10</span><span>100</span>
              </div>
            </div>
          </div>

          {/* ── Right: preview ── */}
          <div className="w-72 shrink-0 overflow-y-auto bg-gray-50 dark:bg-gray-800/50 px-5 py-5 space-y-5">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Live Preview</h3>

            {/* System prompt preview */}
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">System Prompt</p>
              <div className="rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-3 min-h-[100px]">
                {form.systemPrompt ? (
                  <p className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap leading-relaxed">
                    <span className="font-medium text-primary-600 dark:text-primary-400">
                      [{ROLES.find(r => r.value === form.role)?.label}]
                    </span>{' '}
                    {form.systemPrompt}
                  </p>
                ) : (
                  <p className="text-xs text-gray-400 italic">Enter a prompt to see preview…</p>
                )}
              </div>
            </div>

            {/* Selected tools */}
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
                Tools ({form.tools.length})
              </p>
              {form.tools.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {form.tools.map(t => {
                    const tool = TOOLS.find(x => x.value === t)
                    return (
                      <span key={t} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 text-xs">
                        {tool?.icon} {tool?.label}
                      </span>
                    )
                  })}
                </div>
              ) : (
                <p className="text-xs text-gray-400 italic">No tools selected</p>
              )}
            </div>

            {/* Model info */}
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Model Pricing</p>
              <div className="rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{model.label}</span>
                  <span className={clsx('rounded-full px-1.5 py-0.5 text-[10px] font-semibold capitalize', TIER_BADGE[model.tier])}>
                    {model.tier}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs text-gray-600 dark:text-gray-400">
                  <span>Input:</span> <span className="font-mono text-right">{model.inputPer1M}/1M</span>
                  <span>Output:</span> <span className="font-mono text-right">{model.outputPer1M}/1M</span>
                  <span>Memory:</span> <span className="font-mono text-right">{form.memorySize} msgs</span>
                </div>
                <div className="flex items-start gap-1.5 rounded-md bg-blue-50 dark:bg-blue-900/20 p-2 text-xs text-blue-700 dark:text-blue-400">
                  <Info size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
                  Context ≈ {(form.memorySize * 300).toLocaleString()} tokens (~{form.memorySize * 300 / 1000 * parseFloat(model.inputPer1M.replace('$', '')) / 1000 < 0.01 ? '<$0.01' : `$${(form.memorySize * 300 / 1000000 * parseFloat(model.inputPer1M.replace('$', ''))).toFixed(4)}`} input/run)
                </div>
              </div>
            </div>

            {/* Validation summary */}
            {(submitted || Object.keys(touched).length > 0) && (
              <div className={clsx('rounded-lg p-3 text-xs', isValid ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400' : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400')}>
                {isValid ? (
                  <span className="flex items-center gap-1.5"><CheckCircle size={12} /> Ready to save</span>
                ) : (
                  <ul className="space-y-1">
                    {Object.values(errors).map((msg, i) => (
                      <li key={i} className="flex items-center gap-1.5"><AlertCircle size={11} />{msg}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]"
          >
            Cancel
          </button>
          <button
            type="submit"
            form=""
            onClick={handleSubmit}
            className={clsx(
              'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 min-h-[44px]',
              isValid ? 'bg-primary-500 hover:bg-primary-600' : 'bg-gray-300 dark:bg-gray-600 cursor-not-allowed',
            )}
            aria-disabled={!isValid}
          >
            <CheckCircle size={16} />
            {initial?.name ? 'Save Changes' : 'Create Agent'}
          </button>
        </div>
      </div>
    </div>
  )
}
