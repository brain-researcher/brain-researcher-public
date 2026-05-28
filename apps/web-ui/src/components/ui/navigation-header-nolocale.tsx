'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { 
  Brain, 
  Database, 
  FolderOpen,
  MessageSquare, 
  BarChart3, 
  Menu, 
  X, 
  Search,
  User,
  Settings,
  Bell,
  HelpCircle,
  LogOut,
  ChevronDown,
  FileText,
  BookOpen,
  Sparkles,
  Network,
  Activity,
  GitBranch,
  Wrench
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger 
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'

export interface NavigationItem {
  id: string
  label: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  description?: string
  badge?: string
  external?: boolean
}

export interface NavigationHeaderProps {
  className?: string
  showSearch?: boolean
  showUserMenu?: boolean
  showNotifications?: boolean
  user?: {
    name: string
    email: string
    avatar?: string
  }
  onLogoClick?: () => void
  onSearchSubmit?: (query: string) => void
  onLogout?: () => void
  onLogin?: () => void
  customActions?: React.ReactNode
}

export function NavigationHeaderNoLocale({
  className = '',
  showSearch = true,
  showUserMenu = true,
  showNotifications = true,
  user,
  onLogoClick,
  onSearchSubmit,
  onLogout,
  onLogin,
  customActions
}: NavigationHeaderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { enabled: advancedMode } = useAdvancedMode()
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Navigation items without translations - memoized to prevent re-renders
  const mainNavigation: NavigationItem[] = useMemo(
    () => [
      {
        id: 'studio',
        label: 'Studio',
        href: '/studio',
        icon: MessageSquare,
        description: 'Plan, validate, and hand off neuro workflows',
      },
      {
        id: 'projects',
        label: 'Projects',
        href: '/projects',
        icon: Database,
        description: 'Organize runs, datasets, and results',
      },
      {
        id: 'datasets',
        label: 'Datasets',
        href: '/datasets',
        icon: FolderOpen,
        description: 'Browse and add datasets to a plan',
      },
      {
        id: 'workflows',
        label: 'Workflows',
        href: '/library',
        icon: BookOpen,
        description: 'Official workflows you can validate in Studio',
      },
      {
        id: 'kg',
        label: 'Knowledge Graph',
        href: '/kg',
        icon: Network,
        description: 'Explore graph-backed evidence',
      },
      {
        id: 'runs',
        label: 'Runs',
        href: '/analyses',
        icon: Activity,
        description: 'Review validation runs and completed analyses',
      },
    ],
    [],
  )

  const toolsNavigation = useMemo(
    () => [
      {
        id: 'dashboard',
        label: 'Dashboard',
        href: '/dashboard',
        icon: BarChart3,
        description: 'Internal status and monitoring',
      },
      {
        id: 'pipeline',
        label: 'Execution',
        href: '/pipeline',
        icon: Activity,
        description: 'Internal execution runner',
      },
      {
        id: 'pipeline-builder',
        label: 'Pipeline Builder',
        href: '/pipeline-builder',
        icon: GitBranch,
        description: 'Build custom pipelines',
      },
      {
        id: 'tools',
        label: 'Tool Catalog',
        href: '/library/tools',
        icon: Wrench,
        description: 'Browse the internal tools catalog',
      },
      {
        id: 'status',
        label: 'Status',
        href: '/status',
        icon: BarChart3,
        description: 'Service health and diagnostics',
      },
    ],
    [],
  )

  // Close mobile menu on route change
  useEffect(() => {
    setIsMobileMenuOpen(false)
  }, [pathname])

  const handleLogoClick = () => {
    if (onLogoClick) {
      onLogoClick()
    } else {
      router.push('/')
    }
  }

	  const handleSearchSubmit = (e: React.FormEvent) => {
	    e.preventDefault()
	    if (onSearchSubmit) {
	      onSearchSubmit(searchQuery)
	    } else {
	      router.push(`/datasets?q=${encodeURIComponent(searchQuery)}`)
	    }
	  }

  const handleNavigation = (href: string, external?: boolean) => {
    if (external) {
      window.open(href, '_blank')
    } else {
      router.push(href)
    }
  }

  const isActivePath = (href: string) => {
    // Normalize paths by stripping trailing slashes
    const norm = (s: string) => s.replace(/\/+$/, '')
    const current = norm(pathname)
    const target = norm(href)
    
    if (target === '/') {
      return current === '/'
    }
    return current === target || current.startsWith(target + '/')
  }

  return (
    <header 
      className={`sticky top-0 z-50 w-full border-b bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 ${className}`}
      role="banner"
    >
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <div className="flex items-center">
            <button
              onClick={handleLogoClick}
              className="flex items-center gap-2 hover:bg-transparent p-2"
              aria-label="Brain Researcher - Go to home page"
            >
              <div className="flex items-center gap-3">
                <div className="relative">
                  <Brain className="h-8 w-8 text-primary" />
                  <div className="absolute -top-1 -right-1 w-3 h-3 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full animate-pulse" />
                </div>
                <div className="flex flex-col">
                  <span className="font-bold text-xl hidden sm:block bg-gradient-to-r from-primary to-blue-600 bg-clip-text text-transparent">
                    Brain Researcher
                  </span>
                  <div className="flex items-center gap-2 hidden lg:flex">
                    <Badge variant="secondary" className="text-xs px-2 py-0.5">
                      Beta
                    </Badge>
                    <Badge variant="outline" className="text-xs px-2 py-0.5 text-green-600 border-green-300">
                      v0.0.1
                    </Badge>
                  </div>
                </div>
              </div>
            </button>
          </div>

          {/* Desktop Navigation */}
          <nav 
            id="main-navigation"
            className="flex items-center space-x-1"  // Always visible for debugging
            role="navigation"
            aria-label="Main navigation"
          >
            {mainNavigation.map((item) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    isActivePath(item.href) 
                      ? "bg-primary text-primary-foreground" 
                      : "hover:bg-accent hover:text-accent-foreground"
                  }`}
                  aria-label={`${item.label} - ${item.description}`}
                  aria-current={isActivePath(item.href) ? 'page' : undefined}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                  {item.badge && (
                    <Badge variant="secondary" className="ml-1 text-xs">
                      {item.badge}
                    </Badge>
                  )}
                </Link>
              )
            })}

            {/* Tools Dropdown (Advanced Mode only) */}
            {advancedMode ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center gap-1"
                    suppressHydrationWarning
                  >
                    <Wrench className="h-4 w-4" />
                    Advanced
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-56">
                  <DropdownMenuLabel>Advanced</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {toolsNavigation.map((item) => {
                    const Icon = item.icon
                    return (
                      <DropdownMenuItem key={item.id} asChild>
                        <Link href={item.href} className="flex items-center cursor-pointer">
                          <Icon className="h-4 w-4 mr-2" />
                          <div>
                            <div className="font-medium">{item.label}</div>
                            {item.description ? (
                              <div className="text-xs text-muted-foreground">{item.description}</div>
                            ) : null}
                          </div>
                        </Link>
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}

          </nav>

          {/* Search Bar (Desktop) */}
          {showSearch && (
            <form onSubmit={handleSearchSubmit} className="hidden md:block flex-1 max-w-md mx-4" role="search">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search datasets, papers..."
                className="w-full px-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20"
                aria-label="Search datasets, papers, and analyses"
              />
            </form>
          )}

          {/* Right Actions */}
          <div className="flex items-center gap-2">
            {/* Custom Actions */}
            {customActions}

            {/* Search Button (Mobile) */}
            {showSearch && (
	              <Button
	                variant="ghost"
	                size="sm"
	                className="md:hidden"
	                onClick={() => router.push('/datasets')}
	                aria-label="Open search"
	              >
                <Search className="h-4 w-4" />
              </Button>
            )}

            {/* Notifications */}
            {showNotifications && (
              <Button
                variant="ghost"
                size="sm"
                className="relative"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
              </Button>
            )}

            {/* User Menu */}
            {showUserMenu && (
              user ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="sm" className="flex items-center gap-2" suppressHydrationWarning>
                      <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                        <User className="h-4 w-4 text-primary" />
                      </div>
                      <span className="hidden sm:block">{user.name}</span>
                      <ChevronDown className="h-3 w-3" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuLabel>
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary/20 to-blue-500/20 flex items-center justify-center">
                          <User className="h-5 w-5 text-primary" />
                        </div>
                        <div>
                          <div className="font-medium">{user.name}</div>
                          <div className="text-xs text-muted-foreground">{user.email}</div>
                          <div className="text-xs text-green-600">Online</div>
                        </div>
                      </div>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
	                    <DropdownMenuItem onClick={() => router.push('/profile')}>
	                      <User className="h-4 w-4 mr-2" />
	                      Profile
	                    </DropdownMenuItem>
	                    <DropdownMenuItem onClick={() => router.push('/settings')}>
	                      <Settings className="h-4 w-4 mr-2" />
	                      Settings
	                    </DropdownMenuItem>
	                    <DropdownMenuItem onClick={() => router.push('/docs')}>
	                      <FileText className="h-4 w-4 mr-2" />
	                      Documentation
	                    </DropdownMenuItem>
	                    <DropdownMenuItem onClick={() => router.push('/help')}>
	                      <HelpCircle className="h-4 w-4 mr-2" />
	                      Help & Support
	                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem 
                      className="text-red-600 cursor-pointer"
                      onClick={onLogout}
                    >
                      <LogOut className="h-4 w-4 mr-2" />
                      Sign Out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <div className="flex items-center gap-2">
                  <Button 
                    variant="ghost" 
                    size="sm"
                    onClick={() => onLogin ? onLogin() : router.push('/auth/login')}
                  >
                    Login
                  </Button>
                  <Button 
                    variant="default" 
                    size="sm"
                    onClick={() => router.push('/auth/signup')}
                  >
                    Open Studio
                  </Button>
                </div>
              )
            )}

            {/* Mobile Menu */}
            <Sheet open={isMobileMenuOpen} onOpenChange={setIsMobileMenuOpen}>
              <SheetTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="lg:hidden"
                  aria-label="Open menu"
                >
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="w-80">
                <div className="flex flex-col h-full">
                  {/* Mobile Header */}
                  <div className="flex items-center justify-between p-4 border-b">
                    <div className="flex items-center gap-2">
                      <Brain className="h-6 w-6 text-primary" />
                      <span className="font-bold">Brain Researcher</span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setIsMobileMenuOpen(false)}
                      aria-label="Close menu"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>

                  {/* Mobile Search */}
                  {showSearch && (
                    <div className="p-4 border-b">
                      <form onSubmit={(e) => {
                        handleSearchSubmit(e)
                        setIsMobileMenuOpen(false)
                      }}>
                        <input
                          type="text"
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          placeholder="Search..."
                          className="w-full px-3 py-2 text-sm border rounded-md"
                        />
                      </form>
                    </div>
                  )}

                  {/* Mobile Navigation */}
                  <div className="flex-1 overflow-y-auto">
                    <div className="p-4 space-y-1">
                      <div className="text-sm font-semibold text-muted-foreground mb-2">
                        Main Navigation
                      </div>
                      {mainNavigation.map((item) => (
                        <Button
                          key={item.id}
                          variant={isActivePath(item.href) ? "default" : "ghost"}
                          onClick={() => {
                            handleNavigation(item.href, item.external)
                            setIsMobileMenuOpen(false)
                          }}
                          className="w-full justify-start"
                        >
                          <item.icon className="h-4 w-4 mr-2" />
                          {item.label}
                          {item.badge && (
                            <Badge variant="secondary" className="ml-auto text-xs">
                              {item.badge}
                            </Badge>
                          )}
                        </Button>
                      ))}

                      {advancedMode ? (
                        <>
                          <div className="text-sm font-semibold text-muted-foreground mt-6 mb-2">
                            Tools
                          </div>
                          {toolsNavigation.map((item) => (
                            <Button
                              key={item.id}
                              variant="ghost"
                              onClick={() => {
                                handleNavigation(item.href)
                                setIsMobileMenuOpen(false)
                              }}
                              className="w-full justify-start"
                            >
                              <item.icon className="h-4 w-4 mr-2" />
                              {item.label}
                            </Button>
                          ))}
                        </>
                      ) : null}

                    </div>
                  </div>

                  {/* Mobile Footer */}
                  <div className="p-4 border-t space-y-2">
                    <Button variant="ghost" className="w-full justify-start" onClick={() => router.push('/settings')}>
                      <Settings className="h-4 w-4 mr-2" />
                      Settings
                    </Button>
                    <Button variant="ghost" className="w-full justify-start" onClick={() => router.push('/help')}>
                      <HelpCircle className="h-4 w-4 mr-2" />
                      Help
                    </Button>
                  </div>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </div>
    </header>
  )
}
