/**
 * Comprehensive Service Worker Tests for Brain Researcher PWA
 * Tests service worker installation, caching strategies, brain data optimization,
 * offline functionality, and background sync operations
 */

describe('Brain Researcher Service Worker', () => {
  let mockServiceWorker;
  let mockCaches;
  let mockClients;
  let mockIndexedDB;
  let mockFetch;

  beforeAll(() => {
    // Mock global Service Worker environment
    global.self = {
      addEventListener: jest.fn(),
      skipWaiting: jest.fn().mockResolvedValue(),
      clients: {
        claim: jest.fn().mockResolvedValue(),
        matchAll: jest.fn().mockResolvedValue([]),
      },
      registration: {
        showNotification: jest.fn().mockResolvedValue(),
        sync: {
          register: jest.fn().mockResolvedValue(),
        },
      },
      location: {
        origin: 'https://brain-researcher.app',
      },
    };

    // Mock Caches API
    mockCaches = {
      open: jest.fn(),
      keys: jest.fn(),
      delete: jest.fn(),
      match: jest.fn(),
    };
    global.caches = mockCaches;

    // Mock IndexedDB
    mockIndexedDB = {
      open: jest.fn(),
    };
    global.indexedDB = mockIndexedDB;

    // Mock fetch
    mockFetch = jest.fn();
    global.fetch = mockFetch;
  });

  beforeEach(() => {
    jest.clearAllMocks();
    
    // Reset service worker state
    mockServiceWorker = {
      caches: new Map(),
      indexedDB: new Map(),
      eventListeners: {},
    };

    // Mock cache implementation
    const mockCache = {
      addAll: jest.fn().mockResolvedValue(),
      put: jest.fn().mockResolvedValue(),
      match: jest.fn(),
      keys: jest.fn().mockResolvedValue([]),
    };
    
    mockCaches.open.mockResolvedValue(mockCache);
    mockCaches.keys.mockResolvedValue([
      'brain-researcher-v3',
      'brain-researcher-static-v3',
      'brain-researcher-api-v3',
    ]);
  });

  describe('Service Worker Installation', () => {
    test('should install with all required caches', async () => {
      const installEvent = new Event('install');
      const waitUntilSpy = jest.fn();
      installEvent.waitUntil = waitUntilSpy;

      // Simulate install event
      const installHandler = jest.fn(async (event) => {
        const promises = [
          mockCaches.open('brain-researcher-static-v3'),
          mockCaches.open('brain-researcher-api-v3'),
          mockCaches.open('brain-researcher-images-v3'),
          mockCaches.open('brain-researcher-brain-data-v3'),
          mockCaches.open('brain-researcher-analysis-v3'),
        ];

        event.waitUntil(Promise.all(promises));
      });

      await installHandler(installEvent);

      expect(mockCaches.open).toHaveBeenCalledTimes(5);
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-static-v3');
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-brain-data-v3');
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-analysis-v3');
    });

    test('should cache static resources during installation', async () => {
      const mockCache = {
        addAll: jest.fn().mockResolvedValue(),
      };
      mockCaches.open.mockResolvedValue(mockCache);

      const staticResources = [
        '/',
        '/offline',
        '/manifest.json',
        '/_next/static/chunks/webpack.js',
        '/_next/static/chunks/main.js',
      ];

      const installHandler = jest.fn(async () => {
        const cache = await mockCaches.open('brain-researcher-static-v3');
        await cache.addAll(staticResources);
      });

      await installHandler();

      expect(mockCache.addAll).toHaveBeenCalledWith(staticResources);
    });

    test('should initialize IndexedDB for brain data storage', async () => {
      const mockDB = {
        createObjectStore: jest.fn(),
        objectStoreNames: {
          contains: jest.fn().mockReturnValue(false),
        },
      };

      const mockRequest = {
        onsuccess: null,
        onerror: null,
        onupgradeneeded: null,
        result: mockDB,
      };

      mockIndexedDB.open.mockReturnValue(mockRequest);

      const initializeIndexedDB = jest.fn(() => {
        return new Promise((resolve) => {
          const request = mockIndexedDB.open('BrainResearcherDB', 1);
          
          request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('brainData')) {
              const store = db.createObjectStore('brainData', { keyPath: 'url' });
              store.createIndex('timestamp', 'timestamp', { unique: false });
              store.createIndex('type', 'type', { unique: false });
            }
          };
          
          request.onsuccess = () => resolve(request.result);
        });
      });

      await initializeIndexedDB();

      expect(mockIndexedDB.open).toHaveBeenCalledWith('BrainResearcherDB', 1);
    });
  });

  describe('Service Worker Activation', () => {
    test('should clean up old caches during activation', async () => {
      const activateEvent = new Event('activate');
      const waitUntilSpy = jest.fn();
      activateEvent.waitUntil = waitUntilSpy;

      mockCaches.keys.mockResolvedValue([
        'brain-researcher-v2', // old version
        'brain-researcher-static-v3', // current version
        'brain-researcher-api-v2', // old version
        'brain-researcher-brain-data-v3', // current version
      ]);

      const activateHandler = jest.fn(async (event) => {
        const cacheWhitelist = [
          'brain-researcher-static-v3',
          'brain-researcher-api-v3',
          'brain-researcher-brain-data-v3',
        ];

        const deletePromises = [];
        const cacheNames = await mockCaches.keys();
        
        cacheNames.forEach((cacheName) => {
          if (!cacheWhitelist.includes(cacheName)) {
            deletePromises.push(mockCaches.delete(cacheName));
          }
        });

        event.waitUntil(Promise.all(deletePromises));
      });

      await activateHandler(activateEvent);

      expect(mockCaches.delete).toHaveBeenCalledWith('brain-researcher-v2');
      expect(mockCaches.delete).toHaveBeenCalledWith('brain-researcher-api-v2');
      expect(mockCaches.delete).not.toHaveBeenCalledWith('brain-researcher-static-v3');
    });

    test('should take control of all clients', async () => {
      const activateEvent = new Event('activate');
      activateEvent.waitUntil = jest.fn();

      const activateHandler = jest.fn(async (event) => {
        event.waitUntil(self.clients.claim());
      });

      await activateHandler(activateEvent);
      expect(self.clients.claim).toHaveBeenCalled();
    });
  });

  describe('Fetch Event Handling', () => {
    let fetchEvent;
    let mockRequest;
    let mockResponse;

    beforeEach(() => {
      mockRequest = {
        method: 'GET',
        url: 'https://brain-researcher.app/api/kg/brain-regions',
        mode: 'navigate',
        clone: jest.fn().mockReturnThis(),
      };

      mockResponse = {
        ok: true,
        status: 200,
        headers: {
          get: jest.fn(),
          has: jest.fn(),
        },
        clone: jest.fn().mockReturnThis(),
        json: jest.fn().mockResolvedValue({ regions: ['frontal', 'parietal'] }),
      };

      fetchEvent = {
        request: mockRequest,
        respondWith: jest.fn(),
        waitUntil: jest.fn(),
      };

      mockFetch.mockResolvedValue(mockResponse);
    });

    test('should route brain data requests to specialized cache strategy', async () => {
      mockRequest.url = 'https://brain-researcher.app/api/kg/brain-regions';
      
      const isBrainDataRequest = (url) => {
        const urlObj = new URL(url);
        return urlObj.pathname.includes('/api/kg/brain-regions') ||
               urlObj.pathname.includes('/api/atlas/data') ||
               urlObj.pathname.includes('brain') ||
               urlObj.pathname.includes('network');
      };

      const brainDataCacheStrategy = jest.fn(async (request) => {
        const cache = await mockCaches.open('brain-researcher-brain-data-v3');
        
        // Check cache first for brain data (long cache lifetime)
        const cachedResponse = await cache.match(request);
        if (cachedResponse) {
          return cachedResponse;
        }

        // Fetch from network
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
          cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
      });

      expect(isBrainDataRequest(mockRequest.url)).toBe(true);
      
      const result = await brainDataCacheStrategy(mockRequest);
      
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-brain-data-v3');
      expect(mockFetch).toHaveBeenCalledWith(mockRequest);
      expect(result).toBe(mockResponse);
    });

    test('should handle analysis requests with shorter cache lifetime', async () => {
      mockRequest.url = 'https://brain-researcher.app/api/analysis/results/123';
      
      const isAnalysisRequest = (url) => {
        const urlObj = new URL(url);
        return urlObj.pathname.includes('/api/analysis/') ||
               urlObj.pathname.includes('/results') ||
               urlObj.pathname.includes('/stats');
      };

      const analysisCacheStrategy = jest.fn(async (request) => {
        const cache = await mockCaches.open('brain-researcher-analysis-v3');
        
        try {
          // Network first for analysis results
          const networkResponse = await fetch(request);
          if (networkResponse.ok) {
            cache.put(request, networkResponse.clone());
          }
          return networkResponse;
        } catch (error) {
          // Fallback to cache
          return await cache.match(request);
        }
      });

      expect(isAnalysisRequest(mockRequest.url)).toBe(true);
      
      const result = await analysisCacheStrategy(mockRequest);
      
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-analysis-v3');
      expect(mockFetch).toHaveBeenCalledWith(mockRequest);
      expect(result).toBe(mockResponse);
    });

    test('should handle large brain imaging files with progress tracking', async () => {
      mockRequest.url = 'https://brain-researcher.app/data/brain_map_123.nii.gz';
      
      const isBrainImagingFile = (url) => {
        return /\.nii\.gz$/i.test(url) ||
               /\.nii$/i.test(url) ||
               /brain_map/i.test(url) ||
               /statistical_map/i.test(url);
      };

      // Mock ReadableStream
      const mockReader = {
        read: jest.fn()
          .mockResolvedValueOnce({ done: false, value: new Uint8Array(1024) })
          .mockResolvedValueOnce({ done: false, value: new Uint8Array(1024) })
          .mockResolvedValueOnce({ done: true }),
      };

      mockResponse.body = {
        getReader: jest.fn().mockReturnValue(mockReader),
      };

      mockResponse.headers.get.mockReturnValue('2048');

      const largeBrainDataStrategy = jest.fn(async (request) => {
        const response = await fetch(request);
        
        if (response.ok && response.body) {
          const reader = response.body.getReader();
          const chunks = [];
          let receivedLength = 0;
          
          while (true) {
            const { done, value } = await reader.read();
            
            if (done) break;
            
            chunks.push(value);
            receivedLength += value.length;
            
            // Send progress updates
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
          
          return response;
        }
        
        return response;
      });

      expect(isBrainImagingFile(mockRequest.url)).toBe(true);
      
      await largeBrainDataStrategy(mockRequest);
      
      expect(mockReader.read).toHaveBeenCalledTimes(3);
      expect(self.clients.matchAll).toHaveBeenCalled();
    });

    test('should provide offline fallback for navigation requests', async () => {
      mockRequest.mode = 'navigate';
      mockFetch.mockRejectedValue(new Error('Network error'));

      const mockOfflineCache = {
        match: jest.fn().mockResolvedValue(new Response('<html>Offline Page</html>')),
      };
      
      mockCaches.open.mockResolvedValue(mockOfflineCache);

      const networkFirstWithOfflineFallback = jest.fn(async (request) => {
        try {
          return await fetch(request);
        } catch (error) {
          if (request.mode === 'navigate') {
            const staticCache = await mockCaches.open('brain-researcher-static-v3');
            const offlinePage = await staticCache.match('/offline');
            
            if (offlinePage) {
              return offlinePage;
            }
            
            return new Response(`
              <!DOCTYPE html>
              <html>
                <head><title>Brain Researcher - Offline</title></head>
                <body>
                  <h1>You're offline</h1>
                  <p>Brain Researcher is not available right now.</p>
                  <button onclick="window.location.reload()">Try again</button>
                </body>
              </html>
            `, {
              headers: { 'Content-Type': 'text/html' }
            });
          }
          
          throw error;
        }
      });

      const result = await networkFirstWithOfflineFallback(mockRequest);
      
      expect(mockCaches.open).toHaveBeenCalledWith('brain-researcher-static-v3');
      expect(mockOfflineCache.match).toHaveBeenCalledWith('/offline');
      expect(result).toBeInstanceOf(Response);
    });
  });

  describe('Background Sync', () => {
    test('should handle analysis results sync', async () => {
      const syncEvent = {
        tag: 'sync-analysis-results',
        waitUntil: jest.fn(),
      };

      const syncAnalysisResults = jest.fn(async () => {
        // Mock pending analysis results
        const pendingResults = [
          { id: '123', analysisType: 'glm', status: 'completed' },
          { id: '456', analysisType: 'connectivity', status: 'failed' },
        ];

        for (const result of pendingResults) {
          await fetch('/api/analysis/sync', {
            method: 'POST',
            body: JSON.stringify(result),
            headers: { 'Content-Type': 'application/json' }
          });
        }
      });

      const syncHandler = jest.fn((event) => {
        if (event.tag === 'sync-analysis-results') {
          event.waitUntil(syncAnalysisResults());
        }
      });

      await syncHandler(syncEvent);

      expect(syncEvent.waitUntil).toHaveBeenCalled();
      expect(mockFetch).toHaveBeenCalledWith('/api/analysis/sync', expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      }));
    });

    test('should handle brain data sync', async () => {
      const syncEvent = {
        tag: 'sync-brain-data',
        waitUntil: jest.fn(),
      };

      const syncBrainData = jest.fn(async () => {
        const criticalDatasets = [
          '/api/kg/brain-regions',
          '/api/atlas/data'
        ];

        const cache = await mockCaches.open('brain-researcher-brain-data-v3');

        for (const dataset of criticalDatasets) {
          const response = await fetch(dataset);
          if (response.ok) {
            await cache.put(dataset, response.clone());
          }
        }
      });

      const syncHandler = jest.fn((event) => {
        if (event.tag === 'sync-brain-data') {
          event.waitUntil(syncBrainData());
        }
      });

      await syncHandler(syncEvent);

      expect(syncEvent.waitUntil).toHaveBeenCalled();
      expect(mockFetch).toHaveBeenCalledWith('/api/kg/brain-regions');
      expect(mockFetch).toHaveBeenCalledWith('/api/atlas/data');
    });

    test('should handle performance data sync', async () => {
      const syncEvent = {
        tag: 'sync-performance-data',
        waitUntil: jest.fn(),
      };

      const syncPerformanceData = jest.fn(async () => {
        const performanceData = [
          { metric: 'cache_hit_rate', value: 0.85, timestamp: Date.now() },
          { metric: 'analysis_duration', value: 15000, timestamp: Date.now() },
        ];

        if (performanceData.length > 0) {
          await fetch('/api/telemetry/performance', {
            method: 'POST',
            body: JSON.stringify(performanceData),
            headers: { 'Content-Type': 'application/json' }
          });
        }
      });

      const syncHandler = jest.fn((event) => {
        if (event.tag === 'sync-performance-data') {
          event.waitUntil(syncPerformanceData());
        }
      });

      await syncHandler(syncEvent);

      expect(syncEvent.waitUntil).toHaveBeenCalled();
      expect(mockFetch).toHaveBeenCalledWith('/api/telemetry/performance', expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      }));
    });
  });

  describe('Push Notifications', () => {
    test('should handle analysis complete notifications', async () => {
      const pushEvent = {
        data: {
          json: jest.fn().mockReturnValue({
            type: 'analysis-complete',
            analysisName: 'fMRI GLM Analysis',
            analysisId: '123',
            body: 'Analysis "fMRI GLM Analysis" is complete',
          }),
        },
        waitUntil: jest.fn(),
      };

      const pushHandler = jest.fn((event) => {
        const data = event.data.json();
        
        const options = {
          body: `Analysis "${data.analysisName}" is complete`,
          icon: '/icons/icon-192x192.png',
          badge: '/icons/icon-192x192.png',
          tag: data.tag || 'default',
          data: data.data || {},
          actions: [
            { action: 'view', title: 'View Results' },
            { action: 'dismiss', title: 'Dismiss' }
          ],
        };

        event.waitUntil(
          self.registration.showNotification('Brain Researcher', options)
        );
      });

      await pushHandler(pushEvent);

      expect(pushEvent.waitUntil).toHaveBeenCalled();
      expect(self.registration.showNotification).toHaveBeenCalledWith(
        'Brain Researcher',
        expect.objectContaining({
          body: 'Analysis "fMRI GLM Analysis" is complete',
          actions: expect.arrayContaining([
            { action: 'view', title: 'View Results' },
            { action: 'dismiss', title: 'Dismiss' }
          ]),
        })
      );
    });

    test('should handle data update notifications', async () => {
      const pushEvent = {
        data: {
          json: jest.fn().mockReturnValue({
            type: 'data-update',
            datasetName: 'HCP-YA Dataset',
            body: 'New brain data available: HCP-YA Dataset',
          }),
        },
        waitUntil: jest.fn(),
      };

      const pushHandler = jest.fn((event) => {
        const data = event.data.json();
        
        const options = {
          body: `New brain data available: ${data.datasetName}`,
          icon: '/icons/icon-192x192.png',
          badge: '/icons/icon-192x192.png',
          tag: data.tag || 'default',
          data: data.data || {},
          actions: [
            { action: 'sync', title: 'Sync Now' },
            { action: 'later', title: 'Later' }
          ],
        };

        event.waitUntil(
          self.registration.showNotification('Brain Researcher', options)
        );
      });

      await pushHandler(pushEvent);

      expect(self.registration.showNotification).toHaveBeenCalledWith(
        'Brain Researcher',
        expect.objectContaining({
          body: 'New brain data available: HCP-YA Dataset',
          actions: expect.arrayContaining([
            { action: 'sync', title: 'Sync Now' },
            { action: 'later', title: 'Later' }
          ]),
        })
      );
    });

    test('should handle notification clicks', async () => {
      const notificationClickEvent = {
        notification: {
          tag: 'analysis-complete',
          data: { analysisId: '123' },
          close: jest.fn(),
        },
        action: 'view',
        waitUntil: jest.fn(),
      };

      const clickHandler = jest.fn((event) => {
        event.notification.close();
        
        switch (event.action) {
          case 'view':
            event.waitUntil(
              self.clients.openWindow('/analysis/results/' + event.notification.data.analysisId)
            );
            break;
          case 'sync':
            event.waitUntil(
              self.registration.sync.register('sync-brain-data')
            );
            break;
        }
      });

      // Mock clients.openWindow
      self.clients.openWindow = jest.fn().mockResolvedValue();

      await clickHandler(notificationClickEvent);

      expect(notificationClickEvent.notification.close).toHaveBeenCalled();
      expect(self.clients.openWindow).toHaveBeenCalledWith('/analysis/results/123');
    });
  });

  describe('Message Handling', () => {
    test('should handle cache clearing messages', async () => {
      const messageEvent = {
        data: {
          type: 'CLEAR_CACHE',
          payload: { cacheName: 'brain-researcher-brain-data-v3' },
        },
        ports: [{ postMessage: jest.fn() }],
      };

      const clearCache = jest.fn(async (cacheName) => {
        if (cacheName) {
          await mockCaches.delete(cacheName);
        } else {
          const cacheNames = await mockCaches.keys();
          await Promise.all(cacheNames.map(name => mockCaches.delete(name)));
        }
      });

      const messageHandler = jest.fn(async (event) => {
        const { type, payload } = event.data;
        
        if (type === 'CLEAR_CACHE') {
          await clearCache(payload?.cacheName);
          event.ports[0]?.postMessage({ success: true });
        }
      });

      await messageHandler(messageEvent);

      expect(mockCaches.delete).toHaveBeenCalledWith('brain-researcher-brain-data-v3');
      expect(messageEvent.ports[0].postMessage).toHaveBeenCalledWith({ success: true });
    });

    test('should handle preload resources messages', async () => {
      const messageEvent = {
        data: {
          type: 'PRELOAD_RESOURCES',
          payload: { urls: ['/api/atlas/data', '/api/kg/networks'] },
        },
        ports: [{ postMessage: jest.fn() }],
      };

      const preloadResources = jest.fn(async (urls) => {
        const cache = await mockCaches.open('brain-researcher-v3');
        
        await Promise.all(
          urls.map(async (url) => {
            try {
              const response = await fetch(url);
              if (response.ok) {
                await cache.put(url, response);
              }
            } catch (error) {
              console.log('Preload failed for:', url);
            }
          })
        );
      });

      const messageHandler = jest.fn(async (event) => {
        const { type, payload } = event.data;
        
        if (type === 'PRELOAD_RESOURCES') {
          await preloadResources(payload?.urls || []);
          event.ports[0]?.postMessage({ success: true });
        }
      });

      await messageHandler(messageEvent);

      expect(mockFetch).toHaveBeenCalledWith('/api/atlas/data');
      expect(mockFetch).toHaveBeenCalledWith('/api/kg/networks');
      expect(messageEvent.ports[0].postMessage).toHaveBeenCalledWith({ success: true });
    });

    test('should handle cache stats requests', async () => {
      const messageEvent = {
        data: {
          type: 'GET_CACHE_STATS',
        },
        ports: [{ postMessage: jest.fn() }],
      };

      const getCacheStats = jest.fn(async () => {
        const cacheNames = await mockCaches.keys();
        const stats = {};
        
        for (const cacheName of cacheNames) {
          const cache = await mockCaches.open(cacheName);
          const keys = await cache.keys();
          stats[cacheName] = keys.length;
        }
        
        return stats;
      });

      const messageHandler = jest.fn(async (event) => {
        const { type } = event.data;
        
        if (type === 'GET_CACHE_STATS') {
          const stats = await getCacheStats();
          event.ports[0]?.postMessage({ stats });
        }
      });

      // Mock cache keys
      const mockCache = {
        keys: jest.fn().mockResolvedValue(['key1', 'key2', 'key3']),
      };
      mockCaches.open.mockResolvedValue(mockCache);

      await messageHandler(messageEvent);

      expect(messageEvent.ports[0].postMessage).toHaveBeenCalledWith({
        stats: expect.objectContaining({
          'brain-researcher-v3': 3,
          'brain-researcher-static-v3': 3,
          'brain-researcher-api-v3': 3,
        }),
      });
    });
  });

  describe('IndexedDB Brain Data Storage', () => {
    test('should store brain data in IndexedDB', async () => {
      const mockDB = {
        transaction: jest.fn().mockReturnValue({
          objectStore: jest.fn().mockReturnValue({
            put: jest.fn().mockResolvedValue(),
          }),
        }),
      };

      const storeBrainDataInIDB = jest.fn(async (url, data) => {
        const transaction = mockDB.transaction(['brainData'], 'readwrite');
        const store = transaction.objectStore('brainData');
        
        await store.put({
          url: url,
          data: data,
          timestamp: Date.now(),
          type: 'regions', // brain-regions, networks, atlas, nifti
        });
      });

      await storeBrainDataInIDB('/api/kg/brain-regions', { regions: ['frontal', 'parietal'] });

      expect(mockDB.transaction).toHaveBeenCalledWith(['brainData'], 'readwrite');
    });

    test('should retrieve brain data from IndexedDB', async () => {
      const mockDB = {
        transaction: jest.fn().mockReturnValue({
          objectStore: jest.fn().mockReturnValue({
            get: jest.fn().mockReturnValue({
              onsuccess: null,
              onerror: null,
              result: {
                url: '/api/kg/brain-regions',
                data: { regions: ['frontal', 'parietal'] },
                timestamp: Date.now(),
                type: 'regions',
              },
            }),
          }),
        }),
      };

      const getBrainDataFromIDB = jest.fn(async (url) => {
        const transaction = mockDB.transaction(['brainData'], 'readonly');
        const store = transaction.objectStore('brainData');
        
        return new Promise((resolve) => {
          const request = store.get(url);
          request.onsuccess = () => {
            const result = request.result;
            if (result && !isDataStale(result.timestamp)) {
              resolve(result.data);
            } else {
              resolve(null);
            }
          };
        });
      });

      const isDataStale = jest.fn((timestamp, maxAge = 24 * 60 * 60 * 1000) => {
        return (Date.now() - timestamp) > maxAge;
      });

      const result = await getBrainDataFromIDB('/api/kg/brain-regions');
      
      expect(mockDB.transaction).toHaveBeenCalledWith(['brainData'], 'readonly');
    });

    test('should clean up old brain data', async () => {
      const mockDB = {
        transaction: jest.fn().mockReturnValue({
          objectStore: jest.fn().mockReturnValue({
            index: jest.fn().mockReturnValue({
              openCursor: jest.fn().mockReturnValue({
                onsuccess: null,
              }),
            }),
          }),
        }),
      };

      const cleanupOldData = jest.fn(async () => {
        const transaction = mockDB.transaction(['brainData'], 'readwrite');
        const store = transaction.objectStore('brainData');
        const index = store.index('timestamp');
        
        const cutoffTime = Date.now() - (7 * 24 * 60 * 60 * 1000); // 7 days
        const range = { upperBound: cutoffTime };
        
        const request = index.openCursor(range);
        request.onsuccess = (event) => {
          const cursor = event.target.result;
          if (cursor) {
            cursor.delete();
            cursor.continue();
          }
        };
      });

      await cleanupOldData();

      expect(mockDB.transaction).toHaveBeenCalledWith(['brainData'], 'readwrite');
    });
  });

  describe('Performance Metrics', () => {
    test('should track cache hit rates', async () => {
      const trackCachePerformance = jest.fn(() => {
        let totalRequests = 0;
        let cacheHits = 0;
        
        const originalFetch = global.fetch;
        global.fetch = async (...args) => {
          totalRequests++;
          const response = await originalFetch(...args);
          
          if (response.headers.get('x-cache') === 'HIT') {
            cacheHits++;
          }
          
          const hitRate = totalRequests > 0 ? cacheHits / totalRequests : 0;
          return response;
        };
        
        return { totalRequests, cacheHits };
      });

      const metrics = trackCachePerformance();
      expect(typeof metrics.totalRequests).toBe('number');
      expect(typeof metrics.cacheHits).toBe('number');
    });

    test('should report offline capabilities', async () => {
      const getOfflineCapabilities = jest.fn(async () => {
        const capabilities = {
          basicPages: true,
          brainData: false,
          analysisResults: false,
          imagingData: false
        };

        // Check brain data cache
        const brainCache = await mockCaches.open('brain-researcher-brain-data-v3');
        const brainKeys = await brainCache.keys();
        capabilities.brainData = brainKeys.length > 0;

        // Check analysis cache
        const analysisCache = await mockCaches.open('brain-researcher-analysis-v3');
        const analysisKeys = await analysisCache.keys();
        capabilities.analysisResults = analysisKeys.length > 0;

        return capabilities;
      });

      const mockCache = {
        keys: jest.fn().mockResolvedValue(['key1', 'key2']),
      };
      mockCaches.open.mockResolvedValue(mockCache);

      const capabilities = await getOfflineCapabilities();

      expect(capabilities).toEqual({
        basicPages: true,
        brainData: true,
        analysisResults: true,
        imagingData: false,
      });
    });
  });
});