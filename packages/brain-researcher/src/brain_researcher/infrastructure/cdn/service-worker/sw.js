/**
 * Brain Researcher Service Worker
 * Provides offline support, caching strategies, and performance optimization
 */

const CACHE_NAME = 'brain-researcher-v1.2.0';
const OFFLINE_URL = '/offline';
const API_CACHE_NAME = 'brain-researcher-api-v1';
const IMAGE_CACHE_NAME = 'brain-researcher-images-v1';
const STATIC_CACHE_NAME = 'brain-researcher-static-v1';

// Cache durations (in seconds)
const CACHE_DURATIONS = {
    STATIC_ASSETS: 31536000, // 1 year
    API_RESPONSES: 300,      // 5 minutes
    HTML_PAGES: 3600,        // 1 hour
    IMAGES: 2592000,         // 30 days
    FONTS: 31536000          // 1 year
};

// Resources to precache
const PRECACHE_RESOURCES = [
    '/',
    '/offline',
    '/static/css/main.css',
    '/static/js/main.js',
    '/static/images/logo.svg',
    '/static/images/brain-icon.png',
    '/manifest.json'
];

// API endpoints that can be cached
const CACHEABLE_API_PATTERNS = [
    /\/api\/datasets\/.*$/,
    /\/api\/concepts\/.*$/,
    /\/api\/studies\/.*$/,
    /\/api\/tasks\/.*$/,
    /\/api\/search\?.*$/
];

// API endpoints that should never be cached
const NO_CACHE_API_PATTERNS = [
    /\/api\/auth\/.*$/,
    /\/api\/user\/.*$/,
    /\/api\/jobs\/.*$/,
    /\/api\/admin\/.*$/,
    /\/ws\/.*$/
];

/**
 * Install event - precache critical resources
 */
self.addEventListener('install', event => {
    console.log('[SW] Installing service worker...');
    
    event.waitUntil(
        (async () => {
            const cache = await caches.open(STATIC_CACHE_NAME);
            
            try {
                await cache.addAll(PRECACHE_RESOURCES);
                console.log('[SW] Precached resources successfully');
            } catch (error) {
                console.error('[SW] Failed to precache resources:', error);
                // Cache resources individually to avoid total failure
                for (const resource of PRECACHE_RESOURCES) {
                    try {
                        await cache.add(resource);
                    } catch (err) {
                        console.warn(`[SW] Failed to cache ${resource}:`, err);
                    }
                }
            }
            
            // Skip waiting to activate immediately
            self.skipWaiting();
        })()
    );
});

/**
 * Activate event - cleanup old caches
 */
self.addEventListener('activate', event => {
    console.log('[SW] Activating service worker...');
    
    event.waitUntil(
        (async () => {
            // Clean up old caches
            const cacheNames = await caches.keys();
            const validCacheNames = [CACHE_NAME, API_CACHE_NAME, IMAGE_CACHE_NAME, STATIC_CACHE_NAME];
            
            await Promise.all(
                cacheNames
                    .filter(cacheName => !validCacheNames.includes(cacheName))
                    .map(cacheName => {
                        console.log(`[SW] Deleting old cache: ${cacheName}`);
                        return caches.delete(cacheName);
                    })
            );
            
            // Take control of all pages
            self.clients.claim();
        })()
    );
});

/**
 * Fetch event - implement caching strategies
 */
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);
    
    // Skip non-HTTP requests
    if (!url.protocol.startsWith('http')) {
        return;
    }
    
    // Skip Chrome extension requests
    if (url.origin === 'chrome-extension') {
        return;
    }
    
    event.respondWith(handleFetch(request));
});

/**
 * Handle fetch requests with appropriate caching strategy
 */
async function handleFetch(request) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    
    try {
        // Strategy 1: API requests
        if (pathname.startsWith('/api/')) {
            return await handleApiRequest(request);
        }
        
        // Strategy 2: Static assets (JS, CSS, images, fonts)
        if (isStaticAsset(pathname)) {
            return await handleStaticAsset(request);
        }
        
        // Strategy 3: Images
        if (isImage(pathname)) {
            return await handleImage(request);
        }
        
        // Strategy 4: HTML pages and navigation
        if (request.mode === 'navigate' || pathname.endsWith('.html') || pathname === '/') {
            return await handleNavigation(request);
        }
        
        // Default: network first
        return await fetch(request);
        
    } catch (error) {
        console.error('[SW] Fetch error:', error);
        
        // Return offline page for navigation requests
        if (request.mode === 'navigate') {
            const cache = await caches.open(STATIC_CACHE_NAME);
            return await cache.match(OFFLINE_URL) || new Response('Offline');
        }
        
        // Return cached version if available
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match(request);
        if (cached) {
            return cached;
        }
        
        throw error;
    }
}

/**
 * Handle API requests with cache-first strategy for GET requests
 */
async function handleApiRequest(request) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    
    // Never cache certain API endpoints
    if (NO_CACHE_API_PATTERNS.some(pattern => pattern.test(pathname))) {
        return await fetch(request);
    }
    
    // Cache GET requests to certain endpoints
    if (request.method === 'GET' && CACHEABLE_API_PATTERNS.some(pattern => pattern.test(pathname))) {
        const cache = await caches.open(API_CACHE_NAME);
        
        // Try cache first
        const cached = await cache.match(request);
        if (cached) {
            const cacheDate = new Date(cached.headers.get('date') || 0);
            const now = new Date();
            const cacheAge = (now - cacheDate) / 1000;
            
            // Use cached version if still fresh
            if (cacheAge < CACHE_DURATIONS.API_RESPONSES) {
                // Refresh in background if cache is getting stale
                if (cacheAge > CACHE_DURATIONS.API_RESPONSES * 0.8) {
                    refreshCacheInBackground(request, cache);
                }
                return cached;
            }
        }
        
        // Fetch from network
        try {
            const response = await fetch(request);
            if (response.ok) {
                // Cache successful responses
                const responseClone = response.clone();
                await cache.put(request, responseClone);
            }
            return response;
        } catch (error) {
            // Return cached version as fallback
            if (cached) {
                return cached;
            }
            throw error;
        }
    }
    
    // Default to network for non-GET or non-cacheable requests
    return await fetch(request);
}

/**
 * Handle static assets with cache-first strategy
 */
async function handleStaticAsset(request) {
    const cache = await caches.open(STATIC_CACHE_NAME);
    
    // Try cache first
    const cached = await cache.match(request);
    if (cached) {
        return cached;
    }
    
    // Fetch from network and cache
    try {
        const response = await fetch(request);
        if (response.ok) {
            const responseClone = response.clone();
            await cache.put(request, responseClone);
        }
        return response;
    } catch (error) {
        // Return cached version as fallback
        if (cached) {
            return cached;
        }
        throw error;
    }
}

/**
 * Handle images with cache-first strategy and optimization
 */
async function handleImage(request) {
    const cache = await caches.open(IMAGE_CACHE_NAME);
    
    // Try cache first
    const cached = await cache.match(request);
    if (cached) {
        return cached;
    }
    
    // Fetch from network
    try {
        const response = await fetch(request);
        if (response.ok) {
            const responseClone = response.clone();
            await cache.put(request, responseClone);
        }
        return response;
    } catch (error) {
        // Return cached version as fallback
        if (cached) {
            return cached;
        }
        
        // Return placeholder image for failed image loads
        return new Response(
            '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100" fill="#f0f0f0"/><text x="50" y="50" text-anchor="middle" dy=".3em" fill="#999">Image unavailable</text></svg>',
            { headers: { 'Content-Type': 'image/svg+xml' } }
        );
    }
}

/**
 * Handle navigation requests with network-first strategy
 */
async function handleNavigation(request) {
    const cache = await caches.open(STATIC_CACHE_NAME);
    
    try {
        // Try network first for fresh content
        const response = await fetch(request);
        if (response.ok) {
            // Cache successful responses
            const responseClone = response.clone();
            await cache.put(request, responseClone);
        }
        return response;
    } catch (error) {
        // Fallback to cache
        const cached = await cache.match(request);
        if (cached) {
            return cached;
        }
        
        // Fallback to offline page
        const offline = await cache.match(OFFLINE_URL);
        if (offline) {
            return offline;
        }
        
        // Last resort offline response
        return new Response(
            '<html><body><h1>Offline</h1><p>You are currently offline. Please check your connection.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
        );
    }
}

/**
 * Refresh cache in background
 */
async function refreshCacheInBackground(request, cache) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            await cache.put(request, response.clone());
        }
    } catch (error) {
        console.log('[SW] Background refresh failed:', error);
    }
}

/**
 * Check if request is for a static asset
 */
function isStaticAsset(pathname) {
    const staticExtensions = ['.js', '.css', '.woff', '.woff2', '.ttf', '.eot', '.json'];
    return staticExtensions.some(ext => pathname.endsWith(ext)) || 
           pathname.startsWith('/static/') || 
           pathname.startsWith('/_next/');
}

/**
 * Check if request is for an image
 */
function isImage(pathname) {
    const imageExtensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico'];
    return imageExtensions.some(ext => pathname.endsWith(ext));
}

/**
 * Handle background sync for failed network requests
 */
self.addEventListener('sync', event => {
    if (event.tag === 'background-sync') {
        event.waitUntil(doBackgroundSync());
    }
});

async function doBackgroundSync() {
    console.log('[SW] Performing background sync...');
    // Implement background sync logic for failed requests
    // This could include retrying failed API calls, uploading queued data, etc.
}

/**
 * Handle push notifications
 */
self.addEventListener('push', event => {
    if (!event.data) return;
    
    const data = event.data.json();
    const options = {
        body: data.body,
        icon: '/static/images/brain-icon.png',
        badge: '/static/images/badge.png',
        tag: data.tag || 'notification',
        requireInteraction: data.requireInteraction || false,
        actions: data.actions || []
    };
    
    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

/**
 * Handle notification clicks
 */
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    if (event.action) {
        // Handle action clicks
        console.log('[SW] Notification action clicked:', event.action);
    } else {
        // Handle notification click
        event.waitUntil(
            clients.openWindow(event.notification.data?.url || '/')
        );
    }
});

/**
 * Handle messages from main thread
 */
self.addEventListener('message', event => {
    if (event.data?.type === 'SKIP_WAITING') {
        self.skipWaiting();
    } else if (event.data?.type === 'CACHE_URLS') {
        event.waitUntil(cacheUrls(event.data.urls));
    } else if (event.data?.type === 'CLEAR_CACHE') {
        event.waitUntil(clearCache(event.data.cacheName));
    }
});

/**
 * Cache specific URLs
 */
async function cacheUrls(urls) {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(urls);
}

/**
 * Clear specific cache
 */
async function clearCache(cacheName) {
    if (cacheName) {
        await caches.delete(cacheName);
    } else {
        const cacheNames = await caches.keys();
        await Promise.all(cacheNames.map(name => caches.delete(name)));
    }
}