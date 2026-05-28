/**
 * PWA Manager for Brain Researcher
 * Comprehensive Progressive Web App management utilities
 */

import { serviceEndpoints } from '@/lib/service-endpoints'

export interface PWAInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export interface PWACapabilities {
  serviceWorker: boolean;
  installPrompt: boolean;
  pushNotifications: boolean;
  backgroundSync: boolean;
  indexedDB: boolean;
  cacheAPI: boolean;
  webShare: boolean;
  screenOrientation: boolean;
  fullscreen: boolean;
  standalone: boolean;
}

export interface PWAMetrics {
  installDate?: Date;
  launchCount: number;
  totalUsageTime: number;
  offlineUsageTime: number;
  cacheHitRate: number;
  syncEvents: number;
  crashCount: number;
}

export interface PWAConfig {
  enableAutoUpdate: boolean;
  enableBackgroundSync: boolean;
  enablePushNotifications: boolean;
  cacheStrategy: 'aggressive' | 'conservative' | 'adaptive';
  maxCacheSize: number;
  preloadCriticalResources: string[];
}

class PWAManager {
  private installPromptEvent: PWAInstallPromptEvent | null = null;
  private isInstalled = false;
  private isStandalone = false;
  private serviceWorkerRegistration: ServiceWorkerRegistration | null = null;
  private updateAvailable = false;
  private config: PWAConfig;
  private metrics: PWAMetrics;
  private capabilities: PWACapabilities;
  private listeners: Map<string, Function[]> = new Map();

  constructor(config: Partial<PWAConfig> = {}) {
    this.config = {
      enableAutoUpdate: true,
      enableBackgroundSync: true,
      enablePushNotifications: false,
      cacheStrategy: 'adaptive',
      maxCacheSize: 50 * 1024 * 1024, // 50MB
      preloadCriticalResources: [],
      ...config
    };

    this.metrics = this.loadMetrics();
    this.capabilities = this.detectCapabilities();

    if (typeof window !== 'undefined') {
      this.initialize();
    }
  }

  /**
   * Initialize PWA manager
   */
  private async initialize(): Promise<void> {
    try {
      // Detect installation status
      this.detectInstallationStatus();

      // Register service worker
      await this.registerServiceWorker();

      // Setup install prompt listener
      this.setupInstallPromptListener();

      // Setup app lifecycle listeners
      this.setupLifecycleListeners();

      // Initialize metrics tracking
      this.initializeMetricsTracking();

      // Preload critical resources
      if (this.config.preloadCriticalResources.length > 0) {
        await this.preloadResources(this.config.preloadCriticalResources);
      }

      console.log('[PWA Manager] Initialized successfully');
    } catch (error) {
      console.error('[PWA Manager] Initialization failed:', error);
    }
  }

  /**
   * Detect PWA capabilities
   */
  private detectCapabilities(): PWACapabilities {
    const capabilities: PWACapabilities = {
      serviceWorker: 'serviceWorker' in navigator,
      installPrompt: 'BeforeInstallPromptEvent' in window || 'onbeforeinstallprompt' in window,
      pushNotifications: 'PushManager' in window && 'Notification' in window,
      backgroundSync: 'serviceWorker' in navigator && 'sync' in window.ServiceWorkerRegistration.prototype,
      indexedDB: 'indexedDB' in window,
      cacheAPI: 'caches' in window,
      webShare: 'share' in navigator,
      screenOrientation: 'screen' in window && 'orientation' in (window.screen as any),
      fullscreen: 'requestFullscreen' in document.documentElement,
      standalone: window.matchMedia('(display-mode: standalone)').matches ||
                  (window.navigator as any).standalone === true
    };

    return capabilities;
  }

  /**
   * Detect if app is installed
   */
  private detectInstallationStatus(): void {
    this.isStandalone = this.capabilities.standalone;
    
    // Check for iOS Safari standalone mode
    const isIOSStandalone = (window.navigator as any).standalone === true;
    
    // Check for Android/Desktop PWA
    const isDisplayModeStandalone = window.matchMedia('(display-mode: standalone)').matches;
    
    this.isInstalled = isIOSStandalone || isDisplayModeStandalone;

    // Update metrics if first install
    if (this.isInstalled && !this.metrics.installDate) {
      this.metrics.installDate = new Date();
      this.saveMetrics();
    }
  }

  /**
   * Register service worker
   */
  private async registerServiceWorker(): Promise<void> {
    if (!this.capabilities.serviceWorker) {
      console.warn('[PWA Manager] Service Worker not supported');
      return;
    }

    try {
      this.serviceWorkerRegistration = await navigator.serviceWorker.register(
        '/service-worker.js',
        { scope: '/' }
      );

      console.log('[PWA Manager] Service Worker registered successfully');

      // Listen for updates
      this.serviceWorkerRegistration.addEventListener('updatefound', () => {
        const newWorker = this.serviceWorkerRegistration!.installing;
        if (newWorker) {
          newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
              this.updateAvailable = true;
              this.emit('updateAvailable');
            }
          });
        }
      });

      // Setup message listener for service worker
      navigator.serviceWorker.addEventListener('message', (event) => {
        this.handleServiceWorkerMessage(event.data);
      });

    } catch (error) {
      console.error('[PWA Manager] Service Worker registration failed:', error);
    }
  }

  /**
   * Setup install prompt listener
   */
  private setupInstallPromptListener(): void {
    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      this.installPromptEvent = event as PWAInstallPromptEvent;
      this.emit('installPromptReady');
    });

    // iOS install detection
    window.addEventListener('appinstalled', () => {
      this.installPromptEvent = null;
      this.isInstalled = true;
      this.metrics.installDate = new Date();
      this.saveMetrics();
      this.emit('appInstalled');
    });
  }

  /**
   * Setup app lifecycle listeners
   */
  private setupLifecycleListeners(): void {
    let sessionStart = Date.now();
    let isOnline = navigator.onLine;

    // Track app usage time
    const updateUsageTime = () => {
      const sessionTime = Date.now() - sessionStart;
      if (isOnline) {
        this.metrics.totalUsageTime += sessionTime;
      } else {
        this.metrics.offlineUsageTime += sessionTime;
      }
      sessionStart = Date.now();
      this.saveMetrics();
    };

    // Online/offline events
    window.addEventListener('online', () => {
      if (!isOnline) {
        updateUsageTime();
        isOnline = true;
        this.emit('online');
      }
    });

    window.addEventListener('offline', () => {
      if (isOnline) {
        updateUsageTime();
        isOnline = false;
        this.emit('offline');
      }
    });

    // App visibility changes
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        updateUsageTime();
        this.emit('appHidden');
      } else {
        sessionStart = Date.now();
        this.metrics.launchCount++;
        this.saveMetrics();
        this.emit('appVisible');
      }
    });

    // Before unload
    window.addEventListener('beforeunload', updateUsageTime);

    // Error tracking
    window.addEventListener('error', (event) => {
      this.metrics.crashCount++;
      this.saveMetrics();
      this.emit('error', { error: event.error, filename: event.filename, lineno: event.lineno });
    });
  }

  /**
   * Initialize metrics tracking
   */
  private initializeMetricsTracking(): void {
    // Track cache performance
    if (this.capabilities.cacheAPI) {
      this.trackCachePerformance();
    }

    // Track background sync events
    if (this.capabilities.backgroundSync) {
      navigator.serviceWorker.ready.then(registration => {
        // This would be handled by the service worker
      });
    }

    // Send metrics periodically
    setInterval(() => {
      this.reportMetrics();
    }, 5 * 60 * 1000); // Every 5 minutes
  }

  /**
   * Track cache performance
   */
  private trackCachePerformance(): void {
    // Override fetch to track cache hits/misses
    const originalFetch = window.fetch;
    let totalRequests = 0;
    let cacheHits = 0;

    window.fetch = async (...args) => {
      totalRequests++;
      const response = await originalFetch(...args);
      
      // Check if response came from cache
      if (response.headers.get('x-cache') === 'HIT' || 
          response.headers.get('cf-cache-status') === 'HIT') {
        cacheHits++;
      }

      // Update cache hit rate
      this.metrics.cacheHitRate = totalRequests > 0 ? cacheHits / totalRequests : 0;

      return response;
    };
  }

  /**
   * Handle service worker messages
   */
  private handleServiceWorkerMessage(data: any): void {
    switch (data.type) {
      case 'SYNC_COMPLETED':
        this.metrics.syncEvents++;
        this.saveMetrics();
        this.emit('syncCompleted', data);
        break;
      case 'CACHE_UPDATED':
        this.emit('cacheUpdated', data);
        break;
      case 'DOWNLOAD_PROGRESS':
        this.emit('downloadProgress', data);
        break;
      default:
        console.log('[PWA Manager] Unknown SW message:', data);
    }
  }

  /**
   * Install the PWA
   */
  async install(): Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }> {
    if (!this.installPromptEvent) {
      throw new Error('Install prompt not available');
    }

    await this.installPromptEvent.prompt();
    const result = await this.installPromptEvent.userChoice;
    
    if (result.outcome === 'accepted') {
      this.installPromptEvent = null;
      this.emit('installAccepted', result);
    } else {
      this.emit('installDismissed', result);
    }

    return result;
  }

  /**
   * Update the service worker
   */
  async update(): Promise<void> {
    if (!this.serviceWorkerRegistration) {
      throw new Error('Service worker not registered');
    }

    if (!this.updateAvailable) {
      // Force check for updates
      await this.serviceWorkerRegistration.update();
    }

    if (this.serviceWorkerRegistration.waiting) {
      // Tell the waiting SW to become the active SW
      this.serviceWorkerRegistration.waiting.postMessage({ type: 'SKIP_WAITING' });
      
      // Reload the page to activate the new service worker
      window.location.reload();
    }
  }

  /**
   * Preload critical resources
   */
  async preloadResources(urls: string[]): Promise<void> {
    if (!this.serviceWorkerRegistration) return;

    const channel = new MessageChannel();
    this.serviceWorkerRegistration.active?.postMessage(
      { type: 'PRELOAD_RESOURCES', urls },
      [channel.port2]
    );

    return new Promise((resolve) => {
      channel.port1.onmessage = () => resolve();
    });
  }

  /**
   * Clear all caches
   */
  async clearCaches(): Promise<void> {
    if (!this.serviceWorkerRegistration) return;

    const channel = new MessageChannel();
    this.serviceWorkerRegistration.active?.postMessage(
      { type: 'CLEAR_CACHE' },
      [channel.port2]
    );

    return new Promise((resolve) => {
      channel.port1.onmessage = () => resolve();
    });
  }

  /**
   * Get cache statistics
   */
  async getCacheStats(): Promise<Record<string, number>> {
    if (!this.serviceWorkerRegistration) return {};

    const channel = new MessageChannel();
    this.serviceWorkerRegistration.active?.postMessage(
      { type: 'GET_CACHE_STATS' },
      [channel.port2]
    );

    return new Promise((resolve) => {
      channel.port1.onmessage = (event) => {
        resolve(event.data.stats || {});
      };
    });
  }

  /**
   * Share content using Web Share API
   */
  async share(data: { title?: string; text?: string; url?: string }): Promise<void> {
    if (!this.capabilities.webShare) {
      throw new Error('Web Share API not supported');
    }

    try {
      await navigator.share(data);
      this.emit('shareSuccessful', data);
    } catch (error) {
      if (error.name !== 'AbortError') {
        this.emit('shareFailed', { error, data });
        throw error;
      }
    }
  }

  /**
   * Toggle fullscreen mode
   */
  async toggleFullscreen(): Promise<boolean> {
    if (!this.capabilities.fullscreen) {
      throw new Error('Fullscreen API not supported');
    }

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        this.emit('fullscreenExit');
        return false;
      } else {
        await document.documentElement.requestFullscreen();
        this.emit('fullscreenEnter');
        return true;
      }
    } catch (error) {
      this.emit('fullscreenError', error);
      throw error;
    }
  }

  /**
   * Lock screen orientation
   */
  async lockOrientation(orientation: string): Promise<void> {
    if (!this.capabilities.screenOrientation) {
      throw new Error('Screen Orientation API not supported');
    }

    try {
      await (screen.orientation as any).lock?.(orientation);
      this.emit('orientationLocked', orientation);
    } catch (error) {
      this.emit('orientationLockError', error);
      throw error;
    }
  }

  /**
   * Event listener management
   */
  on(event: string, callback: Function): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event)!.push(callback);
  }

  off(event: string, callback: Function): void {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      const index = callbacks.indexOf(callback);
      if (index > -1) {
        callbacks.splice(index, 1);
      }
    }
  }

  private emit(event: string, data?: any): void {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      callbacks.forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[PWA Manager] Event callback error for ${event}:`, error);
        }
      });
    }
  }

  /**
   * Metrics management
   */
  private loadMetrics(): PWAMetrics {
    try {
      const stored = localStorage.getItem('br-pwa-metrics');
      if (stored) {
        const metrics = JSON.parse(stored);
        // Convert date strings back to Date objects
        if (metrics.installDate) {
          metrics.installDate = new Date(metrics.installDate);
        }
        return metrics;
      }
    } catch (error) {
      console.warn('[PWA Manager] Failed to load metrics:', error);
    }

    return {
      launchCount: 0,
      totalUsageTime: 0,
      offlineUsageTime: 0,
      cacheHitRate: 0,
      syncEvents: 0,
      crashCount: 0
    };
  }

  private saveMetrics(): void {
    try {
      localStorage.setItem('br-pwa-metrics', JSON.stringify(this.metrics));
    } catch (error) {
      console.warn('[PWA Manager] Failed to save metrics:', error);
    }
  }

  private async reportMetrics(): Promise<void> {
    try {
      const endpoint = serviceEndpoints.orchestrator('/api/telemetry/pwa')
      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metrics: this.metrics,
          capabilities: this.capabilities,
          config: this.config,
          timestamp: new Date().toISOString()
        })
      });
    } catch (error) {
      // Ignore telemetry errors
    }
  }

  /**
   * Getters
   */
  get isAppInstalled(): boolean {
    return this.isInstalled;
  }

  get isStandaloneMode(): boolean {
    return this.isStandalone;
  }

  get canInstall(): boolean {
    return !!this.installPromptEvent;
  }

  get hasUpdate(): boolean {
    return this.updateAvailable;
  }

  get appCapabilities(): PWACapabilities {
    return { ...this.capabilities };
  }

  get appMetrics(): PWAMetrics {
    return { ...this.metrics };
  }

  get appConfig(): PWAConfig {
    return { ...this.config };
  }

  /**
   * Configuration updates
   */
  updateConfig(newConfig: Partial<PWAConfig>): void {
    this.config = { ...this.config, ...newConfig };
    
    // Apply configuration changes
    if (this.serviceWorkerRegistration) {
      this.serviceWorkerRegistration.active?.postMessage({
        type: 'UPDATE_CONFIG',
        config: this.config
      });
    }
  }
}

// Create singleton instance
const pwaManager = new PWAManager();

// Export utilities
export const PWAUtils = {
  /**
   * Check if running as PWA
   */
  isPWA(): boolean {
    return window.matchMedia('(display-mode: standalone)').matches ||
           (window.navigator as any).standalone === true;
  },

  /**
   * Check if device is mobile
   */
  isMobile(): boolean {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  },

  /**
   * Get device info
   */
  getDeviceInfo(): { platform: string; isMobile: boolean; isPWA: boolean } {
    return {
      platform: navigator.platform,
      isMobile: this.isMobile(),
      isPWA: this.isPWA()
    };
  },

  /**
   * Format file size
   */
  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  },

  /**
   * Format duration
   */
  formatDuration(milliseconds: number): string {
    const seconds = Math.floor(milliseconds / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ${hours % 24}h`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m`;
    return `${seconds}s`;
  }
};

export { PWAManager };
export default pwaManager;
