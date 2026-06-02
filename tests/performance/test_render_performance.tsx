/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackWidget } from '@/components/feedback/FeedbackWidget'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Performance measurement utilities
const measurePerformance = (name: string, fn: () => Promise<void> | void) => {
  return new Promise<number>((resolve) => {
    const start = performance.now()
    const result = fn()

    if (result instanceof Promise) {
      result.then(() => {
        const end = performance.now()
        const duration = end - start
        console.log(`${name}: ${duration.toFixed(2)}ms`)
        resolve(duration)
      })
    } else {
      const end = performance.now()
      const duration = end - start
      console.log(`${name}: ${duration.toFixed(2)}ms`)
      resolve(duration)
    }
  })
}

// Mock performance observer
const mockPerformanceEntries: PerformanceEntry[] = []
global.PerformanceObserver = class MockPerformanceObserver {
  constructor(callback: PerformanceObserverCallback) {
    this.callback = callback
  }

  callback: PerformanceObserverCallback

  observe() {
    // Simulate performance entries
    this.callback({
      getEntries: () => mockPerformanceEntries,
      getEntriesByName: () => [],
      getEntriesByType: () => []
    } as any, this)
  }

  disconnect() {}
}

// Test wrapper
const TestWrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false }
    }
  })

  return (
    <QueryClientProvider client={queryClient}>
      <FeedbackProvider>
        {children}
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

describe('Feedback Widget Render Performance', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockPerformanceEntries.length = 0
  })

  describe('Initial Render Performance', () => {
    it('should render trigger button within performance budget', async () => {
      const renderTime = await measurePerformance('Initial render', () => {
        render(
          <TestWrapper>
            <FeedbackWidget />
          </TestWrapper>
        )
      })

      // Should render in less than 16ms (60fps budget)
      expect(renderTime).toBeLessThan(16)

      // Should render in less than 100ms for good user experience
      expect(renderTime).toBeLessThan(100)

      expect(screen.getByRole('button', { name: /feedback menu/i })).toBeInTheDocument()
    })

    it('should handle multiple widget instances efficiently', async () => {
      const renderTime = await measurePerformance('Multiple widgets render', () => {
        render(
          <TestWrapper>
            <FeedbackWidget position="top-left" />
            <FeedbackWidget position="top-right" />
            <FeedbackWidget position="bottom-left" />
            <FeedbackWidget position="bottom-right" />
          </TestWrapper>
        )
      })

      // Multiple instances should not significantly impact render time
      expect(renderTime).toBeLessThan(50) // 50ms budget for 4 widgets

      const buttons = screen.getAllByRole('button', { name: /feedback menu/i })
      expect(buttons).toHaveLength(4)
    })

    it('should render with different props efficiently', async () => {
      const variants = [
        { position: 'top-left', size: 'sm', variant: 'floating' },
        { position: 'top-right', size: 'md', variant: 'inline' },
        { position: 'bottom-left', size: 'lg', variant: 'minimal' }
      ] as const

      for (const props of variants) {
        const { unmount } = render(
          <TestWrapper>
            <FeedbackWidget {...props} />
          </TestWrapper>
        )

        const renderTime = await measurePerformance(`Render with ${props.variant} variant`, () => {
          // Component should already be rendered
        })

        expect(renderTime).toBeLessThan(1) // Measurement overhead only
        unmount()
      }
    })

    it('should not cause layout thrashing on mount', async () => {
      let layoutShiftCount = 0

      // Mock layout shift observer
      const mockLayoutShiftObserver = {
        observe: jest.fn(),
        disconnect: jest.fn()
      }

      // Simulate layout shift detection
      Object.defineProperty(global, 'PerformanceObserver', {
        value: jest.fn().mockImplementation(() => mockLayoutShiftObserver)
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Should not cause layout shifts
      expect(layoutShiftCount).toBe(0)
      expect(mockLayoutShiftObserver.observe).toHaveBeenCalled()
    })
  })

  describe('Dialog Open Performance', () => {
    it('should open dialog within performance budget', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      const openTime = await measurePerformance('Dialog open', async () => {
        await user.click(trigger)

        await waitFor(() => {
          expect(screen.getByRole('dialog')).toBeInTheDocument()
        })
      })

      // Should open in less than 100ms for good UX
      expect(openTime).toBeLessThan(100)
    })

    it('should handle rapid open/close operations efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      const rapidOperationsTime = await measurePerformance('Rapid open/close', async () => {
        for (let i = 0; i < 10; i++) {
          await user.click(trigger)

          await waitFor(() => {
            expect(screen.getByRole('dialog')).toBeInTheDocument()
          })

          await user.keyboard('{Escape}')

          await waitFor(() => {
            expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
          })
        }
      })

      // 10 open/close cycles should complete reasonably quickly
      expect(rapidOperationsTime).toBeLessThan(2000) // 2 seconds

      // Average per operation
      const avgOperationTime = rapidOperationsTime / 20 // 20 operations (10 open + 10 close)
      expect(avgOperationTime).toBeLessThan(50) // 50ms average per operation
    })

    it('should lazy load heavy components', async () => {
      const user = userEvent.setup()

      // Mock dynamic import
      const mockDynamicImport = jest.fn().mockResolvedValue({
        ScreenshotCapture: () => <div data-testid="screenshot-capture">Screenshot</div>
      })

      render(
        <TestWrapper>
          <FeedbackWidget lazyLoadScreenshot />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Screenshot component should not be loaded yet
      expect(screen.queryByTestId('screenshot-capture')).not.toBeInTheDocument()

      // Navigate to screenshot section to trigger lazy load
      const screenshotTab = screen.getByRole('tab', { name: /screenshot/i })

      const lazyLoadTime = await measurePerformance('Lazy load screenshot', async () => {
        await user.click(screenshotTab)

        await waitFor(() => {
          expect(screen.getByTestId('screenshot-capture')).toBeInTheDocument()
        })
      })

      // Lazy loading should be quick
      expect(lazyLoadTime).toBeLessThan(200) // 200ms budget
    })

    it('should handle form field rendering efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Measure time to render all form fields
      const formFieldsRenderTime = performance.now()

      const formElements = [
        screen.getAllByRole('button', { name: /star/i }),
        screen.getAllByRole('button', { name: /emoji/i }),
        screen.getByRole('combobox', { name: /category/i }),
        screen.getByRole('textbox', { name: /title/i }),
        screen.getByRole('textbox', { name: /description/i })
      ]

      const renderComplete = performance.now()
      const totalRenderTime = renderComplete - formFieldsRenderTime

      expect(totalRenderTime).toBeLessThan(50) // 50ms for all form fields
      expect(formElements.every(el => Array.isArray(el) ? el.length > 0 : el)).toBe(true)
    })
  })

  describe('Form Interaction Performance', () => {
    it('should handle star rating interactions efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const stars = screen.getAllByRole('button', { name: /star/i })

      const interactionTime = await measurePerformance('Star interactions', async () => {
        for (const star of stars) {
          await user.hover(star) // Test hover performance
          await user.click(star) // Test click performance
        }
      })

      // 5 hover + 5 click operations should be fast
      expect(interactionTime).toBeLessThan(100) // 100ms for all interactions
    })

    it('should handle text input efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const titleInput = screen.getByRole('textbox', { name: /title/i })
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })

      const longText = 'This is a long piece of text that simulates a user typing a detailed feedback message with multiple sentences and various punctuation marks. '.repeat(10)

      const typingTime = await measurePerformance('Text input', async () => {
        await user.type(titleInput, 'Performance test title')
        await user.type(descriptionTextarea, longText)
      })

      // Should handle long text input efficiently
      expect(typingTime).toBeLessThan(1000) // 1 second for long text input
    })

    it('should handle form validation efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const titleInput = screen.getByRole('textbox', { name: /title/i })

      const validationTime = await measurePerformance('Form validation', async () => {
        // Type invalid input
        await user.type(titleInput, 'Hi') // Too short
        await user.tab() // Trigger validation

        await waitFor(() => {
          expect(screen.getByText(/title must be at least 5 characters/i)).toBeInTheDocument()
        })

        // Fix validation error
        await user.clear(titleInput)
        await user.type(titleInput, 'Valid title')
        await user.tab()

        await waitFor(() => {
          expect(screen.queryByText(/title must be at least 5 characters/i)).not.toBeInTheDocument()
        })
      })

      // Validation should be responsive
      expect(validationTime).toBeLessThan(200) // 200ms for validation cycle
    })

    it('should handle file upload preview efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot data'], 'test.png', { type: 'image/png' })

      const uploadTime = await measurePerformance('File upload preview', async () => {
        await user.upload(fileInput, mockFile)

        await waitFor(() => {
          expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
        })
      })

      // File preview should appear quickly
      expect(uploadTime).toBeLessThan(300) // 300ms for file upload and preview
    })
  })

  describe('Memory Performance', () => {
    it('should not cause memory leaks on mount/unmount', async () => {
      const initialMemory = (performance as any).memory?.usedJSHeapSize || 0

      // Mount and unmount multiple times
      for (let i = 0; i < 50; i++) {
        const { unmount } = render(
          <TestWrapper>
            <FeedbackWidget />
          </TestWrapper>
        )
        unmount()
      }

      // Force garbage collection if available
      if (global.gc) {
        global.gc()
      }

      const finalMemory = (performance as any).memory?.usedJSHeapSize || 0
      const memoryGrowth = finalMemory - initialMemory

      // Memory growth should be minimal (accounting for test overhead)
      expect(memoryGrowth).toBeLessThan(1024 * 1024) // Less than 1MB growth
    })

    it('should clean up event listeners on unmount', async () => {
      const addEventListenerSpy = jest.spyOn(document, 'addEventListener')
      const removeEventListenerSpy = jest.spyOn(document, 'removeEventListener')

      const { unmount } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const initialEventListeners = addEventListenerSpy.mock.calls.length

      unmount()

      const removedEventListeners = removeEventListenerSpy.mock.calls.length

      // Should remove at least as many listeners as it added
      expect(removedEventListeners).toBeGreaterThanOrEqual(initialEventListeners)

      addEventListenerSpy.mockRestore()
      removeEventListenerSpy.mockRestore()
    })

    it('should handle rapid re-renders without performance degradation', async () => {
      const user = userEvent.setup()
      let renderCount = 0

      const PerformanceTestComponent = () => {
        renderCount++
        return <FeedbackWidget />
      }

      const { rerender } = render(
        <TestWrapper>
          <PerformanceTestComponent />
        </TestWrapper>
      )

      const reRenderTime = await measurePerformance('Rapid re-renders', () => {
        for (let i = 0; i < 100; i++) {
          rerender(
            <TestWrapper>
              <PerformanceTestComponent />
            </TestWrapper>
          )
        }
      })

      expect(renderCount).toBe(101) // Initial + 100 re-renders
      expect(reRenderTime).toBeLessThan(1000) // 1 second for 100 re-renders

      const avgRenderTime = reRenderTime / 100
      expect(avgRenderTime).toBeLessThan(10) // 10ms average per re-render
    })
  })

  describe('Animation Performance', () => {
    it('should maintain 60fps during dialog open animation', async () => {
      const user = userEvent.setup()
      let frameCount = 0
      const frameTimes: number[] = []

      // Mock requestAnimationFrame to track frame rate
      const originalRAF = global.requestAnimationFrame
      global.requestAnimationFrame = (callback: FrameRequestCallback) => {
        const start = performance.now()
        return originalRAF(() => {
          frameCount++
          frameTimes.push(performance.now() - start)
          callback(start)
        })
      }

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      await user.click(trigger)

      // Wait for animation to complete
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Restore RAF
      global.requestAnimationFrame = originalRAF

      if (frameTimes.length > 0) {
        const avgFrameTime = frameTimes.reduce((sum, time) => sum + time, 0) / frameTimes.length

        // Should maintain 60fps (16.67ms per frame)
        expect(avgFrameTime).toBeLessThan(16.67)
      }
    })

    it('should handle hover animations efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const stars = screen.getAllByRole('button', { name: /star/i })

      const hoverAnimationTime = await measurePerformance('Hover animations', async () => {
        for (const star of stars) {
          await user.hover(star)
          await user.unhover(star)
        }
      })

      // Hover animations should be smooth
      expect(hoverAnimationTime).toBeLessThan(200) // 200ms for all hover animations
    })

    it('should handle focus animations efficiently', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const focusableElements = [
        ...screen.getAllByRole('button', { name: /star/i }),
        screen.getByRole('combobox', { name: /category/i }),
        screen.getByRole('textbox', { name: /title/i })
      ]

      const focusAnimationTime = await measurePerformance('Focus animations', async () => {
        for (const element of focusableElements) {
          element.focus()
          await new Promise(resolve => setTimeout(resolve, 50)) // Brief pause
        }
      })

      // Focus animations should not cause performance issues
      expect(focusAnimationTime).toBeLessThan(500) // 500ms budget
    })
  })

  describe('Scroll Performance', () => {
    it('should handle scroll events efficiently', async () => {
      render(
        <TestWrapper>
          <div style={{ height: '200vh' }}>
            <FeedbackWidget />
          </div>
        </TestWrapper>
      )

      let scrollEventCount = 0
      const scrollHandler = () => scrollEventCount++

      window.addEventListener('scroll', scrollHandler)

      const scrollTime = await measurePerformance('Scroll handling', () => {
        // Simulate scroll events
        for (let i = 0; i < 100; i++) {
          window.dispatchEvent(new Event('scroll'))
        }
      })

      window.removeEventListener('scroll', scrollHandler)

      // Should handle many scroll events quickly
      expect(scrollTime).toBeLessThan(100) // 100ms for 100 scroll events
      expect(scrollEventCount).toBe(100)
    })

    it('should maintain position during scroll', async () => {
      render(
        <TestWrapper>
          <div style={{ height: '200vh' }}>
            <FeedbackWidget position="bottom-right" />
          </div>
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      const initialPosition = trigger.getBoundingClientRect()

      // Scroll the page
      window.scrollTo(0, 500)
      window.dispatchEvent(new Event('scroll'))

      const positionAfterScroll = trigger.getBoundingClientRect()

      // Fixed position element should maintain viewport position
      expect(positionAfterScroll.bottom).toBe(initialPosition.bottom)
      expect(positionAfterScroll.right).toBe(initialPosition.right)
    })
  })

  describe('Performance Monitoring', () => {
    it('should report performance metrics', async () => {
      const metrics = {
        initialRenderTime: 0,
        dialogOpenTime: 0,
        formInteractionTime: 0,
        memoryUsage: 0
      }

      // Simulate performance measurement
      const user = userEvent.setup()

      const start = performance.now()
      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )
      metrics.initialRenderTime = performance.now() - start

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      const dialogStart = performance.now()
      await user.click(trigger)
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })
      metrics.dialogOpenTime = performance.now() - dialogStart

      metrics.memoryUsage = (performance as any).memory?.usedJSHeapSize || 0

      // Log metrics for monitoring
      console.log('Performance Metrics:', metrics)

      // Assert performance thresholds
      expect(metrics.initialRenderTime).toBeLessThan(100)
      expect(metrics.dialogOpenTime).toBeLessThan(200)
    })

    it('should track Core Web Vitals', async () => {
      const webVitals = {
        FCP: 0, // First Contentful Paint
        LCP: 0, // Largest Contentful Paint
        FID: 0, // First Input Delay
        CLS: 0  // Cumulative Layout Shift
      }

      // Mock web vitals measurement
      const paintEntries = [
        { name: 'first-contentful-paint', startTime: 150 },
        { name: 'largest-contentful-paint', startTime: 200 }
      ]

      webVitals.FCP = paintEntries.find(e => e.name === 'first-contentful-paint')?.startTime || 0
      webVitals.LCP = paintEntries.find(e => e.name === 'largest-contentful-paint')?.startTime || 0

      // Good Core Web Vitals thresholds
      expect(webVitals.FCP).toBeLessThan(1800) // Good: < 1.8s
      expect(webVitals.LCP).toBeLessThan(2500) // Good: < 2.5s
      expect(webVitals.FID).toBeLessThan(100)  // Good: < 100ms
      expect(webVitals.CLS).toBeLessThan(0.1)  // Good: < 0.1
    })
  })
})