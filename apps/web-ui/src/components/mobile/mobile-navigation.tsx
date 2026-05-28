/**
 * Mobile Navigation Component for Brain Researcher PWA
 * Optimized for touch interactions and small screens
 */

'use client';

import React, { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  HomeIcon,
  ChartBarIcon,
  BeakerIcon,
  CogIcon,
  UserCircleIcon,
  Bars3Icon,
  XMarkIcon,
  BoltIcon,
  CloudArrowUpIcon,
  WifiIcon,
  SignalSlashIcon
} from '@heroicons/react/24/outline';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useOffline } from '@/hooks/use-offline';
import { usePWA } from '@/hooks/use-pwa';

interface NavigationItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
  requiresOnline?: boolean;
}

interface MobileNavigationProps {
  className?: string;
}

const navigationItems: NavigationItem[] = [
  {
    name: 'Dashboard',
    href: '/',
    icon: HomeIcon,
  },
  {
    name: 'Analysis',
    href: '/analysis',
    icon: BeakerIcon,
    requiresOnline: true,
  },
  {
    name: 'Datasets',
    href: '/datasets',
    icon: ChartBarIcon,
  },
  {
    name: 'Insights',
    href: '/analytics',
    icon: BoltIcon,
  },
  {
    name: 'Settings',
    href: '/settings',
    icon: CogIcon,
  }
];

export function MobileNavigation({ className }: MobileNavigationProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [pendingSync, setPendingSync] = useState(0);
  const pathname = usePathname();
  const router = useRouter();
  const { isOffline } = useOffline();
  const { installPrompt, isInstalled } = usePWA();

  // Close menu when route changes
  useEffect(() => {
    setIsMenuOpen(false);
  }, [pathname]);

  // Handle hardware back button on Android
  useEffect(() => {
    if (!isMenuOpen) return;

    const handleBackButton = (e: PopStateEvent) => {
      e.preventDefault();
      setIsMenuOpen(false);
      history.pushState(null, '', pathname);
    };

    // Push a state when menu opens
    history.pushState(null, '', pathname);
    window.addEventListener('popstate', handleBackButton);

    return () => {
      window.removeEventListener('popstate', handleBackButton);
    };
  }, [isMenuOpen, pathname]);

  // Check for pending sync items
  useEffect(() => {
    const checkPendingSync = async () => {
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        try {
          const channel = new MessageChannel();
          navigator.serviceWorker.controller.postMessage(
            { type: 'GET_PENDING_SYNC' },
            [channel.port2]
          );

          channel.port1.onmessage = (event) => {
            setPendingSync(event.data.count || 0);
          };
        } catch (error) {
          console.warn('Failed to check pending sync:', error);
        }
      }
    };

    checkPendingSync();
    const interval = setInterval(checkPendingSync, 30000); // Check every 30s

    return () => clearInterval(interval);
  }, []);

  const handleMenuToggle = () => {
    setIsMenuOpen(!isMenuOpen);
  };

  const handleItemClick = (item: NavigationItem) => {
    if (item.requiresOnline && isOffline) {
      // Show offline message or queue for later
      return;
    }

    setIsMenuOpen(false);
    router.push(item.href);
  };

  const handleInstallApp = () => {
    if (installPrompt) {
      installPrompt.prompt();
    }
  };

  return (
    <>
      {/* Mobile Header Bar */}
      <div className={cn(
        "fixed top-0 left-0 right-0 z-50 bg-white border-b border-gray-200 shadow-sm",
        "safe-area-inset-top", // Handle notch on newer devices
        className
      )}>
        <div className="flex items-center justify-between px-4 h-14">
          {/* Logo/Brand */}
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <BeakerIcon className="w-5 h-5 text-white" />
            </div>
            <span className="text-lg font-semibold text-gray-900">
              Brain Researcher
            </span>
          </div>

          {/* Status Indicators */}
          <div className="flex items-center space-x-2">
            {/* Offline Indicator */}
            {isOffline && (
              <div className="flex items-center text-amber-600">
                <SignalSlashIcon className="w-5 h-5" />
              </div>
            )}

            {/* Sync Indicator */}
            {pendingSync > 0 && (
              <div className="relative">
                <CloudArrowUpIcon className="w-5 h-5 text-blue-600" />
                <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                  {pendingSync > 9 ? '9+' : pendingSync}
                </span>
              </div>
            )}

            {/* Menu Button */}
            <button
              onClick={handleMenuToggle}
              className="p-2 -mr-2 text-gray-600 hover:text-gray-900 touch-manipulation"
              aria-label="Toggle navigation menu"
            >
              {isMenuOpen ? (
                <XMarkIcon className="w-6 h-6" />
              ) : (
                <Bars3Icon className="w-6 h-6" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu Overlay */}
      <AnimatePresence>
        {isMenuOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40 bg-black bg-opacity-50"
              onClick={() => setIsMenuOpen(false)}
            />

            {/* Menu Panel */}
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'tween', duration: 0.3 }}
              className="fixed top-0 right-0 bottom-0 z-50 w-80 bg-white shadow-2xl overflow-y-auto safe-area-inset-top safe-area-inset-bottom"
            >
              {/* Menu Header */}
              <div className="flex items-center justify-between p-4 border-b border-gray-200">
                <div className="flex items-center space-x-3">
                  <UserCircleIcon className="w-8 h-8 text-gray-600" />
                  <div>
                    <div className="text-sm font-medium text-gray-900">User</div>
                    <div className="text-xs text-gray-500">
                      {isOffline ? 'Offline' : 'Online'}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setIsMenuOpen(false)}
                  className="p-2 text-gray-600 hover:text-gray-900 touch-manipulation"
                >
                  <XMarkIcon className="w-6 h-6" />
                </button>
              </div>

              {/* Navigation Items */}
              <nav className="py-4">
                {navigationItems.map((item) => {
                  const isActive = pathname === item.href || 
                    (item.href !== '/' && pathname.startsWith(item.href));
                  const isDisabled = item.requiresOnline && isOffline;

                  return (
                    <button
                      key={item.name}
                      onClick={() => handleItemClick(item)}
                      disabled={isDisabled}
                      className={cn(
                        "w-full flex items-center space-x-3 px-4 py-3 text-left touch-manipulation",
                        "transition-colors duration-150 ease-in-out",
                        isActive 
                          ? "bg-blue-50 border-r-2 border-blue-600 text-blue-700"
                          : isDisabled
                          ? "text-gray-400"
                          : "text-gray-700 hover:bg-gray-50"
                      )}
                    >
                      <item.icon className={cn(
                        "w-6 h-6 flex-shrink-0",
                        isActive ? "text-blue-600" : isDisabled ? "text-gray-300" : "text-gray-500"
                      )} />
                      <span className={cn(
                        "text-base font-medium",
                        isDisabled && "line-through"
                      )}>
                        {item.name}
                      </span>
                      {item.badge && (
                        <span className="ml-auto bg-red-500 text-white text-xs rounded-full px-2 py-1">
                          {item.badge}
                        </span>
                      )}
                      {isDisabled && (
                        <SignalSlashIcon className="ml-auto w-4 h-4 text-gray-400" />
                      )}
                    </button>
                  );
                })}
              </nav>

              {/* PWA Actions */}
              <div className="border-t border-gray-200 p-4 space-y-3">
                {!isInstalled && installPrompt && (
                  <button
                    onClick={handleInstallApp}
                    className="w-full flex items-center space-x-3 px-4 py-3 bg-blue-600 text-white rounded-lg touch-manipulation hover:bg-blue-700"
                  >
                    <CloudArrowUpIcon className="w-5 h-5" />
                    <span>Install App</span>
                  </button>
                )}

                {/* Offline Status */}
                <div className={cn(
                  "flex items-center space-x-3 px-4 py-2 rounded-lg text-sm",
                  isOffline 
                    ? "bg-amber-50 text-amber-800"
                    : "bg-green-50 text-green-800"
                )}>
                  {isOffline ? (
                    <SignalSlashIcon className="w-4 h-4" />
                  ) : (
                    <WifiIcon className="w-4 h-4" />
                  )}
                  <span>
                    {isOffline ? 'Working offline' : 'Connected'}
                  </span>
                  {pendingSync > 0 && (
                    <span className="ml-auto bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                      {pendingSync} pending
                    </span>
                  )}
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Bottom Navigation Bar */}
      <div className="fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-gray-200 safe-area-inset-bottom">
        <div className="grid grid-cols-5 h-16">
          {navigationItems.slice(0, 5).map((item) => {
            const isActive = pathname === item.href || 
              (item.href !== '/' && pathname.startsWith(item.href));
            const isDisabled = item.requiresOnline && isOffline;

            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "flex flex-col items-center justify-center space-y-1 touch-manipulation",
                  "transition-colors duration-150 ease-in-out",
                  isActive 
                    ? "text-blue-600"
                    : isDisabled
                    ? "text-gray-300 pointer-events-none"
                    : "text-gray-600 hover:text-gray-900"
                )}
                onClick={(e) => {
                  if (isDisabled) {
                    e.preventDefault();
                  }
                }}
              >
                <div className="relative">
                  <item.icon className="w-5 h-5" />
                  {item.badge && (
                    <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                      {item.badge > 9 ? '9+' : item.badge}
                    </span>
                  )}
                  {isDisabled && (
                    <SignalSlashIcon className="absolute -bottom-1 -right-1 w-3 h-3 text-amber-500" />
                  )}
                </div>
                <span className="text-xs font-medium truncate max-w-full">
                  {item.name}
                </span>
              </Link>
            );
          })}
        </div>
      </div>

      {/* Spacers for fixed positioning */}
      <div className="h-14" /> {/* Top spacer */}
      <div className="h-16" /> {/* Bottom spacer */}
    </>
  );
}

export default MobileNavigation;