'use client'

import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import {
  Brain, Menu, X, ChevronDown, Bell,
  Settings, LogOut, User, HelpCircle,
  FolderOpen, MessageSquare, Network, BookOpen, GitBranch, Activity, BarChart3, Wrench, Award, Plug, PlayCircle,
  Sun, Moon, Monitor
} from 'lucide-react'
import Link from 'next/link'
import { useRouter, usePathname } from 'next/navigation'
import { SearchAutocomplete } from '@/components/search/search-autocomplete'
import { ConnectionStatus } from '@/components/status/ConnectionStatus'
import { HelpSystem } from '@/components/help'
import { WorkspaceSwitcher } from '@/components/workspace/workspace-switcher'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import { isPublicPath } from '@/lib/auth/public-paths'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import type { NotificationItem } from '@/types/user'
import { formatDistanceToNow } from 'date-fns'

interface NavItem {
  label: string
  href: string
  icon?: React.ElementType
  badge?: number
}

interface HeaderUser {
  name: string
  email: string
  avatar?: string
  role?: string
}

interface NavigationHeaderProps {
  user?: HeaderUser | null
  onLogout?: () => void
  showSearch?: boolean
  showConnectionStatus?: boolean
  fixed?: boolean
}

interface NavigationLinksProps {
  navItems: NavItem[]
  advancedItems: NavItem[]
  advancedMode: boolean
  pathname: string | null
  resolveNavHref: (href: string) => string
}

const NavigationLinks = React.memo(function NavigationLinks({
  navItems,
  advancedItems,
  advancedMode,
  pathname,
  resolveNavHref,
}: NavigationLinksProps) {
  return (
    <nav className="hidden md:flex items-center gap-1" data-tour="navigation" data-help="navigation">
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive =
          pathname === item.href ||
          (pathname ? pathname.startsWith(`${item.href}/`) : false)
        const isStudio = item.href.endsWith('/studio')
        const href = resolveNavHref(item.href)

        return (
          <Link
            key={item.href}
            href={href}
            className={`px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors ${
              isActive
                ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
            data-tour={isStudio ? 'chat' : undefined}
            data-help={isStudio ? 'chat' : undefined}
            data-testid={`nav-${item.label.toLowerCase()}`}
          >
            {Icon && <Icon className="h-4 w-4" />}
            {item.label}
            {item.badge && item.badge > 0 && (
              <span className="ml-1 px-2 py-0.5 bg-red-500 text-white text-xs rounded-full">
                {item.badge}
              </span>
            )}
          </Link>
        )
      })}

      {advancedMode ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              <Wrench className="h-4 w-4" />
              Advanced
              <ChevronDown className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuLabel>Advanced</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {advancedItems.map((item) => {
              const Icon = item.icon
              const href = resolveNavHref(item.href)
              return (
                <DropdownMenuItem key={item.href} asChild>
                  <Link href={href} className="flex items-center gap-2">
                    {Icon ? <Icon className="h-4 w-4" /> : null}
                    <span>{item.label}</span>
                  </Link>
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </nav>
  )
})

export function NavigationHeader({
  user,
  onLogout,
  showSearch = true,
  showConnectionStatus = true,
  fixed = true
}: NavigationHeaderProps) {
  const { enabled: advancedMode } = useAdvancedMode()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [notificationsLoading, setNotificationsLoading] = useState(false)
  const [notificationsError, setNotificationsError] = useState<string | null>(null)
  const [notificationsEndpointStatus, setNotificationsEndpointStatus] = useState<
    'unknown' | 'supported' | 'unsupported'
  >(() => brainResearcherAPI.getNotificationsEndpointStatus())
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('system')
  
  const router = useRouter()
  const pathname = usePathname()
  const userMenuRef = useRef<HTMLDivElement>(null)
  const notificationsRef = useRef<HTMLDivElement>(null)

  const navItems: NavItem[] = [
    { label: 'Studio', href: '/studio', icon: MessageSquare },
    { label: 'Datasets', href: '/datasets', icon: FolderOpen },
    { label: 'Workflows', href: '/library', icon: BookOpen },
    { label: 'Demos', href: '/demos', icon: PlayCircle },
    { label: 'Knowledge Graph', href: '/kg', icon: Network },
    { label: 'MCP', href: '/mcp/setup', icon: Plug },
  ]

  const advancedItems: NavItem[] = [
    { label: 'Dashboard', href: '/dashboard', icon: BarChart3 },
    { label: 'Execution', href: '/pipeline', icon: Activity },
    { label: 'Pipeline Builder', href: '/pipeline-builder', icon: GitBranch },
    { label: 'Tool Catalog', href: '/library/tools', icon: Wrench },
    { label: 'Status', href: '/status', icon: BarChart3 },
    { label: 'Benchmark', href: '/benchmark', icon: Award },
  ]

  const isAuthenticated = Boolean(user)
  const resolveNavHref = useCallback(
    (href: string) => {
      if (isAuthenticated) return href

      if (isPublicPath(href)) return href
      return `/auth/login?callbackUrl=${encodeURIComponent(href)}`
    },
    [isAuthenticated],
  )
  const fetchNotifications = useCallback(async () => {
    if (!user) {
      setNotifications([])
      return
    }

    const currentEndpointStatus = brainResearcherAPI.getNotificationsEndpointStatus()
    if (currentEndpointStatus === 'unsupported') {
      setNotificationsEndpointStatus('unsupported')
      setNotifications([])
      setNotificationsError(null)
      return
    }

    setNotificationsLoading(true)
    setNotificationsError(null)

    try {
      const response = await brainResearcherAPI.getUserNotifications(9)
      setNotifications(response.notifications)
      const nextEndpointStatus =
        response.endpointStatus ?? brainResearcherAPI.getNotificationsEndpointStatus()
      setNotificationsEndpointStatus(nextEndpointStatus)
    } catch (error) {
      console.error('Failed to load notifications:', error)
      setNotificationsError(
        error instanceof Error ? error.message : 'Failed to load notifications'
      )
    } finally {
      setNotificationsLoading(false)
    }
  }, [user])

  useEffect(() => {
    if (!user) {
      setNotifications([])
      setNotificationsError(null)
      setNotificationsEndpointStatus('unknown')
    }
  }, [user])

  const unreadCount = useMemo(
    () => notifications.filter(notification => !notification.read).length,
    [notifications]
  )

  const formatTimestamp = useCallback(
    (timestamp: string) => formatDistanceToNow(new Date(timestamp), { addSuffix: true }),
    []
  )

  // Handle click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false)
      }
      if (notificationsRef.current && !notificationsRef.current.contains(event.target as Node)) {
        setNotificationsOpen(false)
      }
    }
    
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Handle theme change
  const handleThemeChange = (newTheme: 'light' | 'dark' | 'system') => {
    setTheme(newTheme)
    
    // Apply theme
    if (newTheme === 'system') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      document.documentElement.classList.toggle('dark', prefersDark)
    } else {
      document.documentElement.classList.toggle('dark', newTheme === 'dark')
    }
    
    localStorage.setItem('theme', newTheme)
  }

  const handleNotificationToggle = () => {
    const next = !notificationsOpen
    setNotificationsOpen(next)
    if (next && user && !notificationsLoading && notificationsEndpointStatus !== 'unsupported') {
      fetchNotifications()
    }
  }

  // Mark notification as read
  const markNotificationAsRead = async (id: string, actionUrl?: string | null) => {
    setNotifications(prev =>
      prev.map(notification =>
        notification.id === id ? { ...notification, read: true } : notification
      )
    )

    try {
      await brainResearcherAPI.markNotificationsRead([id])
    } catch (error) {
      console.error('Failed to mark notification as read:', error)
    }

    if (actionUrl) {
      setNotificationsOpen(false)
      router.push(actionUrl)
    }
  }

  return (
    <header className={`${fixed ? 'fixed top-0 left-0 right-0 z-50' : ''} bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800`}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo and Navigation */}
          <div className="flex items-center gap-8">
            {/* Logo */}
            <Link href="/" className="flex items-center gap-2">
              <Brain className="h-8 w-8 text-blue-500" />
              <span className="text-xl font-bold text-gray-900 dark:text-white">
                Brain Researcher
              </span>
            </Link>

            <NavigationLinks
              navItems={navItems}
              advancedItems={advancedItems}
              advancedMode={advancedMode}
              pathname={pathname}
              resolveNavHref={resolveNavHref}
            />
          </div>

          {/* Search Bar (Desktop) */}
          {showSearch && (
            <div className="hidden md:block flex-1 max-w-lg mx-8" data-tour="search" data-help="search">
              <SearchAutocomplete />
            </div>
          )}

          {/* Right Side Actions */}
          <div className="flex items-center gap-2">
            {/* Help System */}
            <HelpSystem showHelpButton={true} />
            {/* Global Health Indicator */}
            {showConnectionStatus ? (
              <div className="hidden md:block">
                <ConnectionStatus
                  showDetails={false}
                  checkInterval={60000}
                  className="w-[210px] shrink-0"
                />
              </div>
            ) : null}

            {/* Workspace */}
            <WorkspaceSwitcher />
            
            {/* Notifications */}
            <div className="relative" ref={notificationsRef}>
              <button
                onClick={handleNotificationToggle}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg relative disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!user}
              >
                <Bell className="h-5 w-5 text-gray-600 dark:text-gray-400" />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-xs font-semibold text-white">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>
              
              {/* Notifications Dropdown */}
              {notificationsOpen && (
                <div className="absolute right-0 mt-2 w-80 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700">
                  <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                    <h3 className="font-semibold text-gray-900 dark:text-white">
                      Notifications
                    </h3>
                  </div>
                  <div className="max-h-96 overflow-y-auto">
                    {notificationsLoading ? (
                      <div className="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
                        Loading notifications…
                      </div>
                    ) : notificationsEndpointStatus === 'unsupported' ? (
                      <div className="p-6 text-sm text-gray-500 dark:text-gray-400">
                        Notifications are not available in this environment.
                      </div>
                    ) : notificationsError ? (
                      <div className="p-6 text-sm text-red-600 dark:text-red-400">
                        {notificationsError}
                      </div>
                    ) : notifications.length > 0 ? (
                      notifications.map((notification) => (
                        <button
                          key={notification.id}
                          onClick={() => markNotificationAsRead(notification.id, notification.actionUrl)}
                          className={`w-full px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-700 ${
                            !notification.read ? 'bg-blue-50 dark:bg-blue-900/10' : ''
                          }`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                {notification.title}
                              </p>
                              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                                {notification.message}
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                                <span>{notification.createdAt ? formatTimestamp(notification.createdAt) : 'Just now'}</span>
                                {(notification.priority === 'high' || notification.priority === 'urgent') && (
                                  <>
                                    <span>•</span>
                                    <span className="text-red-500 dark:text-red-400 capitalize">
                                      {notification.priority}
                                    </span>
                                  </>
                                )}
                                {notification.type && (
                                  <>
                                    <span>•</span>
                                    <span className="capitalize text-gray-500 dark:text-gray-400">
                                      {notification.type.replace(/_/g, ' ')}
                                    </span>
                                  </>
                                )}
                              </div>
                              {notification.actionText && notification.actionUrl && (
                                <div className="mt-2 text-xs font-medium text-blue-600 dark:text-blue-400">
                                  {notification.actionText}
                                </div>
                              )}
                            </div>
                            {!notification.read && (
                              <div className="w-2 h-2 bg-blue-500 rounded-full mt-1.5 flex-shrink-0" />
                            )}
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                        You're all caught up.
                      </div>
                    )}
                  </div>
                  <div className="p-3 border-t border-gray-200 dark:border-gray-700">
                    <button
                      className="w-full text-center text-sm text-blue-500 hover:text-blue-600 disabled:text-gray-400 disabled:cursor-not-allowed"
                      onClick={() => fetchNotifications()}
                      disabled={
                        notificationsLoading ||
                        !user ||
                        notificationsEndpointStatus === 'unsupported'
                      }
                    >
                      {notificationsEndpointStatus === 'unsupported'
                        ? 'Notifications unavailable'
                        : 'Refresh notifications'}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* User Menu */}
            {user ? (
              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setUserMenuOpen(!userMenuOpen)}
                  className="flex items-center gap-2 p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
                >
                  <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-blue-600 rounded-full flex items-center justify-center text-white text-sm font-medium">
                    {(user.name || user.email || 'U').charAt(0).toUpperCase()}
                  </div>
                  <ChevronDown className="h-4 w-4 text-gray-500 hidden sm:block" />
                </button>
                
                {/* User Dropdown */}
                {userMenuOpen && (
                  <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700">
                    <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                      <p className="font-medium text-gray-900 dark:text-white">
                        {user.name || user.email || 'User'}
                      </p>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {user.email || ''}
                      </p>
                    </div>
                    
                    <div className="p-2">
                      <Link
                        href="/profile"
                        className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md"
                      >
                        <User className="h-4 w-4" />
                        Profile
                      </Link>
                      <Link
                        href="/settings"
                        className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md"
                      >
                        <Settings className="h-4 w-4" />
                        Settings
                      </Link>
                      <Link
                        href="/help"
                        className="flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md"
                      >
                        <HelpCircle className="h-4 w-4" />
                        Help & Support
                      </Link>
                    </div>
                    
                    <div className="p-2 border-t border-gray-200 dark:border-gray-700">
                      <div className="px-3 py-2">
                        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Theme</p>
                        <div className="flex gap-1">
                          <button
                            onClick={() => handleThemeChange('light')}
                            className={`p-2 rounded ${theme === 'light' ? 'bg-gray-200 dark:bg-gray-700' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                            title="Light"
                          >
                            <Sun className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleThemeChange('dark')}
                            className={`p-2 rounded ${theme === 'dark' ? 'bg-gray-200 dark:bg-gray-700' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                            title="Dark"
                          >
                            <Moon className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleThemeChange('system')}
                            className={`p-2 rounded ${theme === 'system' ? 'bg-gray-200 dark:bg-gray-700' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                            title="System"
                          >
                            <Monitor className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                    
                    <div className="p-2 border-t border-gray-200 dark:border-gray-700">
                      <button
                        onClick={onLogout}
                        className="flex items-center gap-3 w-full px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md"
                      >
                        <LogOut className="h-4 w-4" />
                        Sign out
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                {(() => {
                  const target = pathname && !pathname.startsWith('/auth') ? pathname : '/'
                  const loginHref = `/auth/login?callbackUrl=${encodeURIComponent(target)}`
                  return (
                    <Link
                      href={loginHref}
                      className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
                    >
                      Sign in
                    </Link>
                  )
                })()}
                <Link
                  href="/auth/signup"
                  className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-lg"
                >
                  Open Studio
                </Link>
              </div>
            )}

            {/* Mobile Menu Button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
            >
              {mobileMenuOpen ? (
                <X className="h-6 w-6 text-gray-600 dark:text-gray-400" />
              ) : (
                <Menu className="h-6 w-6 text-gray-600 dark:text-gray-400" />
              )}
            </button>
          </div>
        </div>

        {/* Mobile Search */}
        {showSearch && (
          <div className="md:hidden pb-3">
            <SearchAutocomplete />
          </div>
        )}
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800">
          <nav className="px-4 py-2">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive =
                pathname === item.href ||
                (pathname ? pathname.startsWith(`${item.href}/`) : false)
              const href = resolveNavHref(item.href)
              
              return (
                <Link
                  key={item.href}
                  href={href}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`flex items-center gap-3 px-3 py-2 rounded-md text-base font-medium ${
                    isActive
                      ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  {Icon && <Icon className="h-5 w-5" />}
                  {item.label}
                  {item.badge && item.badge > 0 && (
                    <span className="ml-auto px-2 py-0.5 bg-red-500 text-white text-xs rounded-full">
                      {item.badge}
                    </span>
                  )}
                </Link>
              )
            })}

            {advancedMode ? (
              <div className="mt-2 border-t border-gray-200 dark:border-gray-800 pt-2">
                <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Advanced
                </div>
                {advancedItems.map((item) => {
                  const Icon = item.icon
                  const isActive =
                    pathname === item.href ||
                    (pathname ? pathname.startsWith(`${item.href}/`) : false)
                  const href = resolveNavHref(item.href)
                  return (
                    <Link
                      key={item.href}
                      href={href}
                      onClick={() => setMobileMenuOpen(false)}
                      className={`flex items-center gap-3 px-3 py-2 rounded-md text-base font-medium ${
                        isActive
                          ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                          : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                      }`}
                    >
                      {Icon ? <Icon className="h-5 w-5" /> : null}
                      {item.label}
                    </Link>
                  )
                })}
              </div>
            ) : null}
          </nav>
        </div>
      )}
    </header>
  )
}
