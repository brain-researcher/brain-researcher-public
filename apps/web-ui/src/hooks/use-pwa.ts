/**
 * React hook for PWA functionality in Brain Researcher
 * Provides comprehensive Progressive Web App state management
 */

'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import pwaManager, { PWAManager, PWAInstallPromptEvent, PWACapabilities, PWAMetrics } from '@/lib/pwa-manager';

interface UsePWAReturn {
  // Installation state
  isInstalled: boolean;
  isStandalone: boolean;
  canInstall: boolean;
  installPrompt: PWAInstallPromptEvent | null;
  
  // Update state
  hasUpdate: boolean;
  isUpdating: boolean;
  
  // Installation actions
  install: () => Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  update: () => Promise<void>;
  
  // PWA capabilities
  capabilities: PWACapabilities;
  metrics: PWAMetrics;
  
  // Utility functions
  share: (data: { title?: string; text?: string; url?: string }) => Promise<void>;
  clearCaches: () => Promise<void>;
  getCacheStats: () => Promise<Record<string, number>>;
  
  // State
  isOnline: boolean;
  isLoading: boolean;
  error: string | null;
}

export function usePWA(): UsePWAReturn {
  const [isInstalled, setIsInstalled] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [canInstall, setCanInstall] = useState(false);
  const [installPrompt, setInstallPrompt] = useState<PWAInstallPromptEvent | null>(null);
  const [hasUpdate, setHasUpdate] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [capabilities, setCapabilities] = useState<PWACapabilities>({} as PWACapabilities);
  const [metrics, setMetrics] = useState<PWAMetrics>({} as PWAMetrics);
  const [isOnline, setIsOnline] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initialize PWA state
  useEffect(() => {
    const initializePWA = async () => {
      try {
        setIsLoading(true);
        
        // Wait for PWA manager to initialize
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Get initial state
        setIsInstalled(pwaManager.isAppInstalled);
        setIsStandalone(pwaManager.isStandaloneMode);
        setCanInstall(pwaManager.canInstall);
        setHasUpdate(pwaManager.hasUpdate);
        setCapabilities(pwaManager.appCapabilities);
        setMetrics(pwaManager.appMetrics);
        setIsOnline(navigator.onLine);
        
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'PWA initialization failed');
      } finally {
        setIsLoading(false);
      }
    };

    initializePWA();
  }, []);

  // Setup PWA event listeners
  useEffect(() => {
    const handleInstallPromptReady = () => {
      setCanInstall(true);
      setInstallPrompt(pwaManager.canInstall ? {} as PWAInstallPromptEvent : null);
    };

    const handleAppInstalled = () => {
      setIsInstalled(true);
      setCanInstall(false);
      setInstallPrompt(null);
    };

    const handleUpdateAvailable = () => {
      setHasUpdate(true);
    };

    const handleOnline = () => {
      setIsOnline(true);
    };

    const handleOffline = () => {
      setIsOnline(false);
    };

    const handleError = (errorData: any) => {
      console.error('PWA Error:', errorData);
      setError('PWA error occurred');
    };

    // Register event listeners
    pwaManager.on('installPromptReady', handleInstallPromptReady);
    pwaManager.on('appInstalled', handleAppInstalled);
    pwaManager.on('updateAvailable', handleUpdateAvailable);
    pwaManager.on('online', handleOnline);
    pwaManager.on('offline', handleOffline);
    pwaManager.on('error', handleError);

    // Cleanup
    return () => {
      pwaManager.off('installPromptReady', handleInstallPromptReady);
      pwaManager.off('appInstalled', handleAppInstalled);
      pwaManager.off('updateAvailable', handleUpdateAvailable);
      pwaManager.off('online', handleOnline);
      pwaManager.off('offline', handleOffline);
      pwaManager.off('error', handleError);
    };
  }, []);

  // Browser online/offline state
  useEffect(() => {
    const handleOnlineChange = () => {
      setIsOnline(navigator.onLine);
    };

    window.addEventListener('online', handleOnlineChange);
    window.addEventListener('offline', handleOnlineChange);

    return () => {
      window.removeEventListener('online', handleOnlineChange);
      window.removeEventListener('offline', handleOnlineChange);
    };
  }, []);

  // Installation function
  const install = useCallback(async () => {
    try {
      setError(null);
      const result = await pwaManager.install();
      
      if (result.outcome === 'accepted') {
        setIsInstalled(true);
        setCanInstall(false);
        setInstallPrompt(null);
      }
      
      return result;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Installation failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  // Update function
  const update = useCallback(async () => {
    try {
      setIsUpdating(true);
      setError(null);
      await pwaManager.update();
      setHasUpdate(false);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Update failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    } finally {
      setIsUpdating(false);
    }
  }, []);

  // Share function
  const share = useCallback(async (data: { title?: string; text?: string; url?: string }) => {
    try {
      setError(null);
      await pwaManager.share(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Share failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  // Clear caches function
  const clearCaches = useCallback(async () => {
    try {
      setError(null);
      await pwaManager.clearCaches();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Cache clearing failed';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  // Get cache stats function
  const getCacheStats = useCallback(async () => {
    try {
      setError(null);
      return await pwaManager.getCacheStats();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to get cache stats';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  return {
    isInstalled,
    isStandalone,
    canInstall,
    installPrompt,
    hasUpdate,
    isUpdating,
    install,
    update,
    capabilities,
    metrics,
    share,
    clearCaches,
    getCacheStats,
    isOnline,
    isLoading,
    error
  };
}

export default usePWA;