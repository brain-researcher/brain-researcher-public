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

// Mock fetch for API calls
const mockFetch = jest.fn()
global.fetch = mockFetch

// Mock console methods
const mockConsoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
const mockConsoleWarn = jest.spyOn(console, 'warn').mockImplementation(() => {})

// Mock error boundary to catch React errors
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error?: Error }
> {
  constructor(props: any) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return <div data-testid="error-boundary">Something went wrong: {this.state.error?.message}</div>
    }
    return this.props.children
  }
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
        <ErrorBoundary>
          {children}
        </ErrorBoundary>
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

describe('Feedback Error Handling Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockConsoleError.mockClear()
    mockConsoleWarn.mockClear()
  })

  afterAll(() => {
    mockConsoleError.mockRestore()
    mockConsoleWarn.mockRestore()
  })

  describe('Network and API Errors', () => {
    it('handles complete network failure gracefully', async () => {
      const user = userEvent.setup()
      mockFetch.mockRejectedValue(new Error('Network request failed'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Network failure test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing network failure handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should display user-friendly error message
      await waitFor(() => {
        expect(screen.getByText(/unable to submit feedback/i)).toBeInTheDocument()
        expect(screen.getByText(/please check your internet connection/i)).toBeInTheDocument()
      })

      // Should provide retry and offline save options
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /save offline/i })).toBeInTheDocument()

      // Form should remain open
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('handles malformed API responses', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve('invalid json response')
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Malformed response test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing malformed API response handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/unexpected response from server/i)).toBeInTheDocument()
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
      })

      // Error should be logged
      expect(mockConsoleError).toHaveBeenCalled()
    })

    it('handles API timeout errors', async () => {
      const user = userEvent.setup()
      jest.useFakeTimers()

      mockFetch.mockImplementation(() => new Promise(() => {})) // Never resolves

      render(
        <TestWrapper>
          <FeedbackWidget submitTimeout={5000} />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /performance/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Timeout test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing timeout handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Fast-forward past timeout
      act(() => {
        jest.advanceTimersByTime(6000)
      })

      await waitFor(() => {
        expect(screen.getByText(/request timed out/i)).toBeInTheDocument()
        expect(screen.getByText(/server is taking too long to respond/i)).toBeInTheDocument()
      })

      jest.useRealTimers()
    })

    it('handles server error responses with detailed error messages', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 422,
        json: () => Promise.resolve({
          success: false,
          error: 'Validation failed',
          details: {
            title: ['Title must be unique', 'Title contains inappropriate content'],
            description: ['Description is too similar to spam'],
            screenshot: ['Image format not supported']
          }
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[1])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /content/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Detailed error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing detailed error handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText('Validation failed')).toBeInTheDocument()
        expect(screen.getByText('Title must be unique')).toBeInTheDocument()
        expect(screen.getByText('Title contains inappropriate content')).toBeInTheDocument()
        expect(screen.getByText('Description is too similar to spam')).toBeInTheDocument()
        expect(screen.getByText('Image format not supported')).toBeInTheDocument()
      })

      // Form should remain open for corrections
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
  })

  describe('Client-Side Errors', () => {
    it('handles screenshot capture failures', async () => {
      const user = userEvent.setup()
      
      // Mock html-to-image to throw error
      jest.doMock('html-to-image', () => ({
        toPng: jest.fn().mockRejectedValue(new Error('Screenshot capture failed'))
      }))

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, id: 'feedback-123' })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to capture screenshot
      await user.click(screen.getByRole('button', { name: /capture.*page/i }))

      await waitFor(() => {
        expect(screen.getByText(/failed to capture screenshot/i)).toBeInTheDocument()
        expect(screen.getByText(/you can still submit feedback without a screenshot/i)).toBeInTheDocument()
      })

      // User should be able to continue without screenshot
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /ui-ux/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Screenshot error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing screenshot capture error.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })

    it('handles file upload validation errors', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to upload invalid file
      const fileInput = screen.getByLabelText(/screenshot/i)
      const invalidFile = new File(['not an image'], 'document.pdf', { type: 'application/pdf' })
      
      await user.upload(fileInput, invalidFile)

      expect(screen.getByText(/please select a valid image file/i)).toBeInTheDocument()
      expect(screen.getByText(/supported formats: PNG, JPG, GIF/i)).toBeInTheDocument()

      // Try to upload oversized file
      const largeFile = new File([new ArrayBuffer(10 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      expect(screen.getByText(/file size too large/i)).toBeInTheDocument()
      expect(screen.getByText(/maximum size: 5MB/i)).toBeInTheDocument()

      // Error should clear when valid file is selected
      const validFile = new File(['valid image'], 'valid.png', { type: 'image/png' })
      await user.upload(fileInput, validFile)

      expect(screen.queryByText(/file size too large/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/please select a valid image file/i)).not.toBeInTheDocument()
    })

    it('handles form validation edge cases', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Test XSS attempt in title
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.type(titleInput, '<script>alert("xss")</script>')

      expect(screen.getByText(/title contains invalid characters/i)).toBeInTheDocument()

      // Test SQL injection attempt in description
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      await user.type(descriptionTextarea, "'; DROP TABLE feedback; --")

      expect(screen.getByText(/description contains suspicious content/i)).toBeInTheDocument()

      // Test extremely long input
      const veryLongText = 'x'.repeat(10000)
      await user.clear(titleInput)
      await user.type(titleInput, veryLongText)

      expect(screen.getByText(/title exceeds maximum length/i)).toBeInTheDocument()
    })
  })

  describe('State Management Errors', () => {
    it('handles context provider errors gracefully', async () => {
      // Mock context to throw error
      const BrokenFeedbackProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
        throw new Error('Context provider error')
      }

      render(
        <QueryClientProvider client={new QueryClient()}>
          <ErrorBoundary>
            <BrokenFeedbackProvider>
              <FeedbackWidget />
            </BrokenFeedbackProvider>
          </ErrorBoundary>
        </QueryClientProvider>
      )

      expect(screen.getByTestId('error-boundary')).toBeInTheDocument()
      expect(screen.getByText(/something went wrong: context provider error/i)).toBeInTheDocument()
    })

    it('handles state corruption gracefully', async () => {
      const user = userEvent.setup()

      // Mock localStorage to throw error
      const mockLocalStorage = {
        getItem: jest.fn().mockImplementation(() => {
          throw new Error('Storage quota exceeded')
        }),
        setItem: jest.fn(),
        removeItem: jest.fn()
      }
      Object.defineProperty(window, 'localStorage', { value: mockLocalStorage })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Should fall back gracefully without localStorage
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(mockConsoleWarn).toHaveBeenCalledWith(
        expect.stringContaining('Failed to load saved feedback'),
        expect.any(Error)
      )
    })

    it('handles concurrent submissions gracefully', async () => {
      const user = userEvent.setup()
      let submitCount = 0
      
      mockFetch.mockImplementation(() => {
        submitCount++
        if (submitCount === 1) {
          return new Promise(resolve => setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({ success: true, id: 'feedback-1' })
          }), 100))
        }
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({
            success: false,
            error: 'Duplicate submission detected'
          })
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
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Concurrent test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing concurrent submissions.')

      // Rapidly click submit multiple times
      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)
      await user.click(submitButton)
      await user.click(submitButton)

      // Should prevent multiple submissions
      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      // Should only make one successful API call
      expect(mockFetch).toHaveBeenCalledTimes(1)
    })
  })

  describe('Recovery and Resilience', () => {
    it('recovers from temporary API failures', async () => {
      const user = userEvent.setup()
      jest.useFakeTimers()

      mockFetch
        .mockRejectedValueOnce(new Error('Temporary server error'))
        .mockRejectedValueOnce(new Error('Still failing'))
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ success: true, id: 'feedback-recovered' })
        })

      render(
        <TestWrapper>
          <FeedbackWidget maxRetries={3} retryDelay={1000} />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /feature request/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Recovery test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing automatic recovery.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Show retry indicator
      expect(screen.getByText(/retrying/i)).toBeInTheDocument()

      // First retry
      act(() => {
        jest.advanceTimersByTime(1000)
      })

      // Second retry
      act(() => {
        jest.advanceTimersByTime(2000)
      })

      // Third attempt succeeds
      act(() => {
        jest.advanceTimersByTime(4000)
      })

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      jest.useRealTimers()
    })

    it('preserves form data across errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockRejectedValue(new Error('Network error'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Fill out complete form
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      await user.click(screen.getByRole('button', { name: /very.*happy/i }))
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /accessibility/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Data preservation test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing that form data is preserved across errors.')

      const fileInput = screen.getByLabelText(/screenshot/i)
      const testFile = new File(['screenshot'], 'test.png', { type: 'image/png' })
      await user.upload(fileInput, testFile)

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Wait for error
      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument()
      })

      // Verify all form data is preserved
      expect(screen.getAllByRole('button', { name: /star/i })[3]).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: /very.*happy/i })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('combobox', { name: /category/i })).toHaveValue('accessibility')
      expect(screen.getByRole('textbox', { name: /title/i })).toHaveValue('Data preservation test')
      expect(screen.getByRole('textbox', { name: /description/i })).toHaveValue('Testing that form data is preserved across errors.')
      expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()

      // User can fix the error and resubmit
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, id: 'feedback-recovered' })
      })

      await user.click(screen.getByRole('button', { name: /retry/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })

    it('provides helpful error recovery suggestions', async () => {
      const user = userEvent.setup()
      
      // Different error scenarios with specific suggestions
      const errorScenarios = [
        {
          response: { ok: false, status: 413 },
          json: { error: 'File too large' },
          suggestion: /try reducing image size or use a different image/i
        },
        {
          response: { ok: false, status: 429 },
          json: { error: 'Rate limit exceeded', retryAfter: 300 },
          suggestion: /please wait 5 minutes before submitting again/i
        },
        {
          error: new Error('Failed to fetch'),
          suggestion: /check your internet connection and try again/i
        }
      ]

      for (const scenario of errorScenarios) {
        mockFetch.mockClear()
        
        if (scenario.error) {
          mockFetch.mockRejectedValue(scenario.error)
        } else {
          mockFetch.mockResolvedValue({
            ...scenario.response,
            json: () => Promise.resolve(scenario.json)
          })
        }

        const { unmount } = render(
          <TestWrapper>
            <FeedbackWidget />
          </TestWrapper>
        )

        await user.click(screen.getByRole('button', { name: /feedback menu/i }))
        await user.click(screen.getAllByRole('button', { name: /star/i })[2])
        
        const categorySelect = screen.getByRole('combobox', { name: /category/i })
        await user.click(categorySelect)
        await user.click(screen.getByRole('option', { name: /other/i }))
        
        await user.type(screen.getByRole('textbox', { name: /title/i }), 'Error suggestion test')
        await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing error suggestions.')

        await user.click(screen.getByRole('button', { name: /submit/i }))

        await waitFor(() => {
          expect(screen.getByText(scenario.suggestion)).toBeInTheDocument()
        })

        unmount()
      }
    })
  })
})