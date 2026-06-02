'use client'

import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  Brain, Menu, X, ChevronDown,
  Settings, LogOut, User, HelpCircle,
  Wrench,
  Sun, Moon, Monitor
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
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
import { isPublicPath } from '@/lib/auth/public-paths'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import { advancedNavItems, primaryNavItems, type NavItem } from './navigation-items'

interface HeaderUser {
  name: string
  email: string
  avatar?: string
  role?: string
}

interface NavigationHeaderProps {
  user?: HeaderUser | null
  onLogout?: () => void
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
    <nav className="hidden xl:flex items-center gap-1" data-tour="navigation" data-help="navigation">
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive =
          pathname === item.href ||
          (pathname ? pathname.startsWith(`${item.href}/`) : false)
        const isStudio = item.label === 'Studio'
        const href = resolveNavHref(item.href)

        return (
          <Link
            key={item.href}
            href={href}
            className={`px-2.5 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors ${
              isActive
                ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
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
              className="px-2.5 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
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
  fixed = true
}: NavigationHeaderProps) {
  const { enabled: advancedMode } = useAdvancedMode()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('system')

  const pathname = usePathname()
  const userMenuRef = useRef<HTMLDivElement>(null)

  const navItems = primaryNavItems
  const advancedItems = advancedNavItems

  const isAuthenticated = Boolean(user)
  const resolveNavHref = useCallback(
    (href: string) => {
      if (isAuthenticated) return href

      if (isPublicPath(href)) return href
      return `/auth/login?callbackUrl=${encodeURIComponent(href)}`
    },
    [isAuthenticated],
  )
  // Handle click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false)
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

  return (
    <header className={`${fixed ? 'fixed top-0 left-0 right-0 z-50' : ''} bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800`}>
      <div className="max-w-[88rem] mx-auto px-4 sm:px-6 lg:px-6">
        <div className="flex items-center justify-between h-16 gap-4">
          {/* Logo and Navigation */}
          <div className="flex min-w-0 items-center gap-4 xl:gap-5">
            {/* Logo */}
            <Link href="/" className="flex shrink-0 items-center gap-2">
              <Brain className="h-8 w-8 shrink-0 text-gray-900 dark:text-white" />
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

          {/* Right Side Actions */}
          <div className="flex shrink-0 items-center gap-2">
            {/* Help System */}
            <HelpSystem showHelpButton={true} />

            {/* Workspace */}
            <WorkspaceSwitcher />

            {/* User Menu */}
            {user ? (
              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setUserMenuOpen(!userMenuOpen)}
                  className="flex items-center gap-2 p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
                >
                  <div className="w-8 h-8 bg-gradient-to-br from-gray-700 to-gray-900 rounded-full flex items-center justify-center text-white text-sm font-medium">
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
              <div className="hidden items-center gap-2 sm:flex">
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
                  className="px-4 py-2 bg-gray-900 hover:bg-gray-800 text-white text-sm font-medium rounded-lg"
                >
                  Open Studio
                </Link>
              </div>
            )}

            {/* Mobile Menu Button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="xl:hidden p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
            >
              {mobileMenuOpen ? (
                <X className="h-6 w-6 text-gray-600 dark:text-gray-400" />
              ) : (
                <Menu className="h-6 w-6 text-gray-600 dark:text-gray-400" />
              )}
            </button>
          </div>
        </div>

      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="xl:hidden bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800">
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
                      ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
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
                          ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white'
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
