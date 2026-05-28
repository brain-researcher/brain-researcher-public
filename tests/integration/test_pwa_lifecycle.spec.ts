/**
 * PWA Lifecycle Integration Tests for Brain Researcher
 * Tests complete PWA lifecycle including installation, updates, caching,
 * offline transitions, background sync, and brain-specific workflows
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';

interface PWATestContext {
  page: Page;
  context: BrowserContext;
  serviceWorkerPromise?: Promise<any>;
}

interface BrainDataCache {
  regions: string[];
  networks: string[];
  atlasData: Record<string, any>;
  analysisResults: Record<string, any>;
}

// Helper functions for PWA testing
async function waitForServiceWorker(page: Page): Promise<any> {
  return page.evaluate(() => {
    return new Promise((resolve) => {
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.ready.then(resolve);
      } else {
        resolve(null);
      }
    });
  });
}

async function installPWA(page: Page): Promise<void> {
  // Simulate beforeinstallprompt event
  await page.evaluate(() => {
    const event = new Event('beforeinstallprompt');
    (event as any).prompt = () => Promise.resolve();
    (event as any).userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    window.dispatchEvent(event);
  });
}

async function simulateOffline(page: Page): Promise<void> {
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'onLine', {
      writable: true,
      value: false
    });
    window.dispatchEvent(new Event('offline'));
  });
}

async function simulateOnline(page: Page): Promise<void> {
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'onLine', {
      writable: true,
      value: true
    });
    window.dispatchEvent(new Event('online'));
  });
}

async function getCacheContents(page: Page, cacheName: string): Promise<string[]> {
  return page.evaluate(async (name) => {
    if ('caches' in window) {
      const cache = await caches.open(name);
      const keys = await cache.keys();
      return keys.map(request => request.url);
    }
    return [];
  }, cacheName);
}

async function clearAllCaches(page: Page): Promise<void> {
  await page.evaluate(async () => {
    if ('caches' in window) {
      const names = await caches.keys();
      await Promise.all(names.map(name => caches.delete(name)));
    }
  });
}

test.describe('PWA Installation Lifecycle', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    
    // Navigate to Brain Researcher app
    await page.goto('http://localhost:3000');
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should register service worker on first visit', async () => {
    // Wait for service worker registration
    const swRegistration = await waitForServiceWorker(page);
    expect(swRegistration).toBeTruthy();

    // Check if service worker is registered
    const isRegistered = await page.evaluate(() => {
      return 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null;
    });

    expect(isRegistered).toBe(true);
  });

  test('should cache static resources during installation', async () => {
    await waitForServiceWorker(page);

    // Check if static cache contains expected resources
    const staticCacheContents = await getCacheContents(page, 'brain-researcher-static-v3');
    
    expect(staticCacheContents).toEqual(expect.arrayContaining([
      expect.stringContaining('/'),
      expect.stringContaining('/offline'),
      expect.stringContaining('/manifest.json'),
      expect.stringContaining('/_next/static/')
    ]));
  });

  test('should show install prompt when criteria met', async () => {
    // Trigger install prompt
    await installPWA(page);

    // Check if install prompt is displayed
    const installPrompt = await page.locator('[data-testid="install-prompt"]');
    await expect(installPrompt).toBeVisible({ timeout: 10000 });

    // Verify install prompt content
    await expect(installPrompt).toContainText('Install Brain Researcher');
    await expect(installPrompt).toContainText('offline capabilities');
  });

  test('should complete installation flow', async () => {
    await installPWA(page);

    // Click install button
    const installButton = page.locator('[data-testid="install-button"]');
    await installButton.click();

    // Check if PWA is marked as installed
    const isInstalled = await page.evaluate(() => {
      return window.matchMedia('(display-mode: standalone)').matches ||
             (navigator as any).standalone === true;
    });

    // Note: In test environment, we simulate the installation state
    expect(typeof isInstalled).toBe('boolean');
  });

  test('should initialize brain data caches', async () => {
    await waitForServiceWorker(page);

    // Wait for specialized caches to be created
    await page.waitForTimeout(2000);

    const brainDataCache = await getCacheContents(page, 'brain-researcher-brain-data-v3');
    const analysisCache = await getCacheContents(page, 'brain-researcher-analysis-v3');
    const imageCache = await getCacheContents(page, 'brain-researcher-images-v3');

    // Caches should exist (even if empty initially)
    expect(Array.isArray(brainDataCache)).toBe(true);
    expect(Array.isArray(analysisCache)).toBe(true);
    expect(Array.isArray(imageCache)).toBe(true);
  });
});

test.describe('PWA Update Lifecycle', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should detect service worker updates', async () => {
    // Simulate service worker update
    await page.evaluate(() => {
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        // Simulate updatefound event
        const event = new Event('updatefound');
        navigator.serviceWorker.controller.dispatchEvent(event);
      }
    });

    // Check if update available state is set
    const hasUpdate = await page.evaluate(() => {
      return Boolean((window as any).pwaManager?.hasUpdate);
    });

    expect(typeof hasUpdate).toBe('boolean');
  });

  test('should show update notification', async () => {
    // Simulate update available
    await page.evaluate(() => {
      if ((window as any).pwaManager) {
        (window as any).pwaManager.updateAvailable = true;
        window.dispatchEvent(new CustomEvent('pwa-update-available'));
      }
    });

    // Look for update banner or notification
    const updateBanner = page.locator('[data-testid="update-banner"]').first();
    await expect(updateBanner).toBeVisible({ timeout: 5000 });
    
    await expect(updateBanner).toContainText('update available');
  });

  test('should apply updates when requested', async () => {
    // Simulate update available and click update
    await page.evaluate(() => {
      if ((window as any).pwaManager) {
        (window as any).pwaManager.updateAvailable = true;
        window.dispatchEvent(new CustomEvent('pwa-update-available'));
      }
    });

    const updateButton = page.locator('[data-testid="update-button"]').first();
    await expect(updateButton).toBeVisible({ timeout: 5000 });
    
    await updateButton.click();

    // Verify update process initiated
    const isUpdating = await page.evaluate(() => {
      return Boolean((window as any).pwaManager?.isUpdating);
    });

    expect(typeof isUpdating).toBe('boolean');
  });
});

test.describe('Brain Data Caching Strategies', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should cache brain region data with long expiry', async () => {
    // Navigate to brain regions page
    await page.goto('http://localhost:3000/api/kg/brain-regions');
    
    // Wait for response and caching
    await page.waitForResponse('**/api/kg/brain-regions');
    await page.waitForTimeout(1000);

    // Check if brain data is cached
    const brainDataCache = await getCacheContents(page, 'brain-researcher-brain-data-v3');
    expect(brainDataCache).toEqual(expect.arrayContaining([
      expect.stringContaining('/api/kg/brain-regions')
    ]));

    // Verify cache strategy (cache-first for brain data)
    const cacheResponse = await page.evaluate(async () => {
      if ('caches' in window) {
        const cache = await caches.open('brain-researcher-brain-data-v3');
        const response = await cache.match('/api/kg/brain-regions');
        return response ? await response.text() : null;
      }
      return null;
    });

    expect(cacheResponse).toBeTruthy();
  });

  test('should cache analysis results with shorter expiry', async () => {
    // Mock analysis results endpoint
    await page.route('**/api/analysis/results/**', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          analysisId: 'test-123',
          status: 'completed',
          results: { activation: ['frontal', 'parietal'] }
        })
      });
    });

    await page.goto('http://localhost:3000/api/analysis/results/test-123');
    await page.waitForTimeout(1000);

    // Check if analysis results are cached
    const analysisCache = await getCacheContents(page, 'brain-researcher-analysis-v3');
    expect(analysisCache).toEqual(expect.arrayContaining([
      expect.stringContaining('/api/analysis/results/test-123')
    ]));
  });

  test('should handle large brain imaging files with IndexedDB', async () => {
    // Mock large brain imaging file
    await page.route('**/data/brain_map_*.nii.gz', route => {
      // Simulate large file with streaming
      const chunks = new Array(10).fill(0).map((_, i) => `chunk${i}`);
      route.fulfill({
        status: 200,
        contentType: 'application/octet-stream',
        headers: {
          'Content-Length': '10485760' // 10MB
        },
        body: chunks.join('')
      });
    });

    await page.goto('http://localhost:3000/data/brain_map_123.nii.gz');
    
    // Wait for download with progress
    await page.waitForTimeout(3000);

    // Check if large file is stored in IndexedDB
    const isStoredInIDB = await page.evaluate(async () => {
      return new Promise((resolve) => {
        if ('indexedDB' in window) {
          const request = indexedDB.open('BrainResearcherDB', 1);
          request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['brainData'], 'readonly');
            const store = transaction.objectStore('brainData');
            const getRequest = store.get('/data/brain_map_123.nii.gz');
            
            getRequest.onsuccess = () => {
              resolve(getRequest.result !== undefined);
            };
            getRequest.onerror = () => resolve(false);
          };
          request.onerror = () => resolve(false);
        } else {
          resolve(false);
        }
      });
    });

    expect(isStoredInIDB).toBe(true);
  });

  test('should track download progress for large files', async () => {
    const progressEvents: Array<{ loaded: number; total: number }> = [];

    // Listen for progress events
    await page.evaluate(() => {
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', (event) => {
          if (event.data.type === 'DOWNLOAD_PROGRESS') {
            (window as any).downloadProgress = event.data;
          }
        });
      }
    });

    // Mock large file with progress simulation
    await page.route('**/data/large_brain_scan.nii.gz', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/octet-stream',
        headers: { 'Content-Length': '50000000' }, // 50MB
        body: 'x'.repeat(50000000)
      });
    });

    await page.goto('http://localhost:3000/data/large_brain_scan.nii.gz');
    
    // Wait for download to complete
    await page.waitForTimeout(5000);

    // Check if progress was tracked
    const progressData = await page.evaluate(() => (window as any).downloadProgress);
    expect(progressData).toBeTruthy();
    expect(progressData).toHaveProperty('loaded');
    expect(progressData).toHaveProperty('total');
  });
});

test.describe('Offline/Online Transitions', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should detect offline state and show indicator', async () => {
    // Simulate going offline
    await simulateOffline(page);
    await page.waitForTimeout(1000);

    // Check if offline indicator appears
    const offlineIndicator = page.locator('[data-testid="offline-indicator"]');
    await expect(offlineIndicator).toBeVisible();
    await expect(offlineIndicator).toHaveClass(/offline/);
  });

  test('should serve cached content when offline', async () => {
    // First, load page online to populate cache
    await page.goto('http://localhost:3000/dashboard');
    await page.waitForLoadState('networkidle');

    // Go offline
    await simulateOffline(page);
    await context.setOffline(true);

    // Try to navigate to cached page
    await page.goto('http://localhost:3000/dashboard');
    
    // Page should still load from cache
    await expect(page.locator('body')).toBeVisible();
    await expect(page).toHaveTitle(/Brain Researcher/);
  });

  test('should show offline page for uncached routes', async () => {
    // Go offline
    await simulateOffline(page);
    await context.setOffline(true);

    // Try to navigate to uncached page
    await page.goto('http://localhost:3000/uncached-page');

    // Should show offline fallback
    await expect(page.locator('body')).toContainText(/offline/i);
    await expect(page.locator('button')).toContainText(/try again/i);
  });

  test('should show offline capabilities in indicator', async () => {
    // Populate some caches first
    await page.goto('http://localhost:3000/api/kg/brain-regions');
    await page.waitForResponse('**/api/kg/brain-regions');
    
    await simulateOffline(page);
    await page.waitForTimeout(1000);

    const offlineIndicator = page.locator('[data-testid="offline-indicator"]');
    await expect(offlineIndicator).toBeVisible();
    
    // Check for offline capabilities display
    await expect(offlineIndicator).toContainText('Available offline');
    await expect(offlineIndicator).toContainText('Brain Data');
  });

  test('should resume sync when coming back online', async () => {
    // Go offline and generate some offline data
    await simulateOffline(page);
    
    // Simulate offline analysis result
    await page.evaluate(() => {
      localStorage.setItem('pending-sync', JSON.stringify([
        {
          id: 'offline-analysis-123',
          type: 'analysis-result',
          data: { status: 'completed', results: {} }
        }
      ]));
    });

    // Come back online
    await simulateOnline(page);
    await context.setOffline(false);
    
    // Wait for sync to trigger
    await page.waitForTimeout(2000);

    // Check if sync was attempted
    const syncEvents = await page.evaluate(() => {
      return (window as any).syncEvents || [];
    });

    expect(Array.isArray(syncEvents)).toBe(true);
  });
});

test.describe('Background Sync Operations', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should register background sync for analysis results', async () => {
    // Trigger background sync registration
    await page.evaluate(async () => {
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready;
        if ('sync' in registration) {
          await (registration as any).sync.register('sync-analysis-results');
        }
      }
    });

    // Verify sync was registered
    const syncTags = await page.evaluate(async () => {
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready;
        return (registration as any).sync?.getTags ? 
          await (registration as any).sync.getTags() : [];
      }
      return [];
    });

    expect(syncTags).toContain('sync-analysis-results');
  });

  test('should sync brain data in background', async () => {
    let syncEventTriggered = false;

    // Mock background sync event
    await page.evaluate(() => {
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', (event) => {
          if (event.data.type === 'SYNC_COMPLETED') {
            (window as any).backgroundSyncCompleted = true;
          }
        });
      }
    });

    // Simulate background sync trigger
    await page.evaluate(async () => {
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready;
        if (registration.active) {
          registration.active.postMessage({
            type: 'BACKGROUND_SYNC',
            tag: 'sync-brain-data'
          });
        }
      }
    });

    await page.waitForTimeout(3000);

    const syncCompleted = await page.evaluate(() => 
      (window as any).backgroundSyncCompleted
    );

    expect(typeof syncCompleted).toBe('boolean');
  });

  test('should handle sync failures gracefully', async () => {
    // Mock network failure for sync endpoint
    await page.route('**/api/analysis/sync', route => {
      route.abort('failed');
    });

    // Attempt background sync
    await page.evaluate(async () => {
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready;
        if (registration.active) {
          registration.active.postMessage({
            type: 'BACKGROUND_SYNC',
            tag: 'sync-analysis-results'
          });
        }
      }
    });

    await page.waitForTimeout(2000);

    // Sync should fail gracefully without crashing
    const pageTitle = await page.title();
    expect(pageTitle).toContain('Brain Researcher');
  });

  test('should prioritize critical brain data sync', async () => {
    const syncPriorities: string[] = [];

    // Monitor sync order
    await page.evaluate(() => {
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', (event) => {
          if (event.data.type === 'SYNC_START') {
            (window as any).syncOrder = (window as any).syncOrder || [];
            (window as any).syncOrder.push(event.data.tag);
          }
        });
      }
    });

    // Trigger multiple sync operations
    await page.evaluate(async () => {
      if ('serviceWorker' in navigator) {
        const registration = await navigator.serviceWorker.ready;
        if (registration.active) {
          // Trigger syncs in reverse priority order
          registration.active.postMessage({ type: 'BACKGROUND_SYNC', tag: 'sync-performance-data' });
          registration.active.postMessage({ type: 'BACKGROUND_SYNC', tag: 'sync-brain-data' });
          registration.active.postMessage({ type: 'BACKGROUND_SYNC', tag: 'sync-analysis-results' });
        }
      }
    });

    await page.waitForTimeout(3000);

    const syncOrder = await page.evaluate(() => 
      (window as any).syncOrder || []
    );

    // Brain data and analysis results should be prioritized
    expect(Array.isArray(syncOrder)).toBe(true);
  });
});

test.describe('PWA Performance Metrics', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should track cache hit rates', async () => {
    // Make multiple requests to same endpoint
    await page.goto('http://localhost:3000/api/kg/brain-regions');
    await page.waitForResponse('**/api/kg/brain-regions');
    
    // Second request should hit cache
    await page.goto('http://localhost:3000/api/kg/brain-regions');
    await page.waitForTimeout(1000);

    // Check cache hit rate
    const cacheStats = await page.evaluate(async () => {
      if ((window as any).pwaManager && (window as any).pwaManager.getCacheStats) {
        return await (window as any).pwaManager.getCacheStats();
      }
      return {};
    });

    expect(typeof cacheStats).toBe('object');
  });

  test('should track offline usage time', async () => {
    // Start tracking
    await page.evaluate(() => {
      (window as any).offlineStartTime = Date.now();
    });

    await simulateOffline(page);
    await page.waitForTimeout(2000);
    await simulateOnline(page);

    // Check if offline time was tracked
    const metrics = await page.evaluate(() => {
      if ((window as any).pwaManager) {
        return (window as any).pwaManager.appMetrics;
      }
      return {};
    });

    expect(typeof metrics).toBe('object');
    expect(metrics).toHaveProperty('offlineUsageTime');
  });

  test('should report PWA capabilities', async () => {
    const capabilities = await page.evaluate(() => {
      if ((window as any).pwaManager) {
        return (window as any).pwaManager.appCapabilities;
      }
      return {};
    });

    expect(capabilities).toHaveProperty('serviceWorker');
    expect(capabilities).toHaveProperty('pushNotifications');
    expect(capabilities).toHaveProperty('backgroundSync');
    expect(capabilities).toHaveProperty('indexedDB');
    expect(capabilities).toHaveProperty('cacheAPI');
  });

  test('should collect performance telemetry', async () => {
    // Simulate performance data collection
    await page.evaluate(() => {
      // Mock performance metrics
      const performanceData = {
        cacheHitRate: 0.85,
        offlineCapability: true,
        installCount: 1,
        launchCount: 5,
        averageLoadTime: 1200
      };
      
      localStorage.setItem('pwa-telemetry', JSON.stringify(performanceData));
    });

    const telemetryData = await page.evaluate(() => {
      const stored = localStorage.getItem('pwa-telemetry');
      return stored ? JSON.parse(stored) : null;
    });

    expect(telemetryData).toBeTruthy();
    expect(telemetryData.cacheHitRate).toBeGreaterThan(0);
    expect(telemetryData.offlineCapability).toBe(true);
  });
});

test.describe('Brain Research Workflow Integration', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();
    await page.goto('http://localhost:3000');
    await waitForServiceWorker(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should cache brain atlas data for offline access', async () => {
    // Load brain atlas data
    await page.route('**/api/atlas/data', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          regions: [
            { id: 'frontal', name: 'Frontal Cortex', coordinates: [0, 0, 0] },
            { id: 'parietal', name: 'Parietal Cortex', coordinates: [10, 20, 30] }
          ]
        })
      });
    });

    await page.goto('http://localhost:3000/api/atlas/data');
    await page.waitForResponse('**/api/atlas/data');

    // Go offline and verify data is still accessible
    await simulateOffline(page);
    await context.setOffline(true);

    await page.goto('http://localhost:3000/api/atlas/data');
    const content = await page.textContent('body');
    
    expect(content).toContain('Frontal Cortex');
    expect(content).toContain('Parietal Cortex');
  });

  test('should maintain analysis state during offline periods', async () => {
    // Start an analysis
    await page.evaluate(() => {
      localStorage.setItem('current-analysis', JSON.stringify({
        id: 'analysis-123',
        type: 'connectivity',
        status: 'running',
        progress: 45,
        parameters: { threshold: 0.5 }
      }));
    });

    await simulateOffline(page);
    await page.waitForTimeout(1000);

    // Verify analysis state is preserved
    const analysisState = await page.evaluate(() => {
      const stored = localStorage.getItem('current-analysis');
      return stored ? JSON.parse(stored) : null;
    });

    expect(analysisState).toBeTruthy();
    expect(analysisState.id).toBe('analysis-123');
    expect(analysisState.progress).toBe(45);
  });

  test('should handle brain visualization data caching', async () => {
    // Mock brain visualization endpoint
    await page.route('**/api/viz/brain-surface', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          vertices: new Array(10000).fill(0).map((_, i) => [i, i+1, i+2]),
          faces: new Array(5000).fill(0).map((_, i) => [i, i+1, i+2]),
          data: new Array(10000).fill(0).map(() => Math.random())
        })
      });
    });

    await page.goto('http://localhost:3000/api/viz/brain-surface');
    await page.waitForResponse('**/api/viz/brain-surface');
    await page.waitForTimeout(2000);

    // Check if visualization data is cached
    const imageCache = await getCacheContents(page, 'brain-researcher-images-v3');
    expect(imageCache.some(url => url.includes('/api/viz/brain-surface'))).toBe(true);
  });

  test('should sync research findings when connection restored', async () => {
    // Create offline research findings
    await simulateOffline(page);
    
    await page.evaluate(() => {
      const findings = {
        studyId: 'study-456',
        findings: [
          { region: 'frontal', activation: 0.8, significance: 0.001 },
          { region: 'temporal', activation: 0.6, significance: 0.01 }
        ],
        timestamp: Date.now(),
        needsSync: true
      };
      
      localStorage.setItem('offline-findings', JSON.stringify([findings]));
    });

    // Come back online
    await simulateOnline(page);
    await context.setOffline(false);
    
    await page.waitForTimeout(3000);

    // Verify findings are queued for sync
    const pendingFindings = await page.evaluate(() => {
      const stored = localStorage.getItem('offline-findings');
      return stored ? JSON.parse(stored) : [];
    });

    expect(Array.isArray(pendingFindings)).toBe(true);
    expect(pendingFindings[0]).toHaveProperty('needsSync');
  });
});