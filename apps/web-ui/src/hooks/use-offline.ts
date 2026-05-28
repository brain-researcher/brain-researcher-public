/**
 * React hook for offline functionality in Brain Researcher
 * Provides comprehensive offline state management and capabilities
 */

'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { serviceEndpoints } from '@/lib/service-endpoints';

interface UseOfflineReturn {
  // Connection state
  isOffline: boolean;
  isOnline: boolean;
  isOnlineAgain: boolean;
  
  // Connection info
  connectionType: string | null;
  effectiveType: string | null;
  downlink: number | null;
  rtt: number | null;
  
  // Offline duration tracking
  offlineDuration: number;
  onlineAgainDuration: number;
  lastOnline: Date | null;
  lastOffline: Date | null;
  
  // Offline capabilities
  canWorkOffline: boolean;
  offlineFeatures: string[];
  
  // Sync status
  hasPendingSync: boolean;
  pendingSyncCount: number;
  lastSyncTime: Date | null;
  
  // Actions
  checkConnection: () => Promise<boolean>;
  forceSyncWhenOnline: () => Promise<void>;
  queueOfflineAction: (action: OfflineAction) => void;
  clearOfflineQueue: () => void;
  
  // Storage estimates
  storageUsage: StorageEstimate | null;
  canStoreOffline: boolean;
}

interface OfflineAction {
  id: string;
  type: string;
  data: any;
  timestamp: Date;
  retryCount: number;
  maxRetries: number;
}

interface ConnectionInfo {
  type: string | null;
  effectiveType: string | null;
  downlink: number | null;
  rtt: number | null;
}

export function useOffline(): UseOfflineReturn {
  const [isOffline, setIsOffline] = useState(typeof window !== 'undefined' ? !navigator.onLine : false);
  const [isOnlineAgain, setIsOnlineAgain] = useState(false);
  const [connectionInfo, setConnectionInfo] = useState<ConnectionInfo>({
    type: null,
    effectiveType: null,
    downlink: null,
    rtt: null
  });
  const [offlineDuration, setOfflineDuration] = useState(0);
  const [onlineAgainDuration, setOnlineAgainDuration] = useState(0);
  const [lastOnline, setLastOnline] = useState<Date | null>(null);
  const [lastOffline, setLastOffline] = useState<Date | null>(null);
  const [pendingSyncCount, setPendingSyncCount] = useState(0);
  const [lastSyncTime, setLastSyncTime] = useState<Date | null>(null);
  const [storageUsage, setStorageUsage] = useState<StorageEstimate | null>(null);
  const [offlineQueue, setOfflineQueue] = useState<OfflineAction[]>([]);

  const offlineStartTime = useRef<Date | null>(null);
  const onlineAgainStartTime = useRef<Date | null>(null);
  const durationInterval = useRef<NodeJS.Timeout | null>(null);
  const onlineAgainTimeout = useRef<NodeJS.Timeout | null>(null);
  const processOfflineQueueRef = useRef<(() => Promise<void>) | null>(null);

  // Initialize connection info
  useEffect(() => {
    if (typeof window === 'undefined') return;
    
    const updateConnectionInfo = () => {
      const connection = (navigator as any).connection || 
                        (navigator as any).mozConnection || 
                        (navigator as any).webkitConnection;
      
      if (connection) {
        setConnectionInfo({
          type: connection.type || null,
          effectiveType: connection.effectiveType || null,
          downlink: connection.downlink || null,
          rtt: connection.rtt || null
        });
      }
    };

    updateConnectionInfo();

    // Listen for connection changes
    const connection = (navigator as any).connection || 
                      (navigator as any).mozConnection || 
                      (navigator as any).webkitConnection;
    
    if (connection) {
      connection.addEventListener('change', updateConnectionInfo);
      return () => connection.removeEventListener('change', updateConnectionInfo);
    }
  }, []);

  // Handle online/offline events
  useEffect(() => {
    if (typeof window === 'undefined') return;
    
    const handleOnline = () => {
      const now = new Date();
      setIsOffline(false);
      setIsOnlineAgain(true);
      setLastOnline(now);
      
      // Calculate offline duration
      if (offlineStartTime.current) {
        setOfflineDuration(now.getTime() - offlineStartTime.current.getTime());
        offlineStartTime.current = null;
      }
      
      // Start online again timer
      onlineAgainStartTime.current = now;
      
      // Clear online again flag after 5 seconds
      onlineAgainTimeout.current = setTimeout(() => {
        setIsOnlineAgain(false);
        onlineAgainStartTime.current = null;
      }, 5000);
      
      // Stop duration tracking
      if (durationInterval.current) {
        clearInterval(durationInterval.current);
        durationInterval.current = null;
      }
      
      // Process offline queue when back online
      processOfflineQueueRef.current?.();
    };

    const handleOffline = () => {
      const now = new Date();
      setIsOffline(true);
      setIsOnlineAgain(false);
      setLastOffline(now);
      
      // Start offline duration tracking
      offlineStartTime.current = now;
      
      // Start duration interval
      durationInterval.current = setInterval(() => {
        if (offlineStartTime.current) {
          setOfflineDuration(Date.now() - offlineStartTime.current.getTime());
        }
      }, 1000);
      
      // Clear online again timeout
      if (onlineAgainTimeout.current) {
        clearTimeout(onlineAgainTimeout.current);
        onlineAgainTimeout.current = null;
      }
    };

    // Set initial state
    if (typeof window !== 'undefined' && navigator.onLine) {
      setLastOnline(new Date());
    } else if (typeof window !== 'undefined' && !navigator.onLine) {
      handleOffline();
    }

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      
      if (durationInterval.current) {
        clearInterval(durationInterval.current);
      }
      if (onlineAgainTimeout.current) {
        clearTimeout(onlineAgainTimeout.current);
      }
    };
  }, []);

  // Update online again duration
  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    if (isOnlineAgain && onlineAgainStartTime.current) {
      interval = setInterval(() => {
        setOnlineAgainDuration(Date.now() - onlineAgainStartTime.current!.getTime());
      }, 1000);
    }
    
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isOnlineAgain]);

  // Load offline queue from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem('br-offline-queue');
      if (stored) {
        const queue = JSON.parse(stored);
        // Convert timestamp strings back to Date objects
        const parsedQueue = queue.map((action: any) => ({
          ...action,
          timestamp: new Date(action.timestamp)
        }));
        setOfflineQueue(parsedQueue);
        setPendingSyncCount(parsedQueue.length);
      }
    } catch (error) {
      console.warn('Failed to load offline queue:', error);
    }
  }, []);

  // Save offline queue to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('br-offline-queue', JSON.stringify(offlineQueue));
      setPendingSyncCount(offlineQueue.length);
    } catch (error) {
      console.warn('Failed to save offline queue:', error);
    }
  }, [offlineQueue]);

  // Check storage usage
  useEffect(() => {
    const checkStorageUsage = async () => {
      if ('storage' in navigator && 'estimate' in navigator.storage) {
        try {
          const estimate = await navigator.storage.estimate();
          setStorageUsage(estimate);
        } catch (error) {
          console.warn('Failed to get storage estimate:', error);
        }
      }
    };

    checkStorageUsage();
    
    // Update storage usage every 30 seconds
    const interval = setInterval(checkStorageUsage, 30000);
    return () => clearInterval(interval);
  }, []);

  // Check pending sync with service worker
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
    const interval = setInterval(checkPendingSync, 10000); // Check every 10s
    return () => clearInterval(interval);
  }, []);

  // Check connection function
  const checkConnection = useCallback(async (): Promise<boolean> => {
    try {
      // Try to fetch a small resource
      const response = await fetch(serviceEndpoints.orchestrator('/api/ping'), {
        method: 'HEAD',
        cache: 'no-cache'
      });
      return response.ok;
    } catch {
      return false;
    }
  }, []);

  // Process offline queue when back online
  const processOfflineQueue = useCallback(async () => {
    if (offlineQueue.length === 0) return;

    const processedActions: string[] = [];
    
    for (const action of offlineQueue) {
      try {
        // Process different types of offline actions
        switch (action.type) {
          case 'api-request':
            await fetch(action.data.url, {
              method: action.data.method,
              headers: action.data.headers,
              body: action.data.body
            });
            break;
            
          case 'analysis-save':
            await fetch(serviceEndpoints.orchestrator('/api/analysis/save'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(action.data)
            });
            break;

          case 'settings-update':
            await fetch(serviceEndpoints.orchestrator('/api/settings'), {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(action.data)
            });
            break;
            
          default:
            console.warn('Unknown offline action type:', action.type);
        }
        
        processedActions.push(action.id);
        console.log('Processed offline action:', action.id);
      } catch (error) {
        console.error('Failed to process offline action:', action.id, error);
        
        // Increment retry count
        action.retryCount++;
        
        // Remove if max retries reached
        if (action.retryCount >= action.maxRetries) {
          processedActions.push(action.id);
          console.warn('Max retries reached for offline action:', action.id);
        }
      }
    }

    // Remove processed actions from queue
    setOfflineQueue(prev => prev.filter(action => !processedActions.includes(action.id)));
    setLastSyncTime(new Date());
  }, [offlineQueue]);

  useEffect(() => {
    processOfflineQueueRef.current = processOfflineQueue;
  }, [processOfflineQueue]);

  // Force sync when online
  const forceSyncWhenOnline = useCallback(async () => {
    if (isOffline) {
      throw new Error('Cannot sync while offline');
    }
    
    await processOfflineQueue();
    
    // Trigger service worker background sync if available
    if ('serviceWorker' in navigator) {
      try {
        const registration = await navigator.serviceWorker.ready;
        // Background Sync API - may not be available in all browsers
        if ('sync' in registration) {
          await (registration as unknown as { sync: { register: (tag: string) => Promise<void> } }).sync.register('sync-offline-data');
        }
      } catch (error) {
        console.warn('Failed to register background sync:', error);
      }
    }
  }, [isOffline, processOfflineQueue]);

  // Queue offline action
  const queueOfflineAction = useCallback((action: Omit<OfflineAction, 'id' | 'timestamp' | 'retryCount'>) => {
    const newAction: OfflineAction = {
      ...action,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
      retryCount: 0,
      maxRetries: action.maxRetries || 3
    };
    
    setOfflineQueue(prev => [...prev, newAction]);
    console.log('Queued offline action:', newAction.id);
  }, []);

  // Clear offline queue
  const clearOfflineQueue = useCallback(() => {
    setOfflineQueue([]);
    localStorage.removeItem('br-offline-queue');
  }, []);

  // Determine offline capabilities
  const offlineFeatures = [
    'Browse Datasets',
    'View Analysis Results',
    'Brain Atlas Navigation',
    'Settings Management',
    'Cached Visualizations'
  ];

  const canWorkOffline = storageUsage !== null && (storageUsage.usage || 0) > 1024 * 1024; // At least 1MB cached
  const canStoreOffline = storageUsage !== null && 
    (storageUsage.quota || 0) - (storageUsage.usage || 0) > 10 * 1024 * 1024; // At least 10MB free

  return {
    isOffline,
    isOnline: !isOffline,
    isOnlineAgain,
    connectionType: connectionInfo.type,
    effectiveType: connectionInfo.effectiveType,
    downlink: connectionInfo.downlink,
    rtt: connectionInfo.rtt,
    offlineDuration,
    onlineAgainDuration,
    lastOnline,
    lastOffline,
    canWorkOffline,
    offlineFeatures,
    hasPendingSync: pendingSyncCount > 0,
    pendingSyncCount,
    lastSyncTime,
    checkConnection,
    forceSyncWhenOnline,
    queueOfflineAction,
    clearOfflineQueue,
    storageUsage,
    canStoreOffline
  };
}

export default useOffline;
