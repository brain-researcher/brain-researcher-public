'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { 
  Menu, X, Home, Search, BarChart3, Settings, Brain,
  ChevronLeft, ChevronRight, MoreHorizontal, 
  Sun, Moon, Volume2, VolumeX, Wifi, WifiOff,
  User, LogOut, HelpCircle, Bell, Download
} from 'lucide-react'
import { useRouter, usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { routes } from '@/config/routes'

interface NavigationItem {
  id: string
  icon: React.ElementType
  label: string
  path: string
  badge?: number | string
  submenu?: NavigationItem[]
}

interface MobileNavigationProps {
  items?: NavigationItem[]
  onItemClick?: (item: NavigationItem) => void
  showOfflineIndicator?: boolean
  showSettingsPanel?: boolean
  className?: string
}

// Default navigation items for Brain Researcher
const DEFAULT_NAV_ITEMS: NavigationItem[] = [
  { id: 'home', icon: Home, label: 'Home', path: routes.home },
  { id: 'search', icon: Search, label: 'Finder', path: routes.finder },
  { id: 'analytics', icon: BarChart3, label: 'Analytics', path: routes.analytics, badge: 3 },
  { id: 'brain', icon: Brain, label: 'Knowledge Graph', path: routes.knowledgeGraph },
  { id: 'settings', icon: Settings, label: 'Settings', path: routes.settings }
]

/**
 * Touch-optimized mobile navigation with hamburger menu
 * Features: 44x44px touch targets, swipe gestures, accessibility
 */
export function MobileNavigation({
  items = DEFAULT_NAV_ITEMS,
  onItemClick,
  showOfflineIndicator = true,
  showSettingsPanel = true,
  className
}: MobileNavigationProps) {
  const router = useRouter()
  const pathname = usePathname()
  
  const [isOpen, setIsOpen] = useState(false)
  const [activeSubmenu, setActiveSubmenu] = useState<string | null>(null)
  const [isOnline, setIsOnline] = useState(true)
  const [isDarkMode, setIsDarkMode] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(true)
  
  const menuRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  
  // Touch gesture handling
  const [touchStart, setTouchStart] = useState<{ x: number; y: number } | null>(null)
  const [touchEnd, setTouchEnd] = useState<{ x: number; y: number } | null>(null)
  
  const minSwipeDistance = 100

  // Monitor online status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    setIsOnline(navigator.onLine)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Dark mode detection
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    setIsDarkMode(mediaQuery.matches)
    
    const handleChange = (e: MediaQueryListEvent) => setIsDarkMode(e.matches)
    mediaQuery.addEventListener('change', handleChange)
    
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  // Keyboard navigation
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
      
      // Focus management for accessibility
      if (e.key === 'Tab' && isOpen && menuRef.current) {
        const focusableElements = menuRef.current.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
        const firstElement = focusableElements[0] as HTMLElement
        const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement
        
        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault()
          lastElement.focus()
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault()
          firstElement.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeydown)
    return () => document.removeEventListener('keydown', handleKeydown)
  }, [isOpen])

  // Touch gesture handlers
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    setTouchEnd(null)
    setTouchStart({
      x: e.targetTouches[0].clientX,
      y: e.targetTouches[0].clientY
    })
  }, [])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    setTouchEnd({
      x: e.targetTouches[0].clientX,
      y: e.targetTouches[0].clientY
    })
  }, [])

  const handleTouchEnd = useCallback(() => {
    if (!touchStart || !touchEnd) return
    
    const distance = Math.sqrt(
      Math.pow(touchEnd.x - touchStart.x, 2) + Math.pow(touchEnd.y - touchStart.y, 2)
    )
    
    if (distance < minSwipeDistance) return
    
    const isLeftSwipe = touchStart.x - touchEnd.x > minSwipeDistance
    const isRightSwipe = touchEnd.x - touchStart.x > minSwipeDistance
    
    if (isLeftSwipe && isOpen) {
      setIsOpen(false)
    } else if (isRightSwipe && !isOpen) {
      setIsOpen(true)
    }
  }, [touchStart, touchEnd, isOpen, minSwipeDistance])

  const handleItemClick = useCallback((item: NavigationItem, e: React.MouseEvent) => {
    e.preventDefault()
    
    // Haptic feedback if available
    if ('vibrate' in navigator) {
      navigator.vibrate(10)
    }
    
    if (item.submenu) {
      setActiveSubmenu(activeSubmenu === item.id ? null : item.id)
    } else {
      router.push(item.path)
      setIsOpen(false)
      setActiveSubmenu(null)
      
      // Custom callback
      onItemClick?.(item)
    }
  }, [router, activeSubmenu, onItemClick])

  const toggleSettings = useCallback((setting: 'theme' | 'sound') => {
    if (setting === 'theme') {
      setIsDarkMode(!isDarkMode)
      // Apply theme change logic here
      document.documentElement.classList.toggle('dark')
    } else if (setting === 'sound') {
      setSoundEnabled(!soundEnabled)
    }
  }, [isDarkMode, soundEnabled])

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (isOpen && menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  return (
    <>
      {/* Hamburger Menu Button - 44x44px touch target */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'fixed top-4 left-4 z-50 md:hidden',
          'w-11 h-11 bg-white dark:bg-gray-800 rounded-lg shadow-lg',
          'flex items-center justify-center',
          'border border-gray-200 dark:border-gray-700',
          'transition-all duration-200 ease-in-out',
          'hover:bg-gray-50 dark:hover:bg-gray-700',
          'active:scale-95',
          'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
          className
        )}
        aria-label={isOpen ? 'Close navigation menu' : 'Open navigation menu'}
        aria-expanded={isOpen}
      >
        {isOpen ? (
          <X className="h-6 w-6 text-gray-700 dark:text-gray-200" />
        ) : (
          <Menu className="h-6 w-6 text-gray-700 dark:text-gray-200" />
        )}
      </button>

      {/* Overlay */}
      {isOpen && (
        <div
          ref={overlayRef}
          className="fixed inset-0 bg-black bg-opacity-50 z-40 md:hidden"
          onClick={() => setIsOpen(false)}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          aria-hidden="true"
        />
      )}

      {/* Mobile Menu */}
      <nav
        ref={menuRef}
        className={cn(
          'fixed top-0 left-0 h-full w-80 max-w-[85vw] z-50 md:hidden',
          'bg-white dark:bg-gray-800 shadow-xl',
          'transform transition-transform duration-300 ease-in-out',
          'overflow-y-auto overscroll-contain',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
        aria-label="Main navigation"
        role="navigation"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Brain className="h-8 w-8 text-blue-600" />
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Brain Researcher
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Navigation
                </p>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          
          {/* Offline Indicator */}
          {showOfflineIndicator && !isOnline && (
            <div className="mt-3 px-3 py-2 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
              <div className="flex items-center gap-2">
                <WifiOff className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
                <span className="text-sm text-yellow-700 dark:text-yellow-300">
                  You're offline
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Navigation Items */}
        <div className="px-3 py-4">
          {items.map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.path
            const hasSubmenu = item.submenu && item.submenu.length > 0
            const isSubmenuOpen = activeSubmenu === item.id
            
            return (
              <div key={item.id}>
                {/* Main Navigation Item - 44px touch target */}
                <button
                  onClick={(e) => handleItemClick(item, e)}
                  className={cn(
                    'w-full flex items-center gap-4 px-3 py-3 rounded-lg mb-1',
                    'min-h-[44px] transition-colors duration-150',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset',
                    isActive
                      ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800'
                      : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200'
                  )}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <Icon className="h-6 w-6 flex-shrink-0" />
                  <span className="font-medium flex-1 text-left">{item.label}</span>
                  
                  {/* Badge */}
                  {item.badge && (
                    <span className="bg-red-500 text-white text-xs rounded-full px-2 py-0.5 min-w-[20px] h-5 flex items-center justify-center">
                      {item.badge}
                    </span>
                  )}
                  
                  {/* Submenu Indicator */}
                  {hasSubmenu && (
                    <ChevronRight className={cn(
                      'h-5 w-5 transition-transform duration-200',
                      isSubmenuOpen && 'rotate-90'
                    )} />
                  )}
                </button>

                {/* Submenu */}
                {hasSubmenu && isSubmenuOpen && item.submenu && (
                  <div className="ml-6 pl-4 border-l-2 border-gray-200 dark:border-gray-600 mb-2">
                    {item.submenu.map((subItem) => {
                      const SubIcon = subItem.icon
                      const isSubActive = pathname === subItem.path
                      
                      return (
                        <button
                          key={subItem.id}
                          onClick={() => {
                            router.push(subItem.path)
                            setIsOpen(false)
                            onItemClick?.(subItem)
                          }}
                          className={cn(
                            'w-full flex items-center gap-3 px-3 py-2 rounded-lg mb-1',
                            'min-h-[40px] transition-colors duration-150 text-sm',
                            'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset',
                            isSubActive
                              ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                              : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300'
                          )}
                        >
                          <SubIcon className="h-5 w-5 flex-shrink-0" />
                          <span>{subItem.label}</span>
                          {subItem.badge && (
                            <span className="bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[18px] h-4 flex items-center justify-center">
                              {subItem.badge}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Settings Panel */}
        {showSettingsPanel && (
          <div className="px-3 py-4 mt-auto border-t border-gray-200 dark:border-gray-700">
            <h3 className="px-3 text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">
              Quick Settings
            </h3>
            
            <div className="space-y-2">
              {/* Theme Toggle */}
              <button
                onClick={() => toggleSettings('theme')}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 min-h-[40px]"
              >
                {isDarkMode ? (
                  <Sun className="h-5 w-5 text-yellow-500" />
                ) : (
                  <Moon className="h-5 w-5 text-gray-600" />
                )}
                <span className="text-sm">{isDarkMode ? 'Light Mode' : 'Dark Mode'}</span>
              </button>
              
              {/* Sound Toggle */}
              <button
                onClick={() => toggleSettings('sound')}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 min-h-[40px]"
              >
                {soundEnabled ? (
                  <Volume2 className="h-5 w-5 text-green-500" />
                ) : (
                  <VolumeX className="h-5 w-5 text-gray-400" />
                )}
                <span className="text-sm">Sound {soundEnabled ? 'On' : 'Off'}</span>
              </button>
              
              {/* Connection Status */}
              <div className="flex items-center gap-3 px-3 py-2">
                {isOnline ? (
                  <Wifi className="h-5 w-5 text-green-500" />
                ) : (
                  <WifiOff className="h-5 w-5 text-red-500" />
                )}
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  {isOnline ? 'Online' : 'Offline'}
                </span>
              </div>
            </div>
          </div>
        )}
      </nav>
    </>
  )
}

/**
 * Bottom Tab Navigation for mobile - Alternative pattern
 */
export function BottomTabNavigation({
  items = DEFAULT_NAV_ITEMS.slice(0, 5), // Max 5 items for bottom tabs
  className
}: {
  items?: NavigationItem[]
  className?: string
}) {
  const router = useRouter()
  const pathname = usePathname()

  return (
    <nav
      className={cn(
        'fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700',
        'md:hidden z-30 safe-area-inset-bottom',
        className
      )}
      role="navigation"
      aria-label="Bottom navigation"
    >
      <div className="flex items-center justify-around px-2 py-2">
        {items.map((item) => {
          const Icon = item.icon
          const isActive = pathname === item.path
          
          return (
            <button
              key={item.id}
              onClick={() => router.push(item.path)}
              className={cn(
                'flex flex-col items-center justify-center flex-1 py-2 px-1',
                'min-h-[44px] relative transition-colors duration-150',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset rounded-lg',
                isActive
                  ? 'text-blue-600 dark:text-blue-400'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              )}
              aria-current={isActive ? 'page' : undefined}
              aria-label={item.label}
            >
              <Icon className="h-6 w-6 mb-1" />
              <span className="text-xs font-medium leading-none">{item.label}</span>
              
              {/* Badge */}
              {item.badge && (
                <span className="absolute top-1 right-1/4 bg-red-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[18px] h-4 flex items-center justify-center">
                  {item.badge}
                </span>
              )}
              
              {/* Active Indicator */}
              {isActive && (
                <div className="absolute bottom-0 left-1/2 transform -translate-x-1/2 w-1 h-1 bg-blue-600 dark:bg-blue-400 rounded-full" />
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}

export default MobileNavigation
