/**
 * Service Worker for Brain Researcher UI
 * Provides offline caching, performance optimization, and background sync
 */

const CACHE_NAME = 'brain-researcher-v2';
const STATIC_CACHE = 'brain-researcher-static-v2';
const API_CACHE = 'brain-researcher-api-v2';
const IMAGE_CACHE = 'brain-researcher-images-v2';

// Resources to cache on install
const STATIC_RESOURCES = [
  '/',
  '/offline.html',
  '/manifest.json'
];

// API endpoints to cache
const CACHEABLE_APIS = [
  '/api/dashboard/stats',
  '/api/kg/stats',
  '/api/datasets'
];

// Install event
self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker...');
  
  event.waitUntil(
    Promise.all([
      // Cache static resources
      caches.open(STATIC_CACHE).then(cache => {
        return cache.addAll(STATIC_RESOURCES);
      }),
      // Initialize other caches
      caches.open(API_CACHE),
      caches.open(IMAGE_CACHE)
    ]).then(() => {
      console.log('[SW] Installation complete');
      // Force activate immediately
      self.skipWaiting();
    })
  );
});

// Activate event
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker...');
  
  const cacheWhitelist = [CACHE_NAME, STATIC_CACHE, API_CACHE, IMAGE_CACHE];
  
  event.waitUntil(
    Promise.all([
      // Clean up old caches
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            if (!cacheWhitelist.includes(cacheName)) {
              console.log('[SW] Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      }),
      // Take control of all pages
      self.clients.claim()
    ]).then(() => {
      console.log('[SW] Activation complete');
    })
  );
});

// Fetch event - main caching logic
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  
  // Only handle GET requests
  if (request.method !== 'GET') {
    return;
  }
  
  // Skip cross-origin requests. Browser API traffic should flow through same-origin
  // Next.js proxy routes; explicit public-service overrides bypass SW caching.
  if (url.origin !== self.location.origin) {
    return;
  }

  // Route requests to appropriate cache strategy
  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
  } else if (isAPIRequest(url)) {
    event.respondWith(networkFirst(request, API_CACHE));
  } else if (isImageRequest(url)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
  } else {
    // Default: network first for pages
    event.respondWith(networkFirst(request, CACHE_NAME));
  }
});

// Cache First: Check cache first, fallback to network
async function cacheFirst(request, cacheName) {
  try {
    const cache = await caches.open(cacheName);
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse) {
      // Update cache in background if resource is stale
      if (isStale(cachedResponse)) {
        updateCacheInBackground(request, cache);
      }
      return cachedResponse;
    }
    
    // Not in cache, fetch from network
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    console.error('[SW] Cache first failed:', error);
    // Return offline page for navigation requests
    if (request.mode === 'navigate') {
      const cache = await caches.open(STATIC_CACHE);
      return cache.match('/offline.html') || new Response('Offline content not available', { 
        status: 503,
        statusText: 'Service Unavailable'
      });
    }
    return new Response('Content not available', { 
      status: 503,
      statusText: 'Service Unavailable'
    });
  }
}

// Network First: Try network first, fallback to cache
async function networkFirst(request, cacheName) {
  try {
    const cache = await caches.open(cacheName);
    
    // Try network first
    try {
      const networkResponse = await fetch(request);
      
      if (networkResponse.ok) {
        // Update cache with fresh content
        cache.put(request, networkResponse.clone());
      }
      
      return networkResponse;
    } catch (networkError) {
      console.log('[SW] Network failed, trying cache:', networkError.message);
      
      // Network failed, try cache
      const cachedResponse = await cache.match(request);
      
      if (cachedResponse) {
        return cachedResponse;
      }
      
      // Neither network nor cache available
      if (request.mode === 'navigate') {
        const staticCache = await caches.open(STATIC_CACHE);
        return staticCache.match('/offline.html') || new Response('Page not available offline', { 
          status: 503,
          statusText: 'Service Unavailable'
        });
      }
      
      throw new Error('Both network and cache failed');
    }
  } catch (error) {
    console.error('[SW] Network first failed:', error);
    return new Response('Content not available', { 
      status: 503,
      statusText: 'Service Unavailable'
    });
  }
}

// Stale While Revalidate: Return cache immediately, update in background
async function staleWhileRevalidate(request, cacheName) {
  try {
    const cache = await caches.open(cacheName);
    const cachedResponse = await cache.match(request);
    
    // Always try to update cache in background
    const networkPromise = fetch(request).then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    }).catch(err => {
      console.log('[SW] Background update failed:', err.message);
    });
    
    // Return cached version immediately if available
    if (cachedResponse) {
      // Don't await network promise - it updates in background
      networkPromise;
      return cachedResponse;
    }
    
    // No cached version, wait for network
    return await networkPromise;
  } catch (error) {
    console.error('[SW] Stale while revalidate failed:', error);
    return new Response('Content not available', { 
      status: 503,
      statusText: 'Service Unavailable'
    });
  }
}

// Helper functions
function isStaticAsset(url) {
  return url.pathname.startsWith('/_next/static/') ||
         url.pathname.startsWith('/static/') ||
         url.pathname.endsWith('.css') ||
         url.pathname.endsWith('.js') ||
         url.pathname === '/manifest.json';
}

function isAPIRequest(url) {
  return url.pathname.startsWith('/api/') ||
         CACHEABLE_APIS.some(api => url.pathname.startsWith(api));
}

function isImageRequest(url) {
  return /\.(jpg|jpeg|png|gif|webp|avif|svg)(\?.*)?$/i.test(url.pathname) ||
         url.pathname.startsWith('/_next/image');
}

function isStale(response) {
  if (!response.headers.has('date')) return true;
  
  const responseDate = new Date(response.headers.get('date'));
  const now = new Date();
  const staleTime = 5 * 60 * 1000; // 5 minutes
  
  return (now - responseDate) > staleTime;
}

async function updateCacheInBackground(request, cache) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      await cache.put(request, response);
    }
  } catch (error) {
    console.log('[SW] Background update failed:', error.message);
  }
}

// Message handling for cache management
self.addEventListener('message', (event) => {
  const { type, payload } = event.data;
  
  switch (type) {
    case 'SKIP_WAITING':
      self.skipWaiting();
      break;
      
    case 'CLEAR_CACHE':
      clearCache(payload?.cacheName).then(() => {
        event.ports[0]?.postMessage({ success: true });
      });
      break;
      
    case 'PRELOAD_RESOURCES':
      preloadResources(payload?.urls || []).then(() => {
        event.ports[0]?.postMessage({ success: true });
      });
      break;
      
    case 'GET_CACHE_STATS':
      getCacheStats().then(stats => {
        event.ports[0]?.postMessage({ stats });
      });
      break;
      
    default:
      console.log('[SW] Unknown message type:', type);
  }
});

async function clearCache(cacheName) {
  if (cacheName) {
    await caches.delete(cacheName);
  } else {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map(name => caches.delete(name)));
  }
}

async function preloadResources(urls) {
  const cache = await caches.open(CACHE_NAME);
  await Promise.all(
    urls.map(async (url) => {
      try {
        const response = await fetch(url);
        if (response.ok) {
          await cache.put(url, response);
        }
      } catch (error) {
        console.log('[SW] Preload failed for:', url, error.message);
      }
    })
  );
}

async function getCacheStats() {
  const cacheNames = await caches.keys();
  const stats = {};
  
  for (const cacheName of cacheNames) {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();
    stats[cacheName] = keys.length;
  }
  
  return stats;
}

// Background sync for offline actions
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync triggered:', event.tag);
  
  if (event.tag === 'performance-data') {
    event.waitUntil(syncPerformanceData());
  } else if (event.tag === 'sync-data') {
    event.waitUntil(syncData());
  }
});

async function syncPerformanceData() {
  try {
    // Sync any cached performance data when back online
    console.log('[SW] Syncing performance data...');
    // Implementation would sync with performance monitoring service
  } catch (error) {
    console.error('[SW] Performance data sync failed:', error);
  }
}

async function syncData() {
  try {
    console.log('[SW] Syncing data...');
    // Implement general data sync logic here
  } catch (error) {
    console.error('[SW] Data sync failed:', error);
  }
}

// Push notification handling
self.addEventListener('push', (event) => {
  if (event.data) {
    const data = event.data.json();
    console.log('[SW] Push notification received:', data);
    
    // Handle performance alerts or system notifications
    if (data.type === 'performance-alert') {
      event.waitUntil(
        self.registration.showNotification('Brain Researcher Performance Alert', {
          body: data.message,
          icon: '/manifest-icon-192.maskable.png',
          badge: '/manifest-icon-192.maskable.png',
          tag: 'performance-alert'
        })
      );
    } else {
      // Default notification
      const options = {
        body: data.body || 'New update available',
        icon: '/manifest-icon-192.maskable.png',
        badge: '/manifest-icon-192.maskable.png'
      };

      event.waitUntil(
        self.registration.showNotification('Brain Researcher', options)
      );
    }
  }
});

console.log('[SW] Service worker loaded');
