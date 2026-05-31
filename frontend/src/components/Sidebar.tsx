import { memo, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Bot,
  GitBranch,
  PlayCircle,
  Settings,
  Layers,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import clsx from 'clsx'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: string
}

const NAV_ITEMS: NavItem[] = [
  { to: '/',          label: 'Dashboard',  icon: LayoutDashboard },
  { to: '/agents',    label: 'Agents',     icon: Bot },
  { to: '/workflows', label: 'Workflows',  icon: GitBranch },
  { to: '/executions',label: 'Executions', icon: PlayCircle },
  { to: '/templates', label: 'Templates',  icon: Layers, badge: 'New' },
  { to: '/settings',  label: 'Settings',   icon: Settings },
]

interface SidebarProps {
  mobileOpen: boolean
  onMobileClose: () => void
}

const Sidebar = memo(({ mobileOpen, onMobileClose }: SidebarProps) => {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()

  const handleLogout = () => {
    // Placeholder — wire to auth context
    navigate('/login')
  }

  return (
    <>
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 md:hidden"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar panel */}
      <aside
        role="navigation"
        aria-label="Main navigation"
        className={clsx(
          'fixed inset-y-0 left-0 z-30 flex flex-col bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 transition-all duration-300',
          collapsed ? 'w-16' : 'w-64',
          // Mobile: slide in/out
          mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
        )}
      >
        {/* Logo */}
        <div className={clsx('flex items-center gap-3 px-4 h-16 border-b border-gray-200 dark:border-gray-700 shrink-0', collapsed && 'justify-center px-2')}>
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary-500 shrink-0">
            <Zap size={18} className="text-white" />
          </div>
          {!collapsed && (
            <span className="font-semibold text-gray-900 dark:text-white text-sm truncate">
              Agent Orchestrator
            </span>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 px-2" aria-label="Primary navigation">
          <ul role="list" className="space-y-1">
            {NAV_ITEMS.map(({ to, label, icon: Icon, badge }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  onClick={onMobileClose}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                      'min-h-[44px]',
                      collapsed && 'justify-center px-2',
                      isActive
                        ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                        : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white',
                    )
                  }
                  aria-label={collapsed ? label : undefined}
                  title={collapsed ? label : undefined}
                >
                  <Icon size={20} className="shrink-0" />
                  {!collapsed && (
                    <span className="flex-1 flex items-center justify-between">
                      {label}
                      {badge && (
                        <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-primary-500 text-white leading-none">
                          {badge}
                        </span>
                      )}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* User profile */}
        <div className={clsx('border-t border-gray-200 dark:border-gray-700 p-3', collapsed && 'flex flex-col items-center gap-2')}>
          {!collapsed && (
            <div className="flex items-center gap-3 px-2 py-2 rounded-lg">
              <div
                className="w-8 h-8 rounded-full bg-primary-500 flex items-center justify-center text-white text-sm font-semibold shrink-0"
                aria-hidden="true"
              >
                A
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">Anas Ansari</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate">Admin</p>
              </div>
            </div>
          )}

          <button
            onClick={handleLogout}
            className={clsx(
              'flex items-center gap-2 w-full rounded-lg px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600 dark:hover:text-red-400 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]',
              collapsed && 'justify-center px-2',
            )}
            aria-label="Log out"
            title={collapsed ? 'Log out' : undefined}
          >
            <LogOut size={18} className="shrink-0" />
            {!collapsed && <span>Log out</span>}
          </button>
        </div>

        {/* Collapse toggle (desktop only) */}
        <button
          onClick={() => setCollapsed(v => !v)}
          className="hidden md:flex absolute -right-3 top-20 w-6 h-6 items-center justify-center rounded-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-500 hover:text-gray-900 dark:hover:text-white shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
        </button>
      </aside>
    </>
  )
})

Sidebar.displayName = 'Sidebar'
export default Sidebar
