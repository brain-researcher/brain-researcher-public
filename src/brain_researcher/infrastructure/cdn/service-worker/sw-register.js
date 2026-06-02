/**
 * Service Worker Registration for Brain Researcher
 * Handles service worker lifecycle and updates
 */

class ServiceWorkerManager {
    constructor() {
        this.registration = null;
        this.isUpdateAvailable = false;
        this.callbacks = {
            updateAvailable: [],
            updateReady: [],
            error: []
        };

        this.init();
    }

    /**
     * Initialize service worker registration
     */
    async init() {
        if (!('serviceWorker' in navigator)) {
            console.log('[SW] Service Worker not supported');
            return;
        }

        try {
            await this.register();
            this.setupEventListeners();
            this.checkForUpdates();
        } catch (error) {
            console.error('[SW] Registration failed:', error);
            this.emit('error', error);
        }
    }

    /**
     * Register the service worker
     */
    async register() {
        const swUrl = '/sw.js';

        this.registration = await navigator.serviceWorker.register(swUrl, {
            scope: '/',
            updateViaCache: 'none'
        });

        console.log('[SW] Registered with scope:', this.registration.scope);

        // Handle initial installation
        if (this.registration.installing) {
            console.log('[SW] Installing...');
            await this.trackInstallation(this.registration.installing);
        }

        return this.registration;
    }

    /**
     * Setup event listeners for service worker events
     */
    setupEventListeners() {
        // Listen for updates
        this.registration.addEventListener('updatefound', () => {
            console.log('[SW] Update found');
            this.handleUpdateFound();
        });

        // Listen for controller changes
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            console.log('[SW] Controller changed - page will reload');
            window.location.reload();
        });

        // Listen for messages from service worker
        navigator.serviceWorker.addEventListener('message', event => {
            this.handleMessage(event);
        });

        // Handle page visibility changes
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                this.checkForUpdates();
            }
        });
    }

    /**
     * Handle service worker update found
     */
    async handleUpdateFound() {
        const installingWorker = this.registration.installing;
        if (!installingWorker) return;

        this.isUpdateAvailable = true;
        this.emit('updateAvailable');

        await this.trackInstallation(installingWorker);
    }

    /**
     * Track service worker installation progress
     */
    async trackInstallation(worker) {
        return new Promise((resolve) => {
            worker.addEventListener('statechange', () => {
                console.log('[SW] State changed to:', worker.state);

                switch (worker.state) {
                    case 'installed':
                        if (navigator.serviceWorker.controller) {
                            // Update available
                            this.emit('updateReady');
                        } else {
                            // First install
                            console.log('[SW] Content cached for offline use');
                        }
                        resolve();
                        break;

                    case 'redundant':
                        console.warn('[SW] Worker became redundant');
                        resolve();
                        break;
                }
            });
        });
    }

    /**
     * Handle messages from service worker
     */
    handleMessage(event) {
        const { type, payload } = event.data || {};

        switch (type) {
            case 'CACHE_UPDATED':
                console.log('[SW] Cache updated:', payload);
                break;

            case 'OFFLINE_READY':
                console.log('[SW] App ready to work offline');
                this.showOfflineReady();
                break;

            case 'UPDATE_AVAILABLE':
                console.log('[SW] Update available');
                this.emit('updateAvailable');
                break;
        }
    }

    /**
     * Check for service worker updates
     */
    async checkForUpdates() {
        if (!this.registration) return;

        try {
            await this.registration.update();
        } catch (error) {
            console.error('[SW] Update check failed:', error);
        }
    }

    /**
     * Activate waiting service worker
     */
    async activateUpdate() {
        if (!this.registration?.waiting) {
            console.warn('[SW] No waiting worker to activate');
            return false;
        }

        // Send message to skip waiting
        this.registration.waiting.postMessage({ type: 'SKIP_WAITING' });
        return true;
    }

    /**
     * Cache specific URLs
     */
    async cacheUrls(urls) {
        if (!navigator.serviceWorker.controller) {
            console.warn('[SW] No active service worker to cache URLs');
            return;
        }

        navigator.serviceWorker.controller.postMessage({
            type: 'CACHE_URLS',
            urls
        });
    }

    /**
     * Clear cache
     */
    async clearCache(cacheName = null) {
        if (!navigator.serviceWorker.controller) {
            console.warn('[SW] No active service worker to clear cache');
            return;
        }

        navigator.serviceWorker.controller.postMessage({
            type: 'CLEAR_CACHE',
            cacheName
        });
    }

    /**
     * Get cache status
     */
    async getCacheStatus() {
        if (!('caches' in window)) {
            return { supported: false };
        }

        const cacheNames = await caches.keys();
        const status = {
            supported: true,
            caches: {}
        };

        for (const cacheName of cacheNames) {
            const cache = await caches.open(cacheName);
            const keys = await cache.keys();
            status.caches[cacheName] = keys.length;
        }

        return status;
    }

    /**
     * Show offline ready notification
     */
    showOfflineReady() {
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Brain Researcher', {
                body: 'App is ready to work offline!',
                icon: '/static/images/brain-icon.png',
                tag: 'offline-ready'
            });
        }
    }

    /**
     * Request notification permission
     */
    async requestNotificationPermission() {
        if (!('Notification' in window)) {
            return 'not-supported';
        }

        if (Notification.permission === 'default') {
            const permission = await Notification.requestPermission();
            return permission;
        }

        return Notification.permission;
    }

    /**
     * Event emitter functionality
     */
    on(event, callback) {
        if (this.callbacks[event]) {
            this.callbacks[event].push(callback);
        }
    }

    off(event, callback) {
        if (this.callbacks[event]) {
            const index = this.callbacks[event].indexOf(callback);
            if (index > -1) {
                this.callbacks[event].splice(index, 1);
            }
        }
    }

    emit(event, data) {
        if (this.callbacks[event]) {
            this.callbacks[event].forEach(callback => callback(data));
        }
    }

    /**
     * Unregister service worker
     */
    async unregister() {
        if (!this.registration) return false;

        const result = await this.registration.unregister();
        console.log('[SW] Unregistered:', result);
        return result;
    }
}

// Export for use in other modules
window.ServiceWorkerManager = ServiceWorkerManager;

// Auto-initialize if not in a module environment
if (typeof module === 'undefined') {
    window.swManager = new ServiceWorkerManager();
}

// Utility functions for components
window.swUtils = {
    /**
     * Show update notification UI
     */
    showUpdateNotification() {
        const notification = document.createElement('div');
        notification.className = 'sw-update-notification';
        notification.innerHTML = `
            <div class="sw-notification-content">
                <span>🔄 New version available!</span>
                <button onclick="swUtils.applyUpdate()">Update</button>
                <button onclick="swUtils.dismissUpdate()">Later</button>
            </div>
        `;

        document.body.appendChild(notification);

        // Auto-dismiss after 10 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 10000);
    },

    /**
     * Apply service worker update
     */
    async applyUpdate() {
        if (window.swManager) {
            await window.swManager.activateUpdate();
        }

        // Remove notification
        const notification = document.querySelector('.sw-update-notification');
        if (notification) {
            notification.parentNode.removeChild(notification);
        }
    },

    /**
     * Dismiss update notification
     */
    dismissUpdate() {
        const notification = document.querySelector('.sw-update-notification');
        if (notification) {
            notification.parentNode.removeChild(notification);
        }
    }
};

// Set up update notification listener
if (window.swManager) {
    window.swManager.on('updateReady', () => {
        window.swUtils.showUpdateNotification();
    });
}