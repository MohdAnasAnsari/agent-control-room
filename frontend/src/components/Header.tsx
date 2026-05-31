import { memo, useState, useRef, useEffect, useCallback } from 'react'
import { useLocation, Link } from 'react-router-dom'
import {
  Menu,
  Search,
  Bell,
  Settings,
  Sun,
  Moon,
  ChevronDown,
  User,
  LogOut,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import type { Theme } from '../types'

const ROUTE_LABELS: Record<string, string> = {
  '/': 'Dashboard',
  '/agents': 'Agents',
  '/workflows': 'Workflows',
  '/executions': 'Executions',
  '/settings': 'Settings',
}

function useBreadcrumbs(pathname: string) {
  const segments = pathname.split('/').filter(Boolean)
  const crumbs = [{ label: 'Home', to: '/' }]
  let current = ''
  for (const seg of segments) {
    current += `/${seg}`
    crumbs.push({ label: ROUTE_LABELS[current] ?? (seg.length > 8 ? `${seg.slice(0, 8)}…` : seg), to: current })
  }
  return crumbs
}

interface HeaderProps {
  theme: Theme
  onThemeToggle: () => void
  onMobileMenuToggle: () => void
  sidebarCollapsed?: boolean
}

const Header = memo(({ theme, onThemeToggle, onMobileMenuToggle }: HeaderProps) => {
  const { pathname } = useLocation()
  const breadcrumbs = useBreadcrumbs(pathname)
  const [searchValue, setSearchValue] = useState('')
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  // Close user menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Keyboard: Esc closes menus
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setUserMenuOpen(false)
      searchRef.current?.blur()
    }
  }, [])

  return (
    <header
      className="sticky top-0 z-10 flex items-center gap-4 h-16 px-4 md:px-6 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700"
      onKeyDown={handleKeyDown}
      role="banner"
    >
      {/* Mobile hamburger */}
      <button
        className="md:hidden flex items-center justify-center w-11 h-11 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
        onClick={onMobileMenuToggle}
        aria-label="Open navigation menu"
        aria-expanded={false}
      >
        <Menu size={20} />
      </button>

      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="hidden sm:flex items-center gap-1 text-sm min-w-0">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.to} className="flex items-center gap-1">
            {i > 0 && <span className="text-gray-400 dark:text-gray-600">/</span>}
            {i === breadcrumbs.length - 1 ? (
              <span className="font-medium text-gray-900 dark:text-white truncate" aria-current="page">
                {crumb.label}
              </span>
            ) : (
              <Link
                to={crumb.to}
                className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
              >
                {crumb.label}
              </Link>
            )}
          </span>
        ))}
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search */}
      <div className="relative hidden sm:flex items-center">
        <Search size={16} className="absolute left-3 text-gray-400 pointer-events-none" aria-hidden="true" />
        <input
          ref={searchRef}
          type="search"
          placeholder="Search…"
          value={searchValue}
          onChange={e => setSearchValue(e.target.value)}
          className="pl-9 pr-8 py-2 w-48 lg:w-64 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
          aria-label="Search"
        />
        {searchValue && (
          <button
            onClick={() => setSearchValue('')}
            className="absolute right-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            aria-label="Clear search"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Icon actions */}
      <div className="flex items-center gap-1">
        {/* Theme toggle */}
        <button
          onClick={onThemeToggle}
          className="flex items-center justify-center w-10 h-10 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {/* Notifications */}
        <button
          className="relative flex items-center justify-center w-10 h-10 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          aria-label="Notifications (3 unread)"
        >
          <Bell size={18} />
          <span
            className="absolute top-2 right-2 w-2 h-2 rounded-full bg-red-500"
            aria-hidden="true"
          />
        </button>

        {/* Settings link */}
        <Link
          to="/settings"
          className={clsx(
            'flex items-center justify-center w-10 h-10 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
            pathname === '/settings' && 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400',
          )}
          aria-label="Settings"
        >
          <Settings size={18} />
        </Link>

        {/* User menu */}
        <div className="relative" ref={userMenuRef}>
          <button
            onClick={() => setUserMenuOpen(v => !v)}
            className="flex items-center gap-2 ml-1 rounded-lg px-2 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 min-h-[44px]"
            aria-label="User menu"
            aria-expanded={userMenuOpen}
            aria-haspopup="menu"
          >
            <div className="w-7 h-7 rounded-full bg-primary-500 flex items-center justify-center text-white text-xs font-semibold shrink-0" aria-hidden="true">
              A
            </div>
            <span className="hidden lg:block">Anas</span>
            <ChevronDown size={14} className={clsx('hidden lg:block transition-transform', userMenuOpen && 'rotate-180')} aria-hidden="true" />
          </button>

          {/* Dropdown */}
          {userMenuOpen && (
            <div
              role="menu"
              aria-label="User menu"
              className="absolute right-0 mt-1 w-48 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-lg py-1 z-50"
            >
              <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700">
                <p className="text-sm font-medium text-gray-900 dark:text-white">Anas Ansari</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Admin</p>
              </div>
              <Link
                to="/settings"
                role="menuitem"
                className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                onClick={() => setUserMenuOpen(false)}
              >
                <User size={14} />
                Profile
              </Link>
              <button
                role="menuitem"
                className="flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                onClick={() => setUserMenuOpen(false)}
              >
                <LogOut size={14} />
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
})

Header.displayName = 'Header'
export default Header
