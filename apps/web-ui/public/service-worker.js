/**
 * Enhanced Service Worker for Brain Researcher UI
 * Provides comprehensive offline caching, brain data optimization, and background sync
 * Optimized for neuroimaging datasets and analysis results
 */

const CACHE_VERSION = 'v3';
const CACHE_NAME = `brain-researcher-${CACHE_VERSION}`;
const STATIC_CACHE = `brain-researcher-static-${CACHE_VERSION}`;
const API_CACHE = `brain-researcher-api-${CACHE_VERSION}`;
const IMAGE_CACHE = `brain-researcher-images-${CACHE_VERSION}`;
const BRAIN_DATA_CACHE = `brain-researcher-brain-data-${CACHE_VERSION}`;
const ANALYSIS_CACHE = `brain-researcher-analysis-${CACHE_VERSION}`;

// Enhanced resources to cache on install
const STATIC_RESOURCES = [
  '/',
  '/offline',
  '/manifest.json',
  '/_next/static/chunks/webpack.js',
  '/_next/static/chunks/main.js',
  '/_next/static/chunks/pages/_app.js',
  '/_next/static/css/app.css'
];

// Brain-specific API endpoints for aggressive caching
const BRAIN_DATA_ENDPOINTS = [
  '/api/kg/brain-regions',
  '/api/kg/networks',
  '/api/datasets/meta',
  '/api/atlas/data',
  '/api/viz/brain-templates'
];

// Analysis endpoints that can be cached temporarily
const ANALYSIS_ENDPOINTS = [
  '/api/analysis/results',
  '/api/viz/plots',
  '/api/dashboard/stats'
];

// Large brain imaging files that need special handling
const BRAIN_IMAGING_PATTERNS = [
  /\.nii\.gz$/i,
  /\.nii$/i,
  /brain_map/i,
  /statistical_map/i,
  /contrast_/i
];

// IndexedDB for large brain data storage
const DB_NAME = 'BrainResearcherDB';
const DB_VERSION = 1;
const BRAIN_DATA_STORE = 'brainData';

// Install event with enhanced caching
self.addEventListener('install', (event) => {
  console.log('[SW] Installing enhanced service worker...');
  
  event.waitUntil(
    Promise.all([
      // Cache static resources
      caches.open(STATIC_CACHE).then(cache => {
        console.log('[SW] Caching static resources...');
        return cache.addAll(STATIC_RESOURCES);
      }),
      
      // Initialize specialized caches
      caches.open(API_CACHE),
      caches.open(IMAGE_CACHE),
      caches.open(BRAIN_DATA_CACHE),
      caches.open(ANALYSIS_CACHE),
      
      // Initialize IndexedDB for large brain data
      initializeIndexedDB()
    ]).then(() => {
      console.log('[SW] Enhanced installation complete');
      self.skipWaiting();
    }).catch(error => {
      console.error('[SW] Installation failed:', error);
    })
  );
});

// Enhanced activate event with cache cleanup
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating enhanced service worker...');
  
  const cacheWhitelist = [
    CACHE_NAME, STATIC_CACHE, API_CACHE, 
    IMAGE_CACHE, BRAIN_DATA_CACHE, ANALYSIS_CACHE
  ];
  
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
      
      // Clean up old IndexedDB data
      cleanupOldData(),
      
      // Take control of all pages
      self.clients.claim()
    ]).then(() => {
      console.log('[SW] Enhanced activation complete');
    })
  );
});

// Enhanced fetch handling with brain data optimization
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

  // Route requests to appropriate cache strategy based on content type
  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
  } else if (isBrainDataRequest(url)) {
    event.respondWith(brainDataCacheStrategy(request));
  } else if (isAnalysisRequest(url)) {
    event.respondWith(analysisCacheStrategy(request));
  } else if (isAPIRequest(url)) {
    event.respondWith(networkFirst(request, API_CACHE));
  } else if (isImageRequest(url)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
  } else if (isBrainImagingFile(url)) {
    event.respondWith(largeBrainDataStrategy(request));
  } else {
    // Default: network first for pages
    event.respondWith(networkFirstWithOfflineFallback(request));
  }
});

// Specialized caching strategy for brain data
async function brainDataCacheStrategy(request) {
  const cache = await caches.open(BRAIN_DATA_CACHE);
  
  try {
    // Check cache first for brain data (it changes infrequently)
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse && !isStale(cachedResponse, 24 * 60 * 60 * 1000)) { // 24 hours
      // Update in background if approaching staleness
      updateCacheInBackground(request, cache);
      return cachedResponse;
    }
    
    // Fetch fresh data
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      // Clone and cache the response
      cache.put(request, networkResponse.clone());
      
      // Also store in IndexedDB for offline access
      storeBrainDataInIDB(request.url, await networkResponse.clone().json());
    }
    
    return networkResponse;
  } catch (error) {
    console.log('[SW] Network failed, trying IndexedDB for brain data');
    
    // Try IndexedDB for critical brain data
    const idbData = await getBrainDataFromIDB(request.url);
    if (idbData) {
      return new Response(JSON.stringify(idbData), {
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    // Final fallback to cache
    const cachedResponse = await cache.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    
    return createOfflineResponse('Brain data not available offline');
  }
}

// Strategy for analysis results (shorter cache lifetime)
async function analysisCacheStrategy(request) {
  const cache = await caches.open(ANALYSIS_CACHE);
  
  try {
    // Try network first for analysis results
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    // Fallback to cache for analysis results
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse && !isStale(cachedResponse, 60 * 60 * 1000)) { // 1 hour
      return cachedResponse;
    }
    
    return createOfflineResponse('Analysis results not available offline');
  }
}

// Strategy for large brain imaging files
async function largeBrainDataStrategy(request) {
  try {
    // Check IndexedDB first for large files
    const idbData = await getBrainDataFromIDB(request.url);
    if (idbData) {
      return new Response(idbData, {
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': idbData.byteLength
        }
      });
    }
    
    // Fetch from network with progress tracking
    const response = await fetch(request);
    
    if (response.ok && response.body) {
      // Stream and store large files
      const reader = response.body.getReader();
      const chunks = [];
      let receivedLength = 0;
      
      while (true) {
        const { done, value } = await reader.read();
        
        if (done) break;
        
        chunks.push(value);
        receivedLength += value.length;
        
        // Send progress updates to main thread
        self.clients.matchAll().then(clients => {
          clients.forEach(client => {
            client.postMessage({
              type: 'DOWNLOAD_PROGRESS',
              url: request.url,
              loaded: receivedLength,
              total: response.headers.get('Content-Length')
            });
          });
        });
      }
      
      const fullData = new Uint8Array(receivedLength);
      let position = 0;
      for (const chunk of chunks) {
        fullData.set(chunk, position);
        position += chunk.length;
      }
      
      // Store in IndexedDB for offline access
      await storeBrainDataInIDB(request.url, fullData.buffer);
      
      return new Response(fullData, {
        headers: response.headers
      });
    }
    
    return response;
  } catch (error) {
    console.error('[SW] Large brain data fetch failed:', error);
    return createOfflineResponse('Brain imaging data not available offline');
  }
}

// Enhanced network first with comprehensive offline fallback
async function networkFirstWithOfflineFallback(request) {
  try {
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    // Try cache first
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse) {
      return cachedResponse;
    }
    
    // Navigation requests get offline page
    if (request.mode === 'navigate') {
      const staticCache = await caches.open(STATIC_CACHE);
      const offlinePage = await staticCache.match('/offline');
      
      if (offlinePage) {
        return offlinePage;
      }
      
      // Create basic offline page if not cached
      return new Response(`
        <!DOCTYPE html>
        <html>
          <head>
            <title>Brain Researcher - Offline</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
          </head>
          <body>
            <h1>You're offline</h1>
            <p>Brain Researcher is not available right now. Please check your connection.</p>
            <button onclick="window.location.reload()">Try again</button>
          </body>
        </html>
      `, {
        headers: { 'Content-Type': 'text/html' }
      });
    }
    
    return createOfflineResponse('Content not available offline');
  }
}

// Helper functions with enhanced brain data detection
function isBrainDataRequest(url) {
  return BRAIN_DATA_ENDPOINTS.some(endpoint => url.pathname.startsWith(endpoint)) ||
         url.pathname.includes('brain') ||
         url.pathname.includes('atlas') ||
         url.pathname.includes('network');
}

function isAnalysisRequest(url) {
  return ANALYSIS_ENDPOINTS.some(endpoint => url.pathname.startsWith(endpoint)) ||
         url.pathname.includes('analysis') ||
         url.pathname.includes('results') ||
         url.pathname.includes('stats');
}

function isBrainImagingFile(url) {
  return BRAIN_IMAGING_PATTERNS.some(pattern => pattern.test(url.pathname));
}

function isStaticAsset(url) {
  return url.pathname.startsWith('/_next/static/') ||
         url.pathname.startsWith('/static/') ||
         url.pathname.endsWith('.css') ||
         url.pathname.endsWith('.js') ||
         url.pathname === '/manifest.json' ||
         url.pathname.startsWith('/icons/');
}

function isAPIRequest(url) {
  return url.pathname.startsWith('/api/') && 
         !isBrainDataRequest(url) && 
         !isAnalysisRequest(url);
}

function isImageRequest(url) {
  return /\.(jpg|jpeg|png|gif|webp|avif|svg)(\?.*)?$/i.test(url.pathname) ||
         url.pathname.startsWith('/_next/image');
}

function isStale(response, maxAge = 5 * 60 * 1000) {
  if (!response.headers.has('date')) return true;
  
  const responseDate = new Date(response.headers.get('date'));
  const now = new Date();
  
  return (now - responseDate) > maxAge;
}

function createOfflineResponse(message) {
  return new Response(JSON.stringify({
    error: 'Offline',
    message: message,
    timestamp: new Date().toISOString()
  }), {
    status: 503,
    statusText: 'Service Unavailable',
    headers: { 'Content-Type': 'application/json' }
  });
}

// Enhanced cache strategies (keeping the existing ones and adding improvements)
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
    
    const networkResponse = await fetch(request);
    
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    console.error('[SW] Cache first failed:', error);
    if (request.mode === 'navigate') {
      return await createNavigationFallback();
    }
    return createOfflineResponse('Content not available');
  }
}

async function networkFirst(request, cacheName) {
  try {
    const cache = await caches.open(cacheName);
    
    try {
      const networkResponse = await fetch(request);
      
      if (networkResponse.ok) {
        cache.put(request, networkResponse.clone());
      }
      
      return networkResponse;
    } catch (networkError) {
      const cachedResponse = await cache.match(request);
      
      if (cachedResponse) {
        return cachedResponse;
      }
      
      throw networkError;
    }
  } catch (error) {
    console.error('[SW] Network first failed:', error);
    return createOfflineResponse('Content not available');
  }
}

async function staleWhileRevalidate(request, cacheName) {
  try {
    const cache = await caches.open(cacheName);
    const cachedResponse = await cache.match(request);
    
    const networkPromise = fetch(request).then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    }).catch(() => null);
    
    if (cachedResponse) {
      networkPromise; // Don't await - update in background
      return cachedResponse;
    }
    
    return await networkPromise;
  } catch (error) {
    console.error('[SW] Stale while revalidate failed:', error);
    return createOfflineResponse('Content not available');
  }
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

async function createNavigationFallback() {
  const staticCache = await caches.open(STATIC_CACHE);
  return staticCache.match('/offline') || new Response('Page not available offline', {
    status: 503,
    statusText: 'Service Unavailable'
  });
}

// Enhanced IndexedDB operations for brain data
async function initializeIndexedDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      
      if (!db.objectStoreNames.contains(BRAIN_DATA_STORE)) {
        const store = db.createObjectStore(BRAIN_DATA_STORE, { keyPath: 'url' });
        store.createIndex('timestamp', 'timestamp', { unique: false });
        store.createIndex('type', 'type', { unique: false });
      }
    };
  });
}

async function storeBrainDataInIDB(url, data) {
  try {
    const db = await initializeIndexedDB();
    const transaction = db.transaction([BRAIN_DATA_STORE], 'readwrite');
    const store = transaction.objectStore(BRAIN_DATA_STORE);
    
    await store.put({
      url: url,
      data: data,
      timestamp: Date.now(),
      type: detectBrainDataType(url)
    });
    
    console.log('[SW] Stored brain data in IndexedDB:', url);
  } catch (error) {
    console.error('[SW] Failed to store brain data in IndexedDB:', error);
  }
}

async function getBrainDataFromIDB(url) {
  try {
    const db = await initializeIndexedDB();
    const transaction = db.transaction([BRAIN_DATA_STORE], 'readonly');
    const store = transaction.objectStore(BRAIN_DATA_STORE);
    
    return new Promise((resolve, reject) => {
      const request = store.get(url);
      request.onsuccess = () => {
        const result = request.result;
        if (result && !isDataStale(result.timestamp)) {
          resolve(result.data);
        } else {
          resolve(null);
        }
      };
      request.onerror = () => reject(request.error);
    });
  } catch (error) {
    console.error('[SW] Failed to get brain data from IndexedDB:', error);
    return null;
  }
}

async function cleanupOldData() {
  try {
    const db = await initializeIndexedDB();
    const transaction = db.transaction([BRAIN_DATA_STORE], 'readwrite');
    const store = transaction.objectStore(BRAIN_DATA_STORE);
    const index = store.index('timestamp');
    
    const cutoffTime = Date.now() - (7 * 24 * 60 * 60 * 1000); // 7 days
    const range = IDBKeyRange.upperBound(cutoffTime);
    
    const request = index.openCursor(range);
    request.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };
  } catch (error) {
    console.error('[SW] Failed to cleanup old data:', error);
  }
}

function detectBrainDataType(url) {
  if (url.includes('brain-regions')) return 'regions';
  if (url.includes('networks')) return 'networks';
  if (url.includes('atlas')) return 'atlas';
  if (url.includes('.nii')) return 'nifti';
  return 'unknown';
}

function isDataStale(timestamp, maxAge = 24 * 60 * 60 * 1000) {
  return (Date.now() - timestamp) > maxAge;
}

// Enhanced message handling
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
      
    case 'CLEAR_BRAIN_DATA':
      clearBrainDataCache().then(() => {
        event.ports[0]?.postMessage({ success: true });
      });
      break;
      
    case 'PRELOAD_RESOURCES':
      preloadResources(payload?.urls || []).then(() => {
        event.ports[0]?.postMessage({ success: true });
      });
      break;
      
    case 'PRELOAD_BRAIN_DATA':
      preloadBrainData(payload?.datasets || []).then(() => {
        event.ports[0]?.postMessage({ success: true });
      });
      break;
      
    case 'GET_CACHE_STATS':
      getCacheStats().then(stats => {
        event.ports[0]?.postMessage({ stats });
      });
      break;
      
    case 'GET_OFFLINE_STATUS':
      getOfflineCapabilities().then(capabilities => {
        event.ports[0]?.postMessage({ capabilities });
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

async function clearBrainDataCache() {
  await Promise.all([
    caches.delete(BRAIN_DATA_CACHE),
    caches.delete(ANALYSIS_CACHE),
    cleanupOldData()
  ]);
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

async function preloadBrainData(datasets) {
  const cache = await caches.open(BRAIN_DATA_CACHE);
  
  for (const dataset of datasets) {
    try {
      const response = await fetch(dataset.url);
      if (response.ok) {
        await cache.put(dataset.url, response.clone());
        
        // Also store in IndexedDB for large datasets
        if (dataset.large) {
          await storeBrainDataInIDB(dataset.url, await response.json());
        }
      }
    } catch (error) {
      console.log('[SW] Brain data preload failed for:', dataset.url, error.message);
    }
  }
}

async function getCacheStats() {
  const cacheNames = await caches.keys();
  const stats = {};
  
  for (const cacheName of cacheNames) {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();
    stats[cacheName] = keys.length;
  }
  
  // Add IndexedDB stats
  try {
    const db = await initializeIndexedDB();
    const transaction = db.transaction([BRAIN_DATA_STORE], 'readonly');
    const store = transaction.objectStore(BRAIN_DATA_STORE);
    
    const countRequest = store.count();
    stats['indexeddb_brain_data'] = await new Promise((resolve) => {
      countRequest.onsuccess = () => resolve(countRequest.result);
    });
  } catch (error) {
    stats['indexeddb_brain_data'] = 0;
  }
  
  return stats;
}

async function getOfflineCapabilities() {
  const capabilities = {
    basicPages: true,
    brainData: false,
    analysisResults: false,
    imagingData: false
  };
  
  try {
    const brainCache = await caches.open(BRAIN_DATA_CACHE);
    const brainKeys = await brainCache.keys();
    capabilities.brainData = brainKeys.length > 0;
    
    const analysisCache = await caches.open(ANALYSIS_CACHE);
    const analysisKeys = await analysisCache.keys();
    capabilities.analysisResults = analysisKeys.length > 0;
    
    const db = await initializeIndexedDB();
    const transaction = db.transaction([BRAIN_DATA_STORE], 'readonly');
    const store = transaction.objectStore(BRAIN_DATA_STORE);
    
    const count = await new Promise((resolve) => {
      const countRequest = store.count();
      countRequest.onsuccess = () => resolve(countRequest.result);
    });
    
    capabilities.imagingData = count > 0;
  } catch (error) {
    console.error('[SW] Error checking offline capabilities:', error);
  }
  
  return capabilities;
}

// Enhanced background sync for brain research workflows
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync triggered:', event.tag);
  
  switch (event.tag) {
    case 'sync-analysis-results':
      event.waitUntil(syncAnalysisResults());
      break;
    case 'sync-brain-data':
      event.waitUntil(syncBrainData());
      break;
    case 'sync-performance-data':
      event.waitUntil(syncPerformanceData());
      break;
    case 'cleanup-old-data':
      event.waitUntil(cleanupOldData());
      break;
    default:
      console.log('[SW] Unknown sync tag:', event.tag);
  }
});

async function syncAnalysisResults() {
  try {
    console.log('[SW] Syncing analysis results...');
    // Implementation would sync cached analysis results with server
    const pendingResults = await getPendingAnalysisResults();
    
    for (const result of pendingResults) {
      try {
        await fetch('/api/analysis/sync', {
          method: 'POST',
          body: JSON.stringify(result),
          headers: { 'Content-Type': 'application/json' }
        });
      } catch (error) {
        console.error('[SW] Failed to sync analysis result:', error);
      }
    }
  } catch (error) {
    console.error('[SW] Analysis results sync failed:', error);
  }
}

async function syncBrainData() {
  try {
    console.log('[SW] Syncing brain data...');
    // Check for data updates and refresh critical brain datasets
    const criticalDatasets = [
      '/api/kg/brain-regions',
      '/api/atlas/data'
    ];
    
    const cache = await caches.open(BRAIN_DATA_CACHE);
    
    for (const dataset of criticalDatasets) {
      try {
        const response = await fetch(dataset);
        if (response.ok) {
          await cache.put(dataset, response.clone());
          await storeBrainDataInIDB(dataset, await response.json());
        }
      } catch (error) {
        console.error('[SW] Failed to sync brain dataset:', dataset, error);
      }
    }
  } catch (error) {
    console.error('[SW] Brain data sync failed:', error);
  }
}

async function syncPerformanceData() {
  try {
    console.log('[SW] Syncing performance data...');
    // Sync performance metrics collected offline
    const performanceData = await getStoredPerformanceData();
    
    if (performanceData.length > 0) {
      await fetch('/api/telemetry/performance', {
        method: 'POST',
        body: JSON.stringify(performanceData),
        headers: { 'Content-Type': 'application/json' }
      });
      
      await clearStoredPerformanceData();
    }
  } catch (error) {
    console.error('[SW] Performance data sync failed:', error);
  }
}

async function getPendingAnalysisResults() {
  // Placeholder - would retrieve from IndexedDB
  return [];
}

async function getStoredPerformanceData() {
  // Placeholder - would retrieve from IndexedDB
  return [];
}

async function clearStoredPerformanceData() {
  // Placeholder - would clear from IndexedDB
}

// Enhanced push notification handling for brain research
self.addEventListener('push', (event) => {
  if (event.data) {
    const data = event.data.json();
    console.log('[SW] Push notification received:', data);
    
    const options = {
      body: data.body || 'New update available',
      icon: '/icons/icon-192x192.png',
      badge: '/icons/icon-192x192.png',
      tag: data.tag || 'default',
      data: data.data || {},
      actions: []
    };
    
    // Customize based on notification type
    switch (data.type) {
      case 'analysis-complete':
        options.body = `Analysis "${data.analysisName}" is complete`;
        options.actions = [
          { action: 'view', title: 'View Results' },
          { action: 'dismiss', title: 'Dismiss' }
        ];
        break;
        
      case 'data-update':
        options.body = `New brain data available: ${data.datasetName}`;
        options.actions = [
          { action: 'sync', title: 'Sync Now' },
          { action: 'later', title: 'Later' }
        ];
        break;
        
      case 'system-alert':
        options.body = data.message;
        options.badge = '/icons/alert-badge.png';
        options.requireInteraction = true;
        break;
        
      default:
        options.body = data.body || 'Brain Researcher notification';
    }

    event.waitUntil(
      self.registration.showNotification('Brain Researcher', options)
    );
  }
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  console.log('[SW] Notification clicked:', event.notification.tag, event.action);
  
  event.notification.close();
  
  // Handle different actions
  switch (event.action) {
    case 'view':
      event.waitUntil(
        clients.openWindow('/analysis/results/' + event.notification.data.analysisId)
      );
      break;
      
    case 'sync':
      event.waitUntil(
        self.registration.sync.register('sync-brain-data')
      );
      break;
      
    case 'dismiss':
    case 'later':
      // Just dismiss
      break;
      
    default:
      // Default action - open the app
      event.waitUntil(
        clients.matchAll().then(clientList => {
          if (clientList.length > 0) {
            return clientList[0].focus();
          }
          return clients.openWindow('/');
        })
      );
  }
});

console.log('[SW] Enhanced Brain Researcher service worker loaded');
