'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { 
  Menu, Home, Search, BarChart3, Settings,
  X, ChevronLeft, Share, Download, Bell,
  Wifi, WifiOff, Battery, BatteryLow,
  Smartphone, RefreshCw, ArrowUp
} from 'lucide-react'
import { useRouter, usePathname } from 'next/navigation'

interface MobileAppShellProps {
  children: React.ReactNode
  title?: string
  showBackButton?: boolean
  onBack?: () => void
}

export function MobileAppShell({
  children,
  title = 'Brain Researcher',
  showBackButton = false,
  onBack
}: MobileAppShellProps) {
  const router = useRouter()
  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isOnline, setIsOnline] = useState(true)
  const [batteryLevel, setBatteryLevel] = useState(100)
  const [isInstalled, setIsInstalled] = useState(false)
  const [showInstallPrompt, setShowInstallPrompt] = useState(false)
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null)
  const [showScrollTop, setShowScrollTop] = useState(false)
  const [updateAvailable, setUpdateAvailable] = useState(false)

  // Navigation items
  const navItems = [
    { icon: Home, label: 'Dashboard', path: '/' },
    { icon: Search, label: 'Search', path: '/search' },
    { icon: BarChart3, label: 'Analysis', path: '/analysis' },
    { icon: Settings, label: 'Settings', path: '/settings' }
  ]

  // Check if app is installed
  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches) {
      setIsInstalled(true)
    }

    // Check if running in iOS Safari
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    const isInStandaloneMode = ('standalone' in window.navigator) && (window.navigator as any).standalone
    if (isIOS && !isInStandaloneMode) {
      setTimeout(() => setShowInstallPrompt(true), 3000)
    }
  }, [])

  // Monitor online/offline status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Monitor battery status
  useEffect(() => {
    if ('getBattery' in navigator) {
      (navigator as any).getBattery().then((battery: any) => {
        setBatteryLevel(Math.round(battery.level * 100))
        
        battery.addEventListener('levelchange', () => {
          setBatteryLevel(Math.round(battery.level * 100))
        })
      })
    }
  }, [])

  // Install PWA prompt
  useEffect(() => {
    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e)
      if (!isInstalled) {
        setShowInstallPrompt(true)
      }
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt)

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt)
    }
  }, [isInstalled])

  // Service Worker updates
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').then(reg => {
        reg.addEventListener('updatefound', () => {
          const newWorker = reg.installing
          if (newWorker) {
            newWorker.addEventListener('statechange', () => {
              if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                setUpdateAvailable(true)
              }
            })
          }
        })
      })
    }
  }, [])

  // Scroll to top button
  useEffect(() => {
    const handleScroll = () => {
      setShowScrollTop(window.scrollY > 300)
    }

    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return

    deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    
    if (outcome === 'accepted') {
      setIsInstalled(true)
    }
    
    setDeferredPrompt(null)
    setShowInstallPrompt(false)
  }, [deferredPrompt])

  const handleUpdate = useCallback(() => {
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'SKIP_WAITING' })
      window.location.reload()
    }
  }, [])

  const scrollToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  const handleShare = useCallback(async () => {
    if (navigator.share) {
      try {
        await navigator.share({
          title: 'Brain Researcher',
          text: 'Check out this neuroimaging analysis',
          url: window.location.href
        })
      } catch (err) {
        console.log('Share cancelled or failed')
      }
    }
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Status Bar */}
      <div className="fixed top-0 left-0 right-0 h-6 bg-black text-white text-xs flex items-center justify-between px-4 z-50 md:hidden">
        <div className="flex items-center gap-2">
          <span>{new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        <div className="flex items-center gap-2">
          {!isOnline && <WifiOff className="h-3 w-3" />}
          {batteryLevel < 20 ? (
            <BatteryLow className="h-3 w-3 text-red-400" />
          ) : (
            <Battery className="h-3 w-3" />
          )}
          <span>{batteryLevel}%</span>
        </div>
      </div>

      {/* App Header */}
      <header className="fixed top-6 md:top-0 left-0 right-0 h-14 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 z-40">
        <div className="flex items-center justify-between h-full px-4">
          <div className="flex items-center gap-3">
            {showBackButton ? (
              <button
                onClick={onBack || (() => router.back())}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
            ) : (
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg md:hidden"
              >
                <Menu className="h-5 w-5" />
              </button>
            )}
            <h1 className="text-lg font-semibold truncate">{title}</h1>
          </div>
          
          <div className="flex items-center gap-2">
            <button
              onClick={handleShare}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            >
              <Share className="h-5 w-5" />
            </button>
            <button className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg relative">
              <Bell className="h-5 w-5" />
              <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile Sidebar */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black bg-opacity-50" onClick={() => setSidebarOpen(false)} />
          <div className="absolute left-0 top-0 bottom-0 w-72 bg-white dark:bg-gray-800 shadow-xl">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Menu</h2>
                <button
                  onClick={() => setSidebarOpen(false)}
                  className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>
            
            <nav className="p-4">
              {navItems.map(item => {
                const Icon = item.icon
                const isActive = pathname === item.path
                
                return (
                  <button
                    key={item.path}
                    onClick={() => {
                      router.push(item.path)
                      setSidebarOpen(false)
                    }}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg mb-1 ${
                      isActive
                        ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                        : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </nav>

            {/* Offline Indicator */}
            {!isOnline && (
              <div className="mx-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                <div className="flex items-center gap-2 text-yellow-600 dark:text-yellow-400">
                  <WifiOff className="h-4 w-4" />
                  <span className="text-sm">Offline Mode</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="pt-20 md:pt-14 pb-20 md:pb-0">
        {children}
      </main>

      {/* Bottom Navigation (Mobile) */}
      <nav className="fixed bottom-0 left-0 right-0 h-16 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 md:hidden z-30">
        <div className="flex items-center justify-around h-full">
          {navItems.map(item => {
            const Icon = item.icon
            const isActive = pathname === item.path
            
            return (
              <button
                key={item.path}
                onClick={() => router.push(item.path)}
                className={`flex flex-col items-center justify-center flex-1 h-full ${
                  isActive ? 'text-blue-600 dark:text-blue-400' : 'text-gray-500 dark:text-gray-400'
                }`}
              >
                <Icon className="h-5 w-5 mb-1" />
                <span className="text-xs">{item.label}</span>
              </button>
            )
          })}
        </div>
      </nav>

      {/* Install Prompt */}
      {showInstallPrompt && !isInstalled && (
        <div className="fixed bottom-20 left-4 right-4 md:bottom-4 md:left-auto md:right-4 md:w-80 bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 z-40">
          <div className="flex items-start gap-3">
            <Smartphone className="h-5 w-5 text-blue-500 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-medium mb-1">Install App</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                Install Brain Researcher for a better experience
              </p>
              <div className="flex gap-2">
                <button
                  onClick={handleInstall}
                  className="flex-1 px-3 py-1.5 bg-blue-500 text-white rounded text-sm"
                >
                  Install
                </button>
                <button
                  onClick={() => setShowInstallPrompt(false)}
                  className="flex-1 px-3 py-1.5 bg-gray-100 dark:bg-gray-700 rounded text-sm"
                >
                  Later
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Update Available */}
      {updateAvailable && (
        <div className="fixed top-20 left-4 right-4 md:top-16 md:left-auto md:right-4 md:w-80 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 z-40">
          <div className="flex items-center gap-3">
            <RefreshCw className="h-5 w-5 text-green-600 dark:text-green-400" />
            <div className="flex-1">
              <p className="text-sm font-medium text-green-800 dark:text-green-200">
                Update available
              </p>
            </div>
            <button
              onClick={handleUpdate}
              className="px-3 py-1 bg-green-600 text-white rounded text-sm"
            >
              Update
            </button>
          </div>
        </div>
      )}

      {/* Scroll to Top */}
      {showScrollTop && (
        <button
          onClick={scrollToTop}
          className="fixed bottom-24 right-4 md:bottom-8 p-3 bg-blue-500 text-white rounded-full shadow-lg z-30"
        >
          <ArrowUp className="h-5 w-5" />
        </button>
      )}
    </div>
  )
}