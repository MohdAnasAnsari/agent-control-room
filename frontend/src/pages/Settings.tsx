import { useState } from 'react'
import { User, Bell, Shield, Palette, Server, Save } from 'lucide-react'
import clsx from 'clsx'

type Section = 'profile' | 'notifications' | 'security' | 'appearance' | 'api'

interface ToggleProps {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}

function Toggle({ checked, onChange, label }: ToggleProps) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={clsx(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
        checked ? 'bg-primary-500' : 'bg-gray-300 dark:bg-gray-600',
      )}
    >
      <span
        className={clsx(
          'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-6' : 'translate-x-1',
        )}
      />
    </button>
  )
}

interface FieldProps {
  label: string
  id: string
  children: React.ReactNode
}

function Field({ label, id, children }: FieldProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-6 py-4 border-b border-gray-100 dark:border-gray-700 last:border-0">
      <label htmlFor={id} className="text-sm font-medium text-gray-700 dark:text-gray-300 sm:w-48 shrink-0">
        {label}
      </label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

const inputCls = 'w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent'

const SECTIONS: { id: Section; label: string; icon: React.ComponentType<{ size?: number; className?: string }> }[] = [
  { id: 'profile',       label: 'Profile',       icon: User },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'security',      label: 'Security',      icon: Shield },
  { id: 'appearance',    label: 'Appearance',    icon: Palette },
  { id: 'api',           label: 'API',           icon: Server },
]

export default function Settings() {
  const [activeSection, setActiveSection] = useState<Section>('profile')
  const [saved, setSaved] = useState(false)

  // Form state
  const [name, setName] = useState('Anas Ansari')
  const [email] = useState('anas.ansari@ourworldenergy.com')
  const [emailNotifs, setEmailNotifs] = useState(true)
  const [slackNotifs, setSlackNotifs] = useState(false)
  const [failureAlerts, setFailureAlerts] = useState(true)
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>('system')
  const [apiKey] = useState('sk-orch-••••••••••••••••••••')
  const [apiUrl, setApiUrl] = useState('http://localhost:8000')

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <main className="p-4 md:p-6 max-w-5xl mx-auto space-y-6" role="main">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Manage your account and system preferences.</p>
      </div>

      <div className="flex flex-col sm:flex-row gap-6">
        {/* Sidebar nav */}
        <nav aria-label="Settings sections" className="sm:w-48 shrink-0">
          <ul role="list" className="space-y-1">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  onClick={() => setActiveSection(id)}
                  className={clsx(
                    'flex items-center gap-3 w-full rounded-lg px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]',
                    activeSection === id
                      ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white',
                  )}
                  aria-current={activeSection === id ? 'page' : undefined}
                >
                  <Icon size={16} />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Content */}
        <section className="flex-1 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-6" aria-labelledby="settings-section-title">
          {activeSection === 'profile' && (
            <>
              <h2 id="settings-section-title" className="text-base font-semibold text-gray-900 dark:text-white mb-2">Profile</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Update your personal information.</p>
              <Field label="Full name" id="name">
                <input id="name" type="text" value={name} onChange={e => setName(e.target.value)} className={inputCls} />
              </Field>
              <Field label="Email" id="email">
                <input id="email" type="email" value={email} readOnly className={clsx(inputCls, 'opacity-60 cursor-not-allowed')} aria-describedby="email-note" />
                <p id="email-note" className="text-xs text-gray-400 mt-1">Managed by your organisation.</p>
              </Field>
              <Field label="Role" id="role">
                <input id="role" type="text" value="Admin" readOnly className={clsx(inputCls, 'opacity-60 cursor-not-allowed')} />
              </Field>
            </>
          )}

          {activeSection === 'notifications' && (
            <>
              <h2 id="settings-section-title" className="text-base font-semibold text-gray-900 dark:text-white mb-2">Notifications</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Choose how you want to be notified.</p>
              <Field label="Email notifications" id="email-notifs">
                <Toggle checked={emailNotifs} onChange={setEmailNotifs} label="Email notifications" />
              </Field>
              <Field label="Slack notifications" id="slack-notifs">
                <Toggle checked={slackNotifs} onChange={setSlackNotifs} label="Slack notifications" />
              </Field>
              <Field label="Failure alerts" id="failure-alerts">
                <Toggle checked={failureAlerts} onChange={setFailureAlerts} label="Alert on execution failure" />
              </Field>
            </>
          )}

          {activeSection === 'security' && (
            <>
              <h2 id="settings-section-title" className="text-base font-semibold text-gray-900 dark:text-white mb-2">Security</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Manage authentication and access.</p>
              <Field label="Password" id="password">
                <button className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]">
                  Change password
                </button>
              </Field>
              <Field label="Two-factor auth" id="2fa">
                <button className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]">
                  Set up 2FA
                </button>
              </Field>
            </>
          )}

          {activeSection === 'appearance' && (
            <>
              <h2 id="settings-section-title" className="text-base font-semibold text-gray-900 dark:text-white mb-2">Appearance</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Customize the look and feel.</p>
              <Field label="Theme" id="theme">
                <div className="flex gap-2" role="group" aria-label="Theme selection">
                  {(['system', 'light', 'dark'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => setTheme(t)}
                      className={clsx(
                        'flex-1 rounded-lg border px-3 py-2 text-sm capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]',
                        theme === t
                          ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 font-medium'
                          : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700',
                      )}
                      aria-pressed={theme === t}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </Field>
            </>
          )}

          {activeSection === 'api' && (
            <>
              <h2 id="settings-section-title" className="text-base font-semibold text-gray-900 dark:text-white mb-2">API Configuration</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Configure backend API connection.</p>
              <Field label="API Key" id="api-key">
                <input id="api-key" type="password" value={apiKey} readOnly className={clsx(inputCls, 'font-mono')} aria-label="API key (hidden)" />
              </Field>
              <Field label="API URL" id="api-url">
                <input id="api-url" type="url" value={apiUrl} onChange={e => setApiUrl(e.target.value)} className={clsx(inputCls, 'font-mono')} />
              </Field>
            </>
          )}

          {/* Save button */}
          <div className="flex justify-end mt-6 pt-4 border-t border-gray-100 dark:border-gray-700">
            <button
              onClick={handleSave}
              className={clsx(
                'flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 min-h-[44px]',
                saved
                  ? 'bg-green-500 text-white'
                  : 'bg-primary-500 hover:bg-primary-600 text-white',
              )}
              aria-label="Save settings"
            >
              <Save size={16} />
              {saved ? 'Saved!' : 'Save changes'}
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
