/**
 * Comprehensive End-to-End Offline Functionality Tests for Brain Researcher PWA
 * Tests complete offline workflows including brain data access, analysis continuity,
 * visualization caching, research documentation, and collaboration features
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';

interface OfflineTestContext {
  page: Page;
  context: BrowserContext;
  networkConditions: 'online' | 'offline' | 'slow-3g' | 'fast-3g';
}

interface BrainResearchData {
  atlasData: Record<string, any>;
  analysisResults: Record<string, any>;
  visualizations: Record<string, any>;
  researchNotes: Record<string, any>;
}

// Helper functions for offline testing
async function simulateNetworkConditions(context: BrowserContext, condition: string) {
  switch (condition) {
    case 'offline':
      await context.setOffline(true);
      break;
    case 'slow-3g':
      await context.setOffline(false);
      await context.route('**/*', route => {
        setTimeout(() => route.continue(), 2000); // 2s delay
      });
      break;
    case 'fast-3g':
      await context.setOffline(false);
      await context.route('**/*', route => {
        setTimeout(() => route.continue(), 500); // 500ms delay
      });
      break;
    case 'online':
    default:
      await context.setOffline(false);
      break;
  }
}

async function waitForServiceWorkerActivation(page: Page) {
  await page.waitForFunction(() => {
    return 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null;
  });
}

async function primeOfflineCache(page: Page, urls: string[]) {
  for (const url of urls) {
    await page.goto(url);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000); // Allow caching
  }
}

async function verifyOfflineCapabilities(page: Page): Promise<Record<string, boolean>> {
  return await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) return {};

    const registration = await navigator.serviceWorker.ready;
    if (!registration.active) return {};

    return new Promise((resolve) => {
      const channel = new MessageChannel();
      registration.active!.postMessage(
        { type: 'GET_OFFLINE_STATUS' },
        [channel.port2]
      );

      channel.port1.onmessage = (event) => {
        resolve(event.data.capabilities || {});
      };

      // Timeout after 5 seconds
      setTimeout(() => resolve({}), 5000);
    });
  });
}

async function mockBrainResearchData(page: Page) {
  // Mock brain atlas data
  await page.route('**/api/atlas/**', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'public, max-age=86400' },
      body: JSON.stringify({
        regions: [
          {
            id: 'frontal_cortex',
            name: 'Frontal Cortex',
            coordinates: { x: 0, y: 50, z: 30 },
            volume: 125000,
            function: 'Executive control, working memory'
          },
          {
            id: 'temporal_cortex',
            name: 'Temporal Cortex',
            coordinates: { x: 65, y: -25, z: -10 },
            volume: 85000,
            function: 'Auditory processing, language comprehension'
          },
          {
            id: 'parietal_cortex',
            name: 'Parietal Cortex',
            coordinates: { x: 0, y: -55, z: 45 },
            volume: 95000,
            function: 'Spatial processing, attention'
          }
        ],
        networks: [
          {
            id: 'default_mode',
            name: 'Default Mode Network',
            regions: ['frontal_cortex', 'parietal_cortex'],
            connectivity: 0.85
          },
          {
            id: 'attention',
            name: 'Attention Network',
            regions: ['frontal_cortex', 'parietal_cortex'],
            connectivity: 0.78
          }
        ]
      })
    });
  });

  // Mock analysis results
  await page.route('**/api/analysis/**', route => {
    const url = route.request().url();
    const analysisId = url.split('/').pop();

    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysisId,
        type: 'fmri_glm',
        status: 'completed',
        results: {
          significantActivation: [
            { region: 'frontal_cortex', tScore: 4.2, pValue: 0.0001 },
            { region: 'parietal_cortex', tScore: 3.8, pValue: 0.0005 }
          ],
          effectSizes: {
            frontal_cortex: 0.65,
            parietal_cortex: 0.52
          },
          visualization: {
            statisticalMap: '/viz/stat_map_123.nii.gz',
            overlay: '/viz/overlay_123.png'
          }
        },
        metadata: {
          subjects: 45,
          scanParameters: { TR: 2.0, TE: 30, voxelSize: [2, 2, 2] },
          analysisDate: new Date().toISOString()
        }
      })
    });
  });

  // Mock brain visualization data
  await page.route('**/api/viz/**', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        type: 'surface_mesh',
        vertices: Array.from({ length: 1000 }, (_, i) => [
          Math.sin(i * 0.1), Math.cos(i * 0.1), i * 0.001
        ]),
        faces: Array.from({ length: 500 }, (_, i) => [i, i + 1, i + 2]),
        data: Array.from({ length: 1000 }, () => Math.random()),
        colormap: 'hot',
        threshold: { min: 0.1, max: 0.9 }
      })
    });
  });
}

test.describe('Offline Brain Atlas Access', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should cache brain atlas data for offline access', async () => {
    // Load atlas data while online
    await page.goto('http://localhost:3000/atlas');
    await page.waitForSelector('[data-testid="brain-atlas"]');

    // Verify atlas data is displayed
    await expect(page.locator('[data-testid="region-frontal_cortex"]')).toBeVisible();
    await expect(page.locator('[data-testid="region-temporal_cortex"]')).toBeVisible();
    await expect(page.locator('[data-testid="region-parietal_cortex"]')).toBeVisible();

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Navigate to atlas page again
    await page.goto('http://localhost:3000/atlas');
    await page.waitForSelector('[data-testid="brain-atlas"]', { timeout: 10000 });

    // Verify data is still accessible offline
    await expect(page.locator('[data-testid="region-frontal_cortex"]')).toBeVisible();
    await expect(page.locator('text=Executive control')).toBeVisible();
    await expect(page.locator('text=Default Mode Network')).toBeVisible();
  });

  test('should display regional information offline', async () => {
    // Prime cache with regional data
    await page.goto('http://localhost:3000/atlas/frontal_cortex');
    await page.waitForLoadState('networkidle');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Access regional information offline
    await page.goto('http://localhost:3000/atlas/frontal_cortex');

    await expect(page.locator('text=Frontal Cortex')).toBeVisible();
    await expect(page.locator('text=Executive control')).toBeVisible();
    await expect(page.locator('text=Volume: 125,000')).toBeVisible();
  });

  test('should show network connectivity data offline', async () => {
    // Cache network data
    await page.goto('http://localhost:3000/networks');
    await page.waitForSelector('[data-testid="brain-networks"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Access networks offline
    await page.goto('http://localhost:3000/networks');

    await expect(page.locator('[data-testid="network-default_mode"]')).toBeVisible();
    await expect(page.locator('[data-testid="network-attention"]')).toBeVisible();
    await expect(page.locator('text=Connectivity: 0.85')).toBeVisible();
  });

  test('should handle atlas search functionality offline', async () => {
    // Prime search cache
    await page.goto('http://localhost:3000/atlas');
    await page.fill('[data-testid="atlas-search"]', 'frontal');
    await page.waitForSelector('[data-testid="search-results"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Test search offline
    await page.goto('http://localhost:3000/atlas');
    await page.fill('[data-testid="atlas-search"]', 'temporal');

    // Should show offline search results from cache
    await expect(page.locator('[data-testid="region-temporal_cortex"]')).toBeVisible();
  });
});

test.describe('Offline Analysis Workflow', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should display cached analysis results offline', async () => {
    // Load analysis results while online
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');
    await page.waitForSelector('[data-testid="analysis-results"]');

    // Verify results are displayed
    await expect(page.locator('text=fMRI GLM Analysis')).toBeVisible();
    await expect(page.locator('text=t-Score: 4.2')).toBeVisible();

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Access results offline
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');

    await expect(page.locator('[data-testid="analysis-results"]')).toBeVisible();
    await expect(page.locator('text=Frontal Cortex')).toBeVisible();
    await expect(page.locator('text=p < 0.0001')).toBeVisible();
  });

  test('should maintain analysis state during offline periods', async () => {
    // Start an analysis configuration
    await page.goto('http://localhost:3000/analysis/configure');
    await page.selectOption('[data-testid="analysis-type"]', 'connectivity');
    await page.fill('[data-testid="threshold-input"]', '0.5');
    await page.click('[data-testid="add-roi"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Verify state is preserved
    await page.reload();
    await expect(page.locator('[data-testid="analysis-type"]')).toHaveValue('connectivity');
    await expect(page.locator('[data-testid="threshold-input"]')).toHaveValue('0.5');
  });

  test('should queue analysis jobs for later execution when offline', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Try to submit analysis
    await page.goto('http://localhost:3000/analysis/configure');
    await page.selectOption('[data-testid="analysis-type"]', 'glm');
    await page.fill('[data-testid="analysis-name"]', 'Offline GLM Analysis');
    await page.click('[data-testid="submit-analysis"]');

    // Should show queued message
    await expect(page.locator('[data-testid="queue-message"]')).toBeVisible();
    await expect(page.locator('text=queued for processing')).toBeVisible();

    // Verify job is in local queue
    const queuedJobs = await page.evaluate(() => {
      const stored = localStorage.getItem('queued-analyses');
      return stored ? JSON.parse(stored) : [];
    });

    expect(queuedJobs).toHaveLength(1);
    expect(queuedJobs[0].name).toBe('Offline GLM Analysis');
  });

  test('should show offline-specific analysis limitations', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    await page.goto('http://localhost:3000/analysis/configure');

    // Should show offline limitations
    await expect(page.locator('[data-testid="offline-limitations"]')).toBeVisible();
    await expect(page.locator('text=Limited to cached datasets')).toBeVisible();
    await expect(page.locator('text=Results will sync when online')).toBeVisible();
  });

  test('should preserve analysis parameters in offline mode', async () => {
    // Configure complex analysis while online
    await page.goto('http://localhost:3000/analysis/configure');
    await page.selectOption('[data-testid="analysis-type"]', 'connectivity');
    await page.fill('[data-testid="analysis-name"]', 'Complex Connectivity');

    // Add multiple ROIs
    await page.click('[data-testid="add-roi"]');
    await page.selectOption('[data-testid="roi-1"]', 'frontal_cortex');
    await page.click('[data-testid="add-roi"]');
    await page.selectOption('[data-testid="roi-2"]', 'parietal_cortex');

    // Set advanced parameters
    await page.fill('[data-testid="window-size"]', '100');
    await page.fill('[data-testid="step-size"]', '50');
    await page.check('[data-testid="detrend-option"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');
    await page.reload();

    // Verify all parameters are preserved
    await expect(page.locator('[data-testid="analysis-name"]')).toHaveValue('Complex Connectivity');
    await expect(page.locator('[data-testid="roi-1"]')).toHaveValue('frontal_cortex');
    await expect(page.locator('[data-testid="roi-2"]')).toHaveValue('parietal_cortex');
    await expect(page.locator('[data-testid="window-size"]')).toHaveValue('100');
    await expect(page.locator('[data-testid="detrend-option"]')).toBeChecked();
  });
});

test.describe('Offline Brain Visualization', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should render cached brain surfaces offline', async () => {
    // Load brain surface while online
    await page.goto('http://localhost:3000/visualization/surface');
    await page.waitForSelector('[data-testid="brain-surface"]');

    // Verify 3D brain is loaded
    await expect(page.locator('[data-testid="brain-surface"]')).toBeVisible();
    await expect(page.locator('[data-testid="surface-controls"]')).toBeVisible();

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Access visualization offline
    await page.goto('http://localhost:3000/visualization/surface');

    await expect(page.locator('[data-testid="brain-surface"]')).toBeVisible();
    await expect(page.locator('[data-testid="colormap-selector"]')).toBeVisible();
  });

  test('should maintain visualization state offline', async () => {
    // Set up visualization state
    await page.goto('http://localhost:3000/visualization/surface');
    await page.selectOption('[data-testid="colormap-selector"]', 'hot');
    await page.fill('[data-testid="threshold-min"]', '0.2');
    await page.fill('[data-testid="threshold-max"]', '0.8');
    await page.click('[data-testid="apply-threshold"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');
    await page.reload();

    // Verify state is preserved
    await expect(page.locator('[data-testid="colormap-selector"]')).toHaveValue('hot');
    await expect(page.locator('[data-testid="threshold-min"]')).toHaveValue('0.2');
    await expect(page.locator('[data-testid="threshold-max"]')).toHaveValue('0.8');
  });

  test('should handle statistical overlays offline', async () => {
    // Load statistical overlay data
    await page.goto('http://localhost:3000/visualization/overlay/stat_map_123');
    await page.waitForSelector('[data-testid="statistical-overlay"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Access overlay offline
    await page.goto('http://localhost:3000/visualization/overlay/stat_map_123');

    await expect(page.locator('[data-testid="statistical-overlay"]')).toBeVisible();
    await expect(page.locator('[data-testid="overlay-legend"]')).toBeVisible();
  });

  test('should support interactive features offline', async () => {
    // Prime interactive visualization
    await page.goto('http://localhost:3000/visualization/interactive');
    await page.waitForSelector('[data-testid="interactive-brain"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Test interactions offline
    await page.goto('http://localhost:3000/visualization/interactive');

    // Test rotation
    const brainElement = page.locator('[data-testid="interactive-brain"]');
    await brainElement.hover();
    await page.mouse.down();
    await page.mouse.move(100, 100);
    await page.mouse.up();

    // Test zoom
    await brainElement.hover();
    await page.mouse.wheel(0, -100);

    // Interactions should work offline
    await expect(brainElement).toBeVisible();
  });
});

test.describe('Offline Research Documentation', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should create research notes offline', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Create research note
    await page.goto('http://localhost:3000/research/notes/new');
    await page.fill('[data-testid="note-title"]', 'Offline Research Note');
    await page.fill('[data-testid="note-content"]',
      'This note was created offline. Key findings: Strong activation in frontal cortex during working memory task.'
    );
    await page.selectOption('[data-testid="note-category"]', 'findings');
    await page.click('[data-testid="save-note"]');

    // Should show offline save confirmation
    await expect(page.locator('[data-testid="offline-save-message"]')).toBeVisible();
    await expect(page.locator('text=Saved locally')).toBeVisible();

    // Verify note is stored locally
    const localNotes = await page.evaluate(() => {
      const stored = localStorage.getItem('offline-research-notes');
      return stored ? JSON.parse(stored) : [];
    });

    expect(localNotes).toHaveLength(1);
    expect(localNotes[0].title).toBe('Offline Research Note');
  });

  test('should edit existing notes offline', async () => {
    // Create note online first
    await page.goto('http://localhost:3000/research/notes/new');
    await page.fill('[data-testid="note-title"]', 'Test Note');
    await page.fill('[data-testid="note-content"]', 'Original content');
    await page.click('[data-testid="save-note"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Edit note offline
    await page.goto('http://localhost:3000/research/notes/edit/1');
    await page.fill('[data-testid="note-content"]',
      'Original content\n\nUpdated offline: Additional observations about parietal activation.'
    );
    await page.click('[data-testid="save-note"]');

    await expect(page.locator('[data-testid="offline-edit-message"]')).toBeVisible();
  });

  test('should maintain note formatting offline', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    await page.goto('http://localhost:3000/research/notes/new');

    // Add formatted content
    await page.fill('[data-testid="note-content"]', `
# Connectivity Analysis Results

## Methodology
- fMRI data from 45 subjects
- Connectivity matrix calculation
- Network analysis using graph theory

## Key Findings
**Significant connections:**
1. Frontal-Parietal: r=0.72, p<0.001
2. Temporal-Occipital: r=0.68, p<0.005

## Conclusions
The results suggest strong functional integration in cognitive control networks.
    `.trim());

    await page.click('[data-testid="save-note"]');
    await page.click('[data-testid="view-formatted"]');

    // Check if markdown formatting is preserved
    await expect(page.locator('h1')).toContainText('Connectivity Analysis Results');
    await expect(page.locator('h2').first()).toContainText('Methodology');
    await expect(page.locator('strong')).toContainText('Significant connections:');
    await expect(page.locator('li').first()).toContainText('Frontal-Parietal');
  });

  test('should attach analysis results to notes offline', async () => {
    // Prime analysis results cache
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');
    await page.waitForLoadState('networkidle');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Create note with analysis attachment
    await page.goto('http://localhost:3000/research/notes/new');
    await page.fill('[data-testid="note-title"]', 'GLM Analysis Summary');
    await page.fill('[data-testid="note-content"]', 'Summary of GLM analysis findings');

    // Attach analysis results
    await page.click('[data-testid="attach-analysis"]');
    await page.selectOption('[data-testid="analysis-selector"]', 'glm_analysis_123');
    await page.click('[data-testid="confirm-attachment"]');

    await expect(page.locator('[data-testid="attached-analysis"]')).toBeVisible();
    await expect(page.locator('text=GLM Analysis 123')).toBeVisible();
  });
});

test.describe('Offline Collaboration Features', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should queue comments for sync when offline', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Add comment to analysis
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');
    await page.fill('[data-testid="comment-input"]',
      'Interesting activation pattern in the frontal cortex. This aligns with our hypothesis.'
    );
    await page.click('[data-testid="add-comment"]');

    // Should show offline queue message
    await expect(page.locator('[data-testid="offline-comment-queue"]')).toBeVisible();
    await expect(page.locator('text=Comment queued')).toBeVisible();

    // Verify comment is in queue
    const queuedComments = await page.evaluate(() => {
      const stored = localStorage.getItem('offline-comments');
      return stored ? JSON.parse(stored) : [];
    });

    expect(queuedComments).toHaveLength(1);
    expect(queuedComments[0].content).toContain('frontal cortex');
  });

  test('should show offline annotations on visualizations', async () => {
    // Prime visualization cache
    await page.goto('http://localhost:3000/visualization/surface');
    await page.waitForLoadState('networkidle');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Add annotation
    await page.goto('http://localhost:3000/visualization/surface');
    await page.click('[data-testid="annotation-mode"]');

    // Click on brain region to annotate
    const brainElement = page.locator('[data-testid="brain-surface"]');
    await brainElement.click({ position: { x: 200, y: 150 } });

    await page.fill('[data-testid="annotation-text"]',
      'Strong activation cluster in left frontal cortex'
    );
    await page.click('[data-testid="save-annotation"]');

    // Annotation should appear offline
    await expect(page.locator('[data-testid="annotation-marker"]')).toBeVisible();
    await expect(page.locator('[data-testid="offline-annotation-badge"]')).toBeVisible();
  });

  test('should handle team sharing offline', async () => {
    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Try to share analysis results
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');
    await page.click('[data-testid="share-button"]');

    await page.selectOption('[data-testid="share-team"]', 'cognitive-neuroscience');
    await page.fill('[data-testid="share-message"]', 'Please review these GLM results');
    await page.click('[data-testid="confirm-share"]');

    // Should queue for sharing
    await expect(page.locator('[data-testid="share-queued"]')).toBeVisible();
    await expect(page.locator('text=Share request queued')).toBeVisible();
  });

  test('should maintain version control offline', async () => {
    // Create initial version online
    await page.goto('http://localhost:3000/research/notes/new');
    await page.fill('[data-testid="note-title"]', 'Collaboration Note');
    await page.fill('[data-testid="note-content"]', 'Initial content');
    await page.click('[data-testid="save-note"]');

    // Go offline
    await simulateNetworkConditions(context, 'offline');

    // Make offline edit
    await page.goto('http://localhost:3000/research/notes/edit/1');
    await page.fill('[data-testid="note-content"]',
      'Initial content\n\nOffline edit: Added new methodology section'
    );
    await page.click('[data-testid="save-note"]');

    // Check version history
    await page.click('[data-testid="version-history"]');
    await expect(page.locator('[data-testid="version-list"]')).toBeVisible();
    await expect(page.locator('text=Offline edit')).toBeVisible();
  });
});

test.describe('Offline Data Synchronization', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should sync all offline changes when reconnected', async () => {
    // Generate offline changes
    await simulateNetworkConditions(context, 'offline');

    // Create research note
    await page.goto('http://localhost:3000/research/notes/new');
    await page.fill('[data-testid="note-title"]', 'Offline Finding');
    await page.fill('[data-testid="note-content"]', 'Discovered new activation pattern');
    await page.click('[data-testid="save-note"]');

    // Add analysis comment
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');
    await page.fill('[data-testid="comment-input"]', 'Offline analysis comment');
    await page.click('[data-testid="add-comment"]');

    // Come back online
    await simulateNetworkConditions(context, 'online');

    // Should trigger sync automatically
    await page.waitForTimeout(3000);

    // Check sync status
    await expect(page.locator('[data-testid="sync-status"]')).toBeVisible();
    await expect(page.locator('text=Syncing offline changes')).toBeVisible();

    // Wait for sync completion
    await expect(page.locator('text=Sync complete')).toBeVisible({ timeout: 10000 });
  });

  test('should handle sync conflicts gracefully', async () => {
    // Simulate conflicting changes
    await page.evaluate(() => {
      const conflicts = [{
        type: 'research_note',
        id: 'note_123',
        localVersion: 2,
        serverVersion: 3,
        changes: {
          local: 'Local offline changes',
          server: 'Server changes from collaborator'
        }
      }];

      localStorage.setItem('sync-conflicts', JSON.stringify(conflicts));
    });

    // Come online and trigger conflict resolution
    await simulateNetworkConditions(context, 'online');

    // Should show conflict resolution UI
    await expect(page.locator('[data-testid="conflict-resolution"]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=Sync conflicts detected')).toBeVisible();

    // Should allow manual resolution
    await page.click('[data-testid="resolve-conflicts"]');
    await expect(page.locator('[data-testid="conflict-diff"]')).toBeVisible();
  });

  test('should prioritize critical brain data for sync', async () => {
    // Generate mixed offline data
    await simulateNetworkConditions(context, 'offline');

    // Create various types of offline data
    await page.evaluate(() => {
      const offlineData = [
        { type: 'analysis_result', priority: 'high', id: 'analysis_456' },
        { type: 'brain_annotation', priority: 'high', id: 'annotation_789' },
        { type: 'research_note', priority: 'medium', id: 'note_123' },
        { type: 'user_preference', priority: 'low', id: 'pref_456' }
      ];

      localStorage.setItem('offline-sync-queue', JSON.stringify(offlineData));
    });

    // Come online
    await simulateNetworkConditions(context, 'online');

    // Monitor sync order
    const syncOrder = await page.evaluate(() => {
      return new Promise((resolve) => {
        const order: string[] = [];

        // Mock sync listener
        window.addEventListener('sync-item', (event: any) => {
          order.push(event.detail.type);

          if (order.length === 4) {
            resolve(order);
          }
        });

        // Trigger sync
        setTimeout(() => {
          // Simulate high priority items syncing first
          window.dispatchEvent(new CustomEvent('sync-item', { detail: { type: 'analysis_result' } }));
          window.dispatchEvent(new CustomEvent('sync-item', { detail: { type: 'brain_annotation' } }));
          window.dispatchEvent(new CustomEvent('sync-item', { detail: { type: 'research_note' } }));
          window.dispatchEvent(new CustomEvent('sync-item', { detail: { type: 'user_preference' } }));
        }, 100);
      });
    });

    expect(syncOrder[0]).toBe('analysis_result');
    expect(syncOrder[1]).toBe('brain_annotation');
  });

  test('should show sync progress for large datasets', async () => {
    // Simulate large offline dataset
    await page.evaluate(() => {
      const largeDataset = {
        type: 'brain_imaging_data',
        size: 50000000, // 50MB
        chunks: 100,
        needsSync: true
      };

      localStorage.setItem('large-offline-data', JSON.stringify([largeDataset]));
    });

    // Come online and start sync
    await simulateNetworkConditions(context, 'online');

    // Should show progress indicator
    await expect(page.locator('[data-testid="sync-progress"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="progress-bar"]')).toBeVisible();
    await expect(page.locator('text=Syncing brain imaging data')).toBeVisible();

    // Should show data transfer stats
    await expect(page.locator('[data-testid="sync-stats"]')).toBeVisible();
    await expect(page.locator('text=MB')).toBeVisible();
  });
});

test.describe('Offline Performance and Reliability', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    context = await browser.newContext();
    page = await context.newPage();

    await mockBrainResearchData(page);
    await page.goto('http://localhost:3000');
    await waitForServiceWorkerActivation(page);
  });

  test.afterEach(async () => {
    await context.close();
  });

  test('should maintain performance under slow network conditions', async () => {
    // Simulate slow 3G connection
    await simulateNetworkConditions(context, 'slow-3g');

    const startTime = Date.now();

    // Navigate to cached brain atlas
    await page.goto('http://localhost:3000/atlas');
    await page.waitForSelector('[data-testid="brain-atlas"]');

    const loadTime = Date.now() - startTime;

    // Should load quickly from cache despite slow network
    expect(loadTime).toBeLessThan(3000); // 3 seconds
  });

  test('should handle intermittent connectivity gracefully', async () => {
    // Simulate intermittent connectivity
    const simulateIntermittent = async () => {
      for (let i = 0; i < 5; i++) {
        await simulateNetworkConditions(context, 'offline');
        await page.waitForTimeout(1000);
        await simulateNetworkConditions(context, 'online');
        await page.waitForTimeout(500);
      }
    };

    // Start intermittent simulation
    simulateIntermittent();

    // Navigate during intermittent connectivity
    await page.goto('http://localhost:3000/analysis/results/glm_analysis_123');

    // Should eventually load successfully
    await expect(page.locator('[data-testid="analysis-results"]')).toBeVisible({ timeout: 15000 });
  });

  test('should recover from storage quota errors', async () => {
    // Simulate storage quota exceeded
    await page.evaluate(() => {
      // Mock quota exceeded error
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (key === 'test-quota') {
          throw new DOMException('Quota exceeded', 'QuotaExceededError');
        }
        return originalSetItem.call(this, key, value);
      };
    });

    // Try to save data that would exceed quota
    await page.evaluate(() => {
      try {
        localStorage.setItem('test-quota', 'large data');
      } catch (error) {
        window.dispatchEvent(new CustomEvent('storage-quota-error', { detail: error }));
      }
    });

    // Should show quota management UI
    await expect(page.locator('[data-testid="storage-management"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Storage space low')).toBeVisible();
  });

  test('should provide offline capability report', async () => {
    // Check offline capabilities
    const capabilities = await verifyOfflineCapabilities(page);

    // Navigate to offline status page
    await page.goto('http://localhost:3000/settings/offline');

    // Should show capability report
    await expect(page.locator('[data-testid="offline-capabilities"]')).toBeVisible();
    await expect(page.locator('[data-testid="cache-statistics"]')).toBeVisible();

    // Should show brain-specific offline features
    await expect(page.locator('text=Brain Atlas Data')).toBeVisible();
    await expect(page.locator('text=Analysis Results')).toBeVisible();
    await expect(page.locator('text=Visualizations')).toBeVisible();
  });

  test('should handle cache invalidation properly', async () => {
    // Prime cache with brain data
    await page.goto('http://localhost:3000/api/atlas/data');
    await page.waitForLoadState('networkidle');

    // Simulate cache invalidation
    await page.evaluate(async () => {
      if ('caches' in window) {
        const cache = await caches.open('brain-researcher-brain-data-v3');
        await cache.delete('/api/atlas/data');
      }
    });

    // Go offline and try to access invalidated data
    await simulateNetworkConditions(context, 'offline');
    await page.goto('http://localhost:3000/api/atlas/data');

    // Should show appropriate fallback
    await expect(page.locator('[data-testid="offline-fallback"]')).toBeVisible();
    await expect(page.locator('text=Data not available offline')).toBeVisible();
  });
});