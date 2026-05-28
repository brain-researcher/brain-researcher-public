/**
 * Offline Indicator Component for Brain Researcher PWA
 * Provides visual feedback about connectivity status and offline capabilities
 */

'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  WifiIcon,
  SignalSlashIcon,
  CloudArrowUpIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
  ClockIcon,
  ArrowPathIcon
} from '@heroicons/react/24/outline';
import { cn } from '@/lib/utils';
import { useOffline } from '@/hooks/use-offline';
import { serviceEndpoints } from '@/lib/service-endpoints';

interface OfflineIndicatorProps {
  className?: string;
  position?: 'top' | 'bottom' | 'floating';
  showWhenOnline?: boolean;
  autoHide?: boolean;
  autoHideDelay?: number;
}

interface OfflineCapability {
  name: string;
  available: boolean;
  description: string;
}

export function OfflineIndicator({
  className,
  position = 'top',
  showWhenOnline = false,
  autoHide = true,
  autoHideDelay = 3000
}: OfflineIndicatorProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [pendingSyncCount, setPendingSyncCount] = useState(0);
  const [offlineCapabilities, setOfflineCapabilities] = useState<OfflineCapability[]>([]);
  const [lastSyncTime, setLastSyncTime] = useState<Date | null>(null);
  const [isVisible, setIsVisible] = useState(true);
  
  const { 
    isOffline, 
    isOnlineAgain, 
    offlineDuration, 
    connectionType,
    lastOnline 
  } = useOffline();

  // Auto-hide logic
  useEffect(() => {
    if (!autoHide || isOffline) return;

    const timer = setTimeout(() => {
      if (!isExpanded) {
        setIsVisible(false);
      }
    }, autoHideDelay);

    return () => clearTimeout(timer);
  }, [isOffline, autoHide, autoHideDelay, isExpanded]);

  // Show when coming back online or going offline
  useEffect(() => {
    if (isOffline || isOnlineAgain) {
      setIsVisible(true);
    }
  }, [isOffline, isOnlineAgain]);

  // Check pending sync items
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
            setPendingSyncCount(event.data.count || 0);
            if (event.data.lastSync) {
              setLastSyncTime(new Date(event.data.lastSync));
            }
          };
        } catch (error) {
          console.warn('Failed to check pending sync:', error);
        }
      }
    };

    checkPendingSync();
    const interval = setInterval(checkPendingSync, 5000); // Check every 5s

    return () => clearInterval(interval);
  }, []);

  // Check offline capabilities
  useEffect(() => {
    const checkOfflineCapabilities = async () => {
      const capabilities: OfflineCapability[] = [
        {
          name: 'Browse Datasets',
          available: true,
          description: 'View previously loaded brain datasets'
        },
        {
          name: 'Analysis Results',
          available: pendingSyncCount > 0 || lastSyncTime !== null,
          description: 'Access cached analysis results'
        },
        {
          name: 'Brain Atlases',
          available: true,
          description: 'View anatomical brain regions'
        },
        {
          name: 'New Analysis',
          available: false,
          description: 'Requires internet connection'
        }
      ];

      // Check service worker cache for more specific capabilities
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        try {
          const channel = new MessageChannel();
          navigator.serviceWorker.controller.postMessage(
            { type: 'GET_OFFLINE_STATUS' },
            [channel.port2]
          );

          channel.port1.onmessage = (event) => {
            const { capabilities: swCapabilities } = event.data;
            if (swCapabilities) {
              capabilities[0].available = swCapabilities.brainData;
              capabilities[1].available = swCapabilities.analysisResults;
              capabilities[2].available = swCapabilities.imagingData;
            }
          };
        } catch (error) {
          console.warn('Failed to check offline capabilities:', error);
        }
      }

      setOfflineCapabilities(capabilities);
    };

    checkOfflineCapabilities();
  }, [pendingSyncCount, lastSyncTime]);

  const handleRetryConnection = () => {
    // Force a connectivity check by making a small request
    fetch(serviceEndpoints.orchestrator('/api/ping'), { method: 'HEAD' })
      .then(() => {
        // Connection restored
        console.log('Connection restored');
      })
      .catch(() => {
        // Still offline
        console.log('Still offline');
      });
  };

  const handleSyncNow = async () => {
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
      try {
        // Register background sync (Background Sync API not in standard TS types)
        const registration = await navigator.serviceWorker.ready;
        await (registration as any).sync?.register('sync-offline-data');
        
        console.log('Background sync registered');
      } catch (error) {
        console.error('Failed to register background sync:', error);
      }
    }
  };

  const formatOfflineDuration = (duration: number): string => {
    const minutes = Math.floor(duration / (1000 * 60));
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ${hours % 24}h`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m`;
    return 'Just now';
  };

  const getConnectionQuality = (): { level: string; color: string; description: string } => {
    if (isOffline) {
      return { level: 'offline', color: 'red', description: 'No connection' };
    }

    if (connectionType) {
      switch (connectionType) {
        case 'slow-2g':
        case '2g':
          return { level: 'slow', color: 'orange', description: 'Slow connection' };
        case '3g':
          return { level: 'medium', color: 'yellow', description: 'Medium speed' };
        case '4g':
        case 'wifi':
          return { level: 'fast', color: 'green', description: 'Fast connection' };
        default:
          return { level: 'unknown', color: 'blue', description: 'Connected' };
      }
    }

    return { level: 'online', color: 'green', description: 'Online' };
  };

  // Don't render if online and showWhenOnline is false and not expanded
  if (!isOffline && !showWhenOnline && !isExpanded && !isVisible) {
    return null;
  }

  const connectionQuality = getConnectionQuality();
  const positionClasses = {
    top: 'top-16',
    bottom: 'bottom-20',
    floating: 'top-1/2 transform -translate-y-1/2'
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0, y: position === 'bottom' ? 50 : -50 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: position === 'bottom' ? 50 : -50 }}
          className={cn(
            'fixed left-4 right-4 z-40 max-w-sm mx-auto',
            positionClasses[position],
            className
          )}
        >
          <div
            className={cn(
              'bg-white border rounded-lg shadow-lg overflow-hidden',
              isOffline ? 'border-amber-200' : 'border-green-200'
            )}
          >
            {/* Main Status Bar */}
            <div
              className={cn(
                'px-4 py-3 cursor-pointer',
                isOffline 
                  ? 'bg-amber-50 hover:bg-amber-100' 
                  : 'bg-green-50 hover:bg-green-100'
              )}
              onClick={() => setIsExpanded(!isExpanded)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  {/* Status Icon */}
                  <div className={cn(
                    'w-2 h-2 rounded-full',
                    isOffline ? 'bg-amber-500' : 'bg-green-500'
                  )} />
                  
                  {/* Connection Icon */}
                  {isOffline ? (
                    <SignalSlashIcon className="w-5 h-5 text-amber-600" />
                  ) : (
                    <WifiIcon className="w-5 h-5 text-green-600" />
                  )}

                  {/* Status Text */}
                  <div className="min-w-0 flex-1">
                    <div className={cn(
                      'text-sm font-medium',
                      isOffline ? 'text-amber-900' : 'text-green-900'
                    )}>
                      {isOffline ? 'Working Offline' : connectionQuality.description}
                    </div>
                    {isOffline && offlineDuration > 0 && (
                      <div className="text-xs text-amber-700">
                        {formatOfflineDuration(offlineDuration)}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  {/* Pending Sync Badge */}
                  {pendingSyncCount > 0 && (
                    <div className="flex items-center space-x-1 bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                      <CloudArrowUpIcon className="w-3 h-3" />
                      <span>{pendingSyncCount}</span>
                    </div>
                  )}

                  {/* Expand/Collapse Arrow */}
                  <motion.div
                    animate={{ rotate: isExpanded ? 180 : 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </motion.div>
                </div>
              </div>
            </div>

            {/* Expanded Details */}
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-t border-gray-100"
                >
                  <div className="p-4 space-y-4">
                    {/* Connection Actions */}
                    {isOffline && (
                      <div className="flex space-x-2">
                        <button
                          onClick={handleRetryConnection}
                          className="flex-1 flex items-center justify-center space-x-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
                        >
                          <ArrowPathIcon className="w-4 h-4" />
                          <span>Retry Connection</span>
                        </button>
                        
                        {pendingSyncCount > 0 && (
                          <button
                            onClick={handleSyncNow}
                            className="flex items-center space-x-1 px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200 transition-colors"
                          >
                            <CloudArrowUpIcon className="w-4 h-4" />
                            <span>Sync</span>
                          </button>
                        )}
                      </div>
                    )}

                    {/* Offline Capabilities */}
                    <div>
                      <div className="text-xs font-medium text-gray-700 mb-2">
                        {isOffline ? 'Available Offline:' : 'Offline Capabilities:'}
                      </div>
                      <div className="space-y-2">
                        {offlineCapabilities.map((capability, index) => (
                          <div
                            key={index}
                            className="flex items-center justify-between text-xs"
                          >
                            <div className="flex items-center space-x-2">
                              {capability.available ? (
                                <CheckCircleIcon className="w-4 h-4 text-green-600" />
                              ) : (
                                <ExclamationTriangleIcon className="w-4 h-4 text-gray-400" />
                              )}
                              <span className={cn(
                                capability.available ? 'text-gray-900' : 'text-gray-500'
                              )}>
                                {capability.name}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Last Sync Info */}
                    {lastSyncTime && (
                      <div className="flex items-center space-x-2 text-xs text-gray-600 pt-2 border-t border-gray-100">
                        <ClockIcon className="w-4 h-4" />
                        <span>
                          Last sync: {lastSyncTime.toLocaleTimeString()}
                        </span>
                      </div>
                    )}

                    {/* Connection Details */}
                    {!isOffline && connectionType && (
                      <div className="text-xs text-gray-600 pt-2 border-t border-gray-100">
                        Connection: {connectionType.toUpperCase()}
                        {lastOnline && (
                          <span className="ml-2">
                            • Last offline: {formatOfflineDuration(Date.now() - lastOnline.getTime())} ago
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default OfflineIndicator;
