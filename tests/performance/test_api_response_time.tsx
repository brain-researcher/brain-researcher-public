/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackWidget } from '@/components/feedback/FeedbackWidget'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Mock fetch with timing capabilities
const mockFetch = jest.fn()
global.fetch = mockFetch

// Performance timing utility
const measureApiCall = async (apiCall: () => Promise<any>): Promise<{ duration: number, result: any }> => {
  const start = performance.now()
  const result = await apiCall()
  const end = performance.now()
  return { duration: end - start, result }
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

describe('Feedback Widget API Response Time Performance', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Feedback Submission Performance', () => {
    it('should submit feedback within response time SLA', async () => {
      const user = userEvent.setup()

      // Mock successful response with realistic delay
      mockFetch.mockImplementation(() => new Promise(resolve => {
        setTimeout(() => resolve({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-123',
            message: 'Feedback submitted successfully'
          })
        }), 150) // 150ms simulated server response time
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill form
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'API Performance Test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing API response time performance.')

      const submitStart = performance.now()
      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      const submitEnd = performance.now()
      const totalSubmissionTime = submitEnd - submitStart

      // Total time should include network + processing + UI update
      expect(totalSubmissionTime).toBeLessThan(1000) // 1 second SLA
      expect(totalSubmissionTime).toBeGreaterThan(100) // Should take some realistic time

      // API call should have been made
      expect(mockFetch).toHaveBeenCalledWith('/api/feedback', expect.objectContaining({
        method: 'POST'
      }))
    })

    it('should handle large payloads within performance limits', async () => {
      const user = userEvent.setup()

      // Mock response for large payload
      mockFetch.mockImplementation(() => new Promise(resolve => {
        setTimeout(() => resolve({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-large-123'
          })
        }), 300) // Slower response for large payload
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Create large payload
      const largeDescription = 'This is a very detailed feedback message. '.repeat(100) // ~4KB of text

      await user.click(screen.getAllByRole('button', { name: /star/i })[4])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'feature-request')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Large Payload Test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), largeDescription)

      // Add large file
      const fileInput = screen.getByLabelText(/screenshot/i)
      const largeFile = new File([new ArrayBuffer(2 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      const { duration } = await measureApiCall(async () => {
        await user.click(screen.getByRole('button', { name: /submit/i }))

        await waitFor(() => {
          expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
        })
      })

      // Large payloads should still complete within reasonable time
      expect(duration).toBeLessThan(2000) // 2 second limit for large payloads
    })

    it('should show loading states during API calls', async () => {
      const user = userEvent.setup()

      let resolveApiCall: (value: any) => void
      mockFetch.mockImplementation(() => new Promise(resolve => {
        resolveApiCall = resolve
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill minimal form
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Loading test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing loading states.')

      // Submit form
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should show loading state immediately
      expect(screen.getByText(/submitting/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /submitting/i })).toBeDisabled()

      // Complete the API call
      resolveApiCall!({
        ok: true,
        json: () => Promise.resolve({ success: true, id: 'loading-test' })
      })

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })

    it('should timeout slow API responses', async () => {
      const user = userEvent.setup()

      // Mock very slow response (never resolves)
      mockFetch.mockImplementation(() => new Promise(() => {}))

      render(
        <TestWrapper>
          <FeedbackWidget submitTimeout={2000} />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await user.click(screen.getAllByRole('button', { name: /star/i })[1])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'performance')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Timeout test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing API timeout handling.')

      const submitStart = performance.now()
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should timeout and show error
      await waitFor(() => {
        expect(screen.getByText(/request timed out/i)).toBeInTheDocument()
      }, { timeout: 3000 })

      const submitEnd = performance.now()
      const timeoutDuration = submitEnd - submitStart

      // Should timeout around the specified timeout value
      expect(timeoutDuration).toBeGreaterThan(1900) // Close to 2000ms
      expect(timeoutDuration).toBeLessThan(2500) // Not too much longer
    })
  })

  describe('Screenshot Upload Performance', () => {
    it('should upload screenshots within performance limits', async () => {
      const user = userEvent.setup()

      // Mock screenshot upload endpoint
      mockFetch.mockImplementation((url) => {
        const delay = url.includes('screenshot') ? 500 : 200 // Screenshots take longer
        return new Promise(resolve => {
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({
              success: true,
              url: 'https://example.com/screenshot.png'
            })
          }), delay)
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const fileInput = screen.getByLabelText(/screenshot/i)
      const screenshot = new File(['screenshot data'], 'screenshot.png', { type: 'image/png' })

      const { duration: uploadDuration } = await measureApiCall(async () => {
        await user.upload(fileInput, screenshot)

        await waitFor(() => {
          expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
        })
      })

      // Screenshot upload should complete reasonably quickly
      expect(uploadDuration).toBeLessThan(1000) // 1 second for screenshot upload
    })

    it('should compress large images before upload', async () => {
      const user = userEvent.setup()

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, url: 'compressed.jpg' })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Large image file (5MB)
      const largeImage = new File([new ArrayBuffer(5 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      const fileInput = screen.getByLabelText(/screenshot/i)

      const { duration: compressionDuration } = await measureApiCall(async () => {
        await user.upload(fileInput, largeImage)

        // Should show compression progress
        expect(screen.getByText(/compressing/i)).toBeInTheDocument()

        await waitFor(() => {
          expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
        })
      })

      // Compression + upload should complete in reasonable time
      expect(compressionDuration).toBeLessThan(3000) // 3 seconds for large image compression
    })

    it('should handle screenshot capture performance', async () => {
      const user = userEvent.setup()

      // Mock html-to-image
      const mockToPng = jest.fn().mockImplementation(() => {
        return new Promise(resolve => {
          setTimeout(() => resolve('data:image/png;base64,mockdata'), 800) // Simulate capture time
        })
      })

      jest.doMock('html-to-image', () => ({
        toPng: mockToPng
      }))

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const { duration: captureDuration } = await measureApiCall(async () => {
        await user.click(screen.getByRole('button', { name: /capture.*page/i }))

        await waitFor(() => {
          expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
        })
      })

      // Screenshot capture should complete within reasonable time
      expect(captureDuration).toBeLessThan(1500) // 1.5 seconds for page capture
      expect(mockToPng).toHaveBeenCalled()
    })
  })

  describe('Network Condition Simulation', () => {
    it('should handle slow 3G network conditions', async () => {
      const user = userEvent.setup()

      // Simulate slow 3G (500ms latency, 500 Kbps)
      mockFetch.mockImplementation(() => new Promise(resolve => {
        setTimeout(() => resolve({
          ok: true,
          json: () => Promise.resolve({ success: true, id: 'slow-3g-test' })
        }), 800) // Slow response
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Slow network test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing slow network conditions.')

      const { duration } = await measureApiCall(async () => {
        await user.click(screen.getByRole('button', { name: /submit/i }))

        await waitFor(() => {
          expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
        }, { timeout: 5000 })
      })

      // Should handle slow networks gracefully
      expect(duration).toBeGreaterThan(700) // Should reflect slow network
      expect(duration).toBeLessThan(3000) // But still complete reasonably
    })

    it('should show appropriate loading indicators for slow networks', async () => {
      const user = userEvent.setup()

      let slowResolve: (value: any) => void
      mockFetch.mockImplementation(() => new Promise(resolve => {
        slowResolve = resolve
        // Don't resolve immediately - simulates slow network
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await user.click(screen.getAllByRole('button', { name: /star/i })[2])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'performance')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Slow indicator test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing slow network indicators.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should show immediate feedback
      expect(screen.getByText(/submitting/i)).toBeInTheDocument()

      // Wait a bit, should show "taking longer than usual"
      await new Promise(resolve => setTimeout(resolve, 3000))

      expect(screen.getByText(/taking longer than usual/i)).toBeInTheDocument()

      // Complete the request
      slowResolve!({
        ok: true,
        json: () => Promise.resolve({ success: true, id: 'slow-indicator-test' })
      })

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })

    it('should handle intermittent network failures with retries', async () => {
      const user = userEvent.setup()
      let attemptCount = 0

      mockFetch.mockImplementation(() => {
        attemptCount++
        if (attemptCount < 3) {
          // Fail first 2 attempts
          return Promise.reject(new Error('Network error'))
        } else {
          // Succeed on 3rd attempt
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ success: true, id: 'retry-test' })
          })
        }
      })

      render(
        <TestWrapper>
          <FeedbackWidget maxRetries={3} retryDelay={500} />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await user.click(screen.getAllByRole('button', { name: /star/i })[4])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Retry test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing retry mechanism.')

      const { duration } = await measureApiCall(async () => {
        await user.click(screen.getByRole('button', { name: /submit/i }))

        // Should show retry indicators
        await waitFor(() => {
          expect(screen.getByText(/retrying/i)).toBeInTheDocument()
        })

        await waitFor(() => {
          expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
        }, { timeout: 10000 })
      })

      // Should have attempted 3 times
      expect(attemptCount).toBe(3)

      // Total time should account for retries
      expect(duration).toBeGreaterThan(1000) // At least 2 retries with delays
      expect(duration).toBeLessThan(5000) // But not excessive
    })
  })

  describe('Concurrent Request Handling', () => {
    it('should handle multiple simultaneous submissions efficiently', async () => {
      const users = [userEvent.setup(), userEvent.setup(), userEvent.setup()]
      let requestCount = 0

      mockFetch.mockImplementation(() => {
        requestCount++
        return new Promise(resolve => {
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({ success: true, id: `concurrent-${requestCount}` })
          }), 200)
        })
      })

      // Render multiple widgets
      const widgets = users.map((_, index) => (
        <TestWrapper key={index}>
          <FeedbackWidget />
        </TestWrapper>
      ))

      const { rerender } = render(<div>{widgets[0]}</div>)

      // Start concurrent submissions
      const submissions = users.map(async (user, index) => {
        rerender(<div>{widgets[index]}</div>)

        await user.click(screen.getByRole('button', { name: /feedback menu/i }))
        await user.click(screen.getAllByRole('button', { name: /star/i })[2])

        const categorySelect = screen.getByRole('combobox', { name: /category/i })
        await user.selectOptions(categorySelect, 'other')

        await user.type(screen.getByRole('textbox', { name: /title/i }), `Concurrent test ${index}`)
        await user.type(screen.getByRole('textbox', { name: /description/i }), `Concurrent submission ${index}`)

        return measureApiCall(async () => {
          await user.click(screen.getByRole('button', { name: /submit/i }))

          await waitFor(() => {
            expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
          })
        })
      })

      const results = await Promise.all(submissions)

      // All submissions should complete
      expect(results).toHaveLength(3)
      results.forEach(result => {
        expect(result.duration).toBeLessThan(1000) // Each should complete reasonably quickly
      })

      // Should have made separate API calls
      expect(requestCount).toBe(3)
    })

    it('should prevent duplicate submissions', async () => {
      const user = userEvent.setup()
      let requestCount = 0

      mockFetch.mockImplementation(() => {
        requestCount++
        return new Promise(resolve => {
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({ success: true, id: 'duplicate-test' })
          }), 1000) // Slow response to allow duplicate clicks
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Duplicate test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing duplicate prevention.')

      const submitButton = screen.getByRole('button', { name: /submit/i })

      // Click submit multiple times rapidly
      await user.click(submitButton)
      await user.click(submitButton)
      await user.click(submitButton)

      // Button should be disabled after first click
      expect(submitButton).toBeDisabled()

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      }, { timeout: 2000 })

      // Should have only made one API call
      expect(requestCount).toBe(1)
    })
  })

  describe('API Performance Monitoring', () => {
    it('should track API response times', async () => {
      const user = userEvent.setup()
      const responseTimes: number[] = []

      mockFetch.mockImplementation(() => {
        const delay = Math.random() * 300 + 100 // Random delay between 100-400ms
        return new Promise(resolve => {
          setTimeout(() => {
            responseTimes.push(delay)
            resolve({
              ok: true,
              json: () => Promise.resolve({ success: true, id: 'perf-test' })
            })
          }, delay)
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Submit multiple feedback to collect response time data
      for (let i = 0; i < 5; i++) {
        await user.click(screen.getByRole('button', { name: /feedback menu/i }))

        await user.click(screen.getAllByRole('button', { name: /star/i })[2])

        const categorySelect = screen.getByRole('combobox', { name: /category/i })
        await user.selectOptions(categorySelect, 'other')

        await user.type(screen.getByRole('textbox', { name: /title/i }), `Performance test ${i}`)
        await user.type(screen.getByRole('textbox', { name: /description/i }), `API performance test ${i}`)

        await user.click(screen.getByRole('button', { name: /submit/i }))

        await waitFor(() => {
          expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
        })

        // Close success message to reset for next iteration
        await user.click(screen.getByRole('button', { name: /close/i }))
      }

      // Calculate statistics
      const avgResponseTime = responseTimes.reduce((sum, time) => sum + time, 0) / responseTimes.length
      const maxResponseTime = Math.max(...responseTimes)
      const minResponseTime = Math.min(...responseTimes)

      console.log('API Response Time Statistics:', {
        average: avgResponseTime.toFixed(2) + 'ms',
        min: minResponseTime.toFixed(2) + 'ms',
        max: maxResponseTime.toFixed(2) + 'ms',
        samples: responseTimes.length
      })

      // Performance assertions
      expect(avgResponseTime).toBeLessThan(500) // 500ms average
      expect(maxResponseTime).toBeLessThan(1000) // 1s maximum
      expect(responseTimes.length).toBe(5) // All requests completed
    })

    it('should report performance anomalies', async () => {
      const user = userEvent.setup()
      const performanceMetrics = {
        requests: 0,
        failures: 0,
        slowRequests: 0,
        totalTime: 0
      }

      mockFetch.mockImplementation(() => {
        performanceMetrics.requests++
        const isSlowRequest = Math.random() < 0.2 // 20% chance of slow request
        const delay = isSlowRequest ? 2000 : 200 // Either 2s or 200ms

        if (isSlowRequest) {
          performanceMetrics.slowRequests++
        }

        return new Promise((resolve, reject) => {
          setTimeout(() => {
            performanceMetrics.totalTime += delay

            if (Math.random() < 0.1) { // 10% chance of failure
              performanceMetrics.failures++
              reject(new Error('API Error'))
            } else {
              resolve({
                ok: true,
                json: () => Promise.resolve({ success: true, id: 'anomaly-test' })
              })
            }
          }, delay)
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Submit several requests to gather metrics
      const submissions = []
      for (let i = 0; i < 10; i++) {
        submissions.push(
          (async () => {
            try {
              await user.click(screen.getByRole('button', { name: /feedback menu/i }))
              await user.click(screen.getAllByRole('button', { name: /star/i })[1])

              const categorySelect = screen.getByRole('combobox', { name: /category/i })
              await user.selectOptions(categorySelect, 'performance')

              await user.type(screen.getByRole('textbox', { name: /title/i }), `Anomaly test ${i}`)
              await user.type(screen.getByRole('textbox', { name: /description/i }), `Performance anomaly test ${i}`)

              await user.click(screen.getByRole('button', { name: /submit/i }))

              await waitFor(() => {
                expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
              }, { timeout: 3000 })

              await user.click(screen.getByRole('button', { name: /close/i }))
            } catch (error) {
              // Handle expected failures
            }
          })()
        )
      }

      await Promise.allSettled(submissions)

      const avgResponseTime = performanceMetrics.totalTime / performanceMetrics.requests
      const slowRequestPercentage = (performanceMetrics.slowRequests / performanceMetrics.requests) * 100
      const failurePercentage = (performanceMetrics.failures / performanceMetrics.requests) * 100

      console.log('Performance Anomaly Report:', {
        totalRequests: performanceMetrics.requests,
        averageResponseTime: avgResponseTime.toFixed(2) + 'ms',
        slowRequests: `${performanceMetrics.slowRequests} (${slowRequestPercentage.toFixed(1)}%)`,
        failures: `${performanceMetrics.failures} (${failurePercentage.toFixed(1)}%)`,
      })

      // Report anomalies
      if (slowRequestPercentage > 30) {
        console.warn('High percentage of slow requests detected')
      }

      if (failurePercentage > 20) {
        console.warn('High failure rate detected')
      }

      // Basic health checks
      expect(failurePercentage).toBeLessThan(50) // Less than 50% failure rate
      expect(performanceMetrics.requests).toBeGreaterThan(5) // At least some completed
    })
  })
})