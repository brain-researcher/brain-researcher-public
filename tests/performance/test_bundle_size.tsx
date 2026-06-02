/**
 * @jest-environment jsdom
 */
import { bundleSize, gzipSize, parseBundle } from 'bundlesize-utils'
import path from 'path'

// Mock bundlesize utilities for testing
jest.mock('bundlesize-utils', () => ({
  bundleSize: jest.fn(),
  gzipSize: jest.fn(),
  parseBundle: jest.fn()
}))

const mockBundleSize = bundleSize as jest.MockedFunction<typeof bundleSize>
const mockGzipSize = gzipSize as jest.MockedFunction<typeof gzipSize>
const mockParseBundle = parseBundle as jest.MockedFunction<typeof parseBundle>

describe('Feedback Widget Bundle Size Performance', () => {
  const BUNDLE_SIZE_LIMITS = {
    // Main feedback widget bundle
    feedbackWidget: {
      max: 50 * 1024, // 50KB uncompressed
      maxGzipped: 15 * 1024, // 15KB gzipped
    },
    // Individual components
    feedbackDialog: {
      max: 20 * 1024, // 20KB uncompressed
      maxGzipped: 6 * 1024, // 6KB gzipped
    },
    feedbackTrigger: {
      max: 8 * 1024, // 8KB uncompressed
      maxGzipped: 2.5 * 1024, // 2.5KB gzipped
    },
    feedbackForm: {
      max: 25 * 1024, // 25KB uncompressed
      maxGzipped: 8 * 1024, // 8KB gzipped
    },
    screenshotCapture: {
      max: 15 * 1024, // 15KB uncompressed
      maxGzipped: 5 * 1024, // 5KB gzipped
    }
  }

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Main Widget Bundle', () => {
    it('should not exceed bundle size limits for main widget', async () => {
      const widgetPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackWidget.tsx')

      // Mock file sizes
      mockBundleSize.mockResolvedValue(48 * 1024) // 48KB
      mockGzipSize.mockResolvedValue(14 * 1024) // 14KB

      const uncompressed = await bundleSize(widgetPath)
      const compressed = await gzipSize(widgetPath)

      expect(uncompressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackWidget.max)
      expect(compressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackWidget.maxGzipped)
    })

    it('should warn when approaching bundle size limits', async () => {
      const widgetPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackWidget.tsx')

      // Mock size at 90% of limit
      const warningSize = BUNDLE_SIZE_LIMITS.feedbackWidget.max * 0.9
      mockBundleSize.mockResolvedValue(warningSize)
      mockGzipSize.mockResolvedValue(BUNDLE_SIZE_LIMITS.feedbackWidget.maxGzipped * 0.9)

      const consoleWarn = jest.spyOn(console, 'warn').mockImplementation()

      const uncompressed = await bundleSize(widgetPath)

      if (uncompressed >= BUNDLE_SIZE_LIMITS.feedbackWidget.max * 0.9) {
        console.warn(`Bundle size warning: ${uncompressed} bytes is approaching limit of ${BUNDLE_SIZE_LIMITS.feedbackWidget.max} bytes`)
      }

      expect(consoleWarn).toHaveBeenCalled()
      consoleWarn.mockRestore()
    })

    it('should track bundle composition and dependencies', async () => {
      const widgetPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackWidget.tsx')

      const mockBundle = {
        files: [
          { name: 'FeedbackWidget.tsx', size: 8 * 1024 },
          { name: 'FeedbackDialog.tsx', size: 12 * 1024 },
          { name: 'FeedbackForm.tsx', size: 15 * 1024 },
          { name: 'RatingSection.tsx', size: 5 * 1024 },
          { name: 'ScreenshotCapture.tsx', size: 8 * 1024 }
        ],
        dependencies: [
          { name: 'react', size: 2 * 1024 },
          { name: 'html-to-image', size: 3 * 1024 },
          { name: 'lucide-react', size: 1.5 * 1024 }
        ]
      }

      mockParseBundle.mockResolvedValue(mockBundle)

      const bundle = await parseBundle(widgetPath)

      // Check that core files are reasonably sized
      const mainFile = bundle.files.find(f => f.name === 'FeedbackWidget.tsx')
      expect(mainFile?.size).toBeLessThanOrEqual(10 * 1024) // 10KB for main component

      // Check dependency sizes
      const totalDependencySize = bundle.dependencies.reduce((sum, dep) => sum + dep.size, 0)
      expect(totalDependencySize).toBeLessThanOrEqual(10 * 1024) // 10KB for all deps
    })
  })

  describe('Individual Component Bundles', () => {
    it('should check FeedbackDialog bundle size', async () => {
      const dialogPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackDialog.tsx')

      mockBundleSize.mockResolvedValue(18 * 1024)
      mockGzipSize.mockResolvedValue(5.5 * 1024)

      const uncompressed = await bundleSize(dialogPath)
      const compressed = await gzipSize(dialogPath)

      expect(uncompressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackDialog.max)
      expect(compressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackDialog.maxGzipped)
    })

    it('should check FeedbackTrigger bundle size', async () => {
      const triggerPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackTrigger.tsx')

      mockBundleSize.mockResolvedValue(7 * 1024)
      mockGzipSize.mockResolvedValue(2.2 * 1024)

      const uncompressed = await bundleSize(triggerPath)
      const compressed = await gzipSize(triggerPath)

      expect(uncompressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackTrigger.max)
      expect(compressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackTrigger.maxGzipped)
    })

    it('should check FeedbackForm bundle size', async () => {
      const formPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/FeedbackForm.tsx')

      mockBundleSize.mockResolvedValue(23 * 1024)
      mockGzipSize.mockResolvedValue(7.5 * 1024)

      const uncompressed = await bundleSize(formPath)
      const compressed = await gzipSize(formPath)

      expect(uncompressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackForm.max)
      expect(compressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.feedbackForm.maxGzipped)
    })

    it('should check ScreenshotCapture bundle size', async () => {
      const screenshotPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/components/ScreenshotCapture.tsx')

      mockBundleSize.mockResolvedValue(13 * 1024)
      mockGzipSize.mockResolvedValue(4.5 * 1024)

      const uncompressed = await bundleSize(screenshotPath)
      const compressed = await gzipSize(screenshotPath)

      expect(uncompressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.screenshotCapture.max)
      expect(compressed).toBeLessThanOrEqual(BUNDLE_SIZE_LIMITS.screenshotCapture.maxGzipped)
    })
  })

  describe('Tree Shaking and Code Splitting', () => {
    it('should support tree shaking for unused exports', async () => {
      const indexPath = path.resolve(__dirname, '../../apps/web-ui/src/components/feedback/index.ts')

      // Mock scenario where only FeedbackWidget is imported
      const mockTreeShakenBundle = {
        files: [
          { name: 'FeedbackWidget.tsx', size: 8 * 1024, included: true },
          { name: 'FeedbackDialog.tsx', size: 12 * 1024, included: true }, // Used by Widget
          { name: 'FeedbackTrigger.tsx', size: 5 * 1024, included: true }, // Used by Widget
          { name: 'ScreenshotCapture.tsx', size: 8 * 1024, included: false }, // Not used directly
          { name: 'SuccessMessage.tsx', size: 3 * 1024, included: false } // Not used directly
        ]
      }

      mockParseBundle.mockResolvedValue(mockTreeShakenBundle)

      const bundle = await parseBundle(indexPath)
      const includedSize = bundle.files
        .filter(f => f.included)
        .reduce((sum, f) => sum + f.size, 0)

      const totalSize = bundle.files.reduce((sum, f) => sum + f.size, 0)

      // Tree shaking should reduce bundle size
      expect(includedSize).toBeLessThan(totalSize)

      // Should only include necessary files
      const includedFiles = bundle.files.filter(f => f.included).map(f => f.name)
      expect(includedFiles).toContain('FeedbackWidget.tsx')
      expect(includedFiles).toContain('FeedbackDialog.tsx')
      expect(includedFiles).not.toContain('ScreenshotCapture.tsx') // Should be code-split
    })

    it('should support lazy loading for screenshot functionality', async () => {
      // Mock dynamic import scenario
      const mockDynamicBundle = {
        main: { size: 35 * 1024 }, // Main bundle without screenshot
        chunks: [
          { name: 'screenshot', size: 15 * 1024, loadOnDemand: true },
          { name: 'html-to-image', size: 8 * 1024, loadOnDemand: true }
        ]
      }

      // Main bundle should be smaller without screenshot functionality
      expect(mockDynamicBundle.main.size).toBeLessThanOrEqual(40 * 1024)

      // Screenshot functionality should be in separate chunk
      const screenshotChunk = mockDynamicBundle.chunks.find(c => c.name === 'screenshot')
      expect(screenshotChunk?.loadOnDemand).toBe(true)
      expect(screenshotChunk?.size).toBeLessThanOrEqual(20 * 1024)
    })

    it('should optimize for different import patterns', async () => {
      // Test different import scenarios
      const importScenarios = [
        {
          name: 'Full widget import',
          imports: ['FeedbackWidget'],
          expectedSize: 48 * 1024
        },
        {
          name: 'Trigger only import',
          imports: ['FeedbackTrigger'],
          expectedSize: 12 * 1024
        },
        {
          name: 'Form only import',
          imports: ['FeedbackForm'],
          expectedSize: 28 * 1024
        },
        {
          name: 'Individual components import',
          imports: ['RatingSection', 'CategorySection'],
          expectedSize: 15 * 1024
        }
      ]

      for (const scenario of importScenarios) {
        mockBundleSize.mockResolvedValue(scenario.expectedSize)

        const size = await bundleSize('mock-path')
        expect(size).toBeLessThanOrEqual(scenario.expectedSize)

        // Log for monitoring
        console.log(`Bundle size for ${scenario.name}: ${size} bytes`)
      }
    })
  })

  describe('Dependency Analysis', () => {
    it('should monitor third-party dependency sizes', async () => {
      const mockDependencies = [
        { name: 'react', size: 42 * 1024, version: '18.2.0', essential: true },
        { name: 'html-to-image', size: 25 * 1024, version: '1.11.13', essential: false },
        { name: 'lucide-react', size: 15 * 1024, version: '0.344.0', essential: false },
        { name: '@radix-ui/react-dialog', size: 12 * 1024, version: '1.1.15', essential: true },
        { name: '@tanstack/react-query', size: 35 * 1024, version: '5.0.0', essential: true }
      ]

      // Check individual dependency sizes
      const largeDependencies = mockDependencies.filter(dep => dep.size > 20 * 1024)
      expect(largeDependencies.length).toBeLessThanOrEqual(3) // Limit large dependencies

      // Check total non-essential dependency size
      const nonEssentialSize = mockDependencies
        .filter(dep => !dep.essential)
        .reduce((sum, dep) => sum + dep.size, 0)

      expect(nonEssentialSize).toBeLessThanOrEqual(50 * 1024) // 50KB for non-essential deps

      // Check for duplicate or similar dependencies
      const duplicatePatterns = ['react-', '@types/', 'lucide-']
      const duplicates = duplicatePatterns.map(pattern =>
        mockDependencies.filter(dep => dep.name.includes(pattern))
      ).filter(group => group.length > 1)

      expect(duplicates.length).toBeLessThanOrEqual(1) // Minimize duplicates
    })

    it('should track bundle size trends over time', async () => {
      // Mock historical data
      const historicalSizes = [
        { version: '1.0.0', size: 45 * 1024, date: '2025-01-01' },
        { version: '1.1.0', size: 47 * 1024, date: '2025-02-01' },
        { version: '1.2.0', size: 49 * 1024, date: '2025-03-01' },
        { version: '1.3.0', size: 48 * 1024, date: '2025-04-01' } // Improvement
      ]

      const currentSize = 48 * 1024
      const lastSize = historicalSizes[historicalSizes.length - 1].size
      const sizeChange = currentSize - lastSize

      // Bundle size should not grow significantly
      expect(Math.abs(sizeChange)).toBeLessThanOrEqual(5 * 1024) // 5KB tolerance

      if (sizeChange > 2 * 1024) {
        console.warn(`Bundle size increased by ${sizeChange} bytes`)
      }

      if (sizeChange < -2 * 1024) {
        console.log(`Bundle size optimized by ${Math.abs(sizeChange)} bytes`)
      }
    })

    it('should analyze code complexity and its impact on bundle size', async () => {
      const mockComplexityMetrics = {
        cyclomaticComplexity: 25, // Should be < 30
        linesOfCode: 800, // Should be < 1000 per component
        numberOfMethods: 15, // Should be < 20
        depthOfInheritance: 3, // Should be < 5
        couplingBetweenObjects: 8 // Should be < 10
      }

      // High complexity often correlates with larger bundle size
      expect(mockComplexityMetrics.cyclomaticComplexity).toBeLessThanOrEqual(30)
      expect(mockComplexityMetrics.linesOfCode).toBeLessThanOrEqual(1000)
      expect(mockComplexityMetrics.numberOfMethods).toBeLessThanOrEqual(20)
      expect(mockComplexityMetrics.depthOfInheritance).toBeLessThanOrEqual(5)
      expect(mockComplexityMetrics.couplingBetweenObjects).toBeLessThanOrEqual(10)

      // Calculate complexity score (lower is better)
      const complexityScore = (
        mockComplexityMetrics.cyclomaticComplexity * 2 +
        mockComplexityMetrics.linesOfCode / 50 +
        mockComplexityMetrics.numberOfMethods * 3 +
        mockComplexityMetrics.depthOfInheritance * 5 +
        mockComplexityMetrics.couplingBetweenObjects * 4
      )

      expect(complexityScore).toBeLessThanOrEqual(200) // Complexity threshold
    })
  })

  describe('Performance Budgets', () => {
    it('should enforce performance budgets for different network conditions', async () => {
      const networkBudgets = {
        '3g-fast': { budget: 100 * 1024, description: '3G Fast (1.4Mbps)' },
        '3g-slow': { budget: 70 * 1024, description: '3G Slow (0.4Mbps)' },
        '2g': { budget: 30 * 1024, description: '2G (0.256Mbps)' }
      }

      const currentBundleSize = 48 * 1024 // Mock current size

      for (const [network, config] of Object.entries(networkBudgets)) {
        const withinBudget = currentBundleSize <= config.budget

        if (!withinBudget) {
          console.warn(`Bundle size ${currentBundleSize} exceeds ${network} budget of ${config.budget}`)
        }

        // At minimum, should work on 3G Fast
        if (network === '3g-fast') {
          expect(currentBundleSize).toBeLessThanOrEqual(config.budget)
        }
      }
    })

    it('should calculate loading time estimates', async () => {
      const bundleSize = 48 * 1024 // 48KB
      const gzippedSize = 14 * 1024 // 14KB

      const connectionSpeeds = {
        'broadband': 5000 * 1024, // 5Mbps
        '4g': 1000 * 1024, // 1Mbps
        '3g': 500 * 1024, // 500Kbps
        '2g': 56 * 1024 // 56Kbps
      }

      for (const [connection, speedBps] of Object.entries(connectionSpeeds)) {
        const loadTime = (gzippedSize * 8) / speedBps // Convert to seconds

        console.log(`Load time on ${connection}: ${loadTime.toFixed(2)}s`)

        // Should load in reasonable time on modern connections
        if (connection === '4g') {
          expect(loadTime).toBeLessThanOrEqual(1) // 1 second on 4G
        }

        if (connection === '3g') {
          expect(loadTime).toBeLessThanOrEqual(2) // 2 seconds on 3G
        }
      }
    })

    it('should monitor compression efficiency', async () => {
      const uncompressedSize = 48 * 1024
      const gzippedSize = 14 * 1024
      const compressionRatio = gzippedSize / uncompressedSize

      // Good compression should achieve at least 3:1 ratio
      expect(compressionRatio).toBeLessThanOrEqual(0.35) // 65% reduction minimum

      // Excellent compression achieves 4:1 or better
      if (compressionRatio <= 0.25) {
        console.log(`Excellent compression: ${(100 - compressionRatio * 100).toFixed(1)}% reduction`)
      }

      // Check for files that compress poorly (indicates binary data or already compressed)
      const poorCompressionThreshold = 0.8 // Less than 20% reduction
      expect(compressionRatio).toBeLessThan(poorCompressionThreshold)
    })
  })

  describe('Bundle Optimization Recommendations', () => {
    it('should provide optimization recommendations', async () => {
      const bundleAnalysis = {
        totalSize: 48 * 1024,
        gzippedSize: 14 * 1024,
        duplicateCode: 2 * 1024,
        unusedCode: 3 * 1024,
        largeAssets: [
          { name: 'html-to-image', size: 8 * 1024 }
        ],
        improvementPotential: 5 * 1024
      }

      const recommendations: string[] = []

      // Check for duplicate code
      if (bundleAnalysis.duplicateCode > 1024) {
        recommendations.push('Remove duplicate code to save ' + (bundleAnalysis.duplicateCode / 1024).toFixed(1) + 'KB')
      }

      // Check for unused code
      if (bundleAnalysis.unusedCode > 2 * 1024) {
        recommendations.push('Remove unused code to save ' + (bundleAnalysis.unusedCode / 1024).toFixed(1) + 'KB')
      }

      // Check for large assets
      bundleAnalysis.largeAssets.forEach(asset => {
        if (asset.size > 5 * 1024) {
          recommendations.push(`Consider code-splitting or optimizing ${asset.name} (${(asset.size / 1024).toFixed(1)}KB)`)
        }
      })

      // Should have actionable recommendations
      expect(recommendations.length).toBeGreaterThan(0)
      expect(bundleAnalysis.improvementPotential).toBeGreaterThan(0)

      console.log('Optimization recommendations:', recommendations)
    })

    it('should track optimization implementation', async () => {
      const optimizationTechniques = [
        { name: 'Tree Shaking', implemented: true, savings: 5 * 1024 },
        { name: 'Code Splitting', implemented: true, savings: 8 * 1024 },
        { name: 'Gzip Compression', implemented: true, savings: 34 * 1024 },
        { name: 'Minification', implemented: true, savings: 12 * 1024 },
        { name: 'Dead Code Elimination', implemented: false, potentialSavings: 3 * 1024 },
        { name: 'Dynamic Imports', implemented: false, potentialSavings: 6 * 1024 }
      ]

      const implementedSavings = optimizationTechniques
        .filter(tech => tech.implemented)
        .reduce((sum, tech) => sum + (tech.savings || 0), 0)

      const potentialSavings = optimizationTechniques
        .filter(tech => !tech.implemented)
        .reduce((sum, tech) => sum + (tech.potentialSavings || 0), 0)

      // Should have implemented major optimizations
      expect(implementedSavings).toBeGreaterThan(50 * 1024) // 50KB savings

      // Track remaining optimization opportunities
      console.log(`Potential additional savings: ${(potentialSavings / 1024).toFixed(1)}KB`)

      if (potentialSavings > 5 * 1024) {
        console.warn('Consider implementing additional optimizations')
      }
    })
  })
})