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

// Mock fetch for API calls
const mockFetch = jest.fn()
global.fetch = mockFetch

// Mock FormData to inspect what's being sent
const mockFormData = {
  append: jest.fn(),
  get: jest.fn(),
  entries: jest.fn()
}
global.FormData = jest.fn(() => mockFormData) as any

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

describe('Feedback API Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockFormData.append.mockClear()
    mockFormData.get.mockClear()
    mockFormData.entries.mockClear()
  })

  describe('Successful API Submissions', () => {
    it('submits feedback data correctly to API', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-123',
          message: 'Feedback submitted successfully'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Open and fill form
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'API Test Bug')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'This is a test bug report for API integration testing.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify API call
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/feedback', {
          method: 'POST',
          body: expect.any(Object),
          headers: {
            'Accept': 'application/json',
          }
        })
      })

      // Verify FormData contains expected fields
      expect(mockFormData.append).toHaveBeenCalledWith('title', 'API Test Bug')
      expect(mockFormData.append).toHaveBeenCalledWith('description', 'This is a test bug report for API integration testing.')
      expect(mockFormData.append).toHaveBeenCalledWith('category', 'bug-report')
      expect(mockFormData.append).toHaveBeenCalledWith('rating', '4')
      expect(mockFormData.append).toHaveBeenCalledWith('url', expect.stringContaining('localhost'))
      expect(mockFormData.append).toHaveBeenCalledWith('userAgent', expect.any(String))
      expect(mockFormData.append).toHaveBeenCalledWith('timestamp', expect.any(String))
    })

    it('submits feedback with screenshot', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-124'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Add screenshot
      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot data'], 'screenshot.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // Fill other fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /ui-ux/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'UI Issue with Screenshot')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'The UI has alignment issues as shown in the screenshot.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })

      // Verify screenshot was included
      expect(mockFormData.append).toHaveBeenCalledWith('screenshot', expect.any(File))
    })

    it('submits feedback with emoji rating', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-125'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Select star and emoji ratings
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      await user.click(screen.getByRole('button', { name: /very.*happy/i }))
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Love the app!')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'This application is fantastic. Really easy to use!')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })

      // Verify emoji rating was included
      expect(mockFormData.append).toHaveBeenCalledWith('emojiRating', 'very-happy')
    })

    it('submits context information when provided', async () => {
      const user = userEvent.setup()
      const testContext = 'User is on dataset analysis page viewing charts'
      
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-126'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget context={testContext} />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /content/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Chart data issue')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'The chart is showing incorrect data values.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })

      expect(mockFormData.append).toHaveBeenCalledWith('context', testContext)
    })
  })

  describe('API Error Handling', () => {
    it('handles 400 Bad Request errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({
          success: false,
          error: 'Invalid feedback data',
          details: {
            title: 'Title is required',
            description: 'Description too short'
          }
        })
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
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      // Submit with invalid data
      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText('Invalid feedback data')).toBeInTheDocument()
        expect(screen.getByText('Title is required')).toBeInTheDocument()
        expect(screen.getByText('Description too short')).toBeInTheDocument()
      })
    })

    it('handles 413 Payload Too Large errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 413,
        json: () => Promise.resolve({
          success: false,
          error: 'Screenshot file is too large. Maximum size is 5MB.'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Upload large file
      const fileInput = screen.getByLabelText(/screenshot/i)
      const largeFile = new File([new ArrayBuffer(10 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      // Fill other fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /performance/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Large file test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing large file upload handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/screenshot file is too large/i)).toBeInTheDocument()
        expect(screen.getByText(/maximum size is 5MB/i)).toBeInTheDocument()
      })
    })

    it('handles 429 Rate Limit errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 429,
        json: () => Promise.resolve({
          success: false,
          error: 'Too many feedback submissions. Please wait 5 minutes before submitting again.',
          retryAfter: 300
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
      await user.click(screen.getByRole('option', { name: /other/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Rate limit test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing rate limit handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/too many feedback submissions/i)).toBeInTheDocument()
        expect(screen.getByText(/please wait 5 minutes/i)).toBeInTheDocument()
      })

      // Verify retry timer is shown
      expect(screen.getByTestId('retry-timer')).toBeInTheDocument()
    })

    it('handles 500 Internal Server Error', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({
          success: false,
          error: 'Internal server error. Please try again later.'
        })
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
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Server error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing server error handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/internal server error/i)).toBeInTheDocument()
        expect(screen.getByText(/please try again later/i)).toBeInTheDocument()
      })

      // Verify retry button is available
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    })

    it('handles network connectivity errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockRejectedValue(new Error('Failed to fetch'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /accessibility/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Network error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing network error handling.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument()
        expect(screen.getByText(/check your connection/i)).toBeInTheDocument()
      })

      // Verify offline indicator and retry options
      expect(screen.getByTestId('offline-indicator')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /save.*offline/i })).toBeInTheDocument()
    })
  })

  describe('Retry Mechanisms', () => {
    it('retries failed submissions with exponential backoff', async () => {
      const user = userEvent.setup()
      jest.useFakeTimers()

      mockFetch
        .mockRejectedValueOnce(new Error('Network error'))
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-retry-123'
          })
        })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /performance/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Retry test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing retry mechanism.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // First retry after 1 second
      jest.advanceTimersByTime(1000)
      
      // Second retry after 2 seconds
      jest.advanceTimersByTime(2000)
      
      // Third attempt succeeds after 4 seconds
      jest.advanceTimersByTime(4000)

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      expect(mockFetch).toHaveBeenCalledTimes(3)
      
      jest.useRealTimers()
    })

    it('allows manual retry after failure', async () => {
      const user = userEvent.setup()
      mockFetch
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-manual-retry-123'
          })
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
      await user.click(screen.getByRole('option', { name: /content/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Manual retry test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing manual retry functionality.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Wait for error message
      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument()
      })

      // Click retry button
      await user.click(screen.getByRole('button', { name: /retry/i }))

      // Should succeed on retry
      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      expect(mockFetch).toHaveBeenCalledTimes(2)
    })

    it('saves feedback offline for later submission', async () => {
      const user = userEvent.setup()
      const localStorageMock = {
        setItem: jest.fn(),
        getItem: jest.fn(),
        removeItem: jest.fn()
      }
      Object.defineProperty(window, 'localStorage', { value: localStorageMock })

      mockFetch.mockRejectedValue(new Error('Network error'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /feature request/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Offline save test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing offline save functionality.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Wait for error message
      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument()
      })

      // Click save offline button
      await user.click(screen.getByRole('button', { name: /save.*offline/i }))

      // Verify data was saved to localStorage
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'pendingFeedback',
        expect.stringContaining('Offline save test')
      )

      expect(screen.getByText(/feedback saved offline/i)).toBeInTheDocument()
    })
  })

  describe('Request Batching and Optimization', () => {
    it('batches multiple screenshot upload requests', async () => {
      const user = userEvent.setup()
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            urls: ['screenshot1.png', 'screenshot2.png']
          })
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-batch-123'
          })
        })

      render(
        <TestWrapper>
          <FeedbackWidget allowMultipleScreenshots />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Upload multiple screenshots
      const fileInput = screen.getByLabelText(/screenshot/i)
      const file1 = new File(['screenshot1'], 'screenshot1.png', { type: 'image/png' })
      const file2 = new File(['screenshot2'], 'screenshot2.png', { type: 'image/png' })
      
      await user.upload(fileInput, [file1, file2])

      // Fill other fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /ui-ux/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Multiple screenshots test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing multiple screenshot upload.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(2) // One for screenshots, one for feedback
      })

      // First call should be screenshot batch upload
      expect(mockFetch).toHaveBeenNthCalledWith(1, '/api/feedback/screenshots', expect.any(Object))
      
      // Second call should be feedback submission with screenshot URLs
      expect(mockFetch).toHaveBeenNthCalledWith(2, '/api/feedback', expect.any(Object))
    })

    it('compresses large images before upload', async () => {
      const user = userEvent.setup()
      const mockCanvas = {
        toBlob: jest.fn((callback) => callback(new Blob(['compressed'], { type: 'image/jpeg' })))
      }
      const mockCreateImageBitmap = jest.fn().mockResolvedValue({
        width: 1920,
        height: 1080
      })
      global.createImageBitmap = mockCreateImageBitmap
      global.HTMLCanvasElement.prototype.getContext = jest.fn(() => ({
        drawImage: jest.fn(),
        canvas: mockCanvas
      }))

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-compress-123'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Upload large image
      const fileInput = screen.getByLabelText(/screenshot/i)
      const largeFile = new File([new ArrayBuffer(8 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      await waitFor(() => {
        expect(screen.getByText(/compressing image/i)).toBeInTheDocument()
      })

      // Verify compression was applied
      await waitFor(() => {
        expect(mockCreateImageBitmap).toHaveBeenCalled()
        expect(mockCanvas.toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.8)
      })
    })
  })

  describe('Analytics and Tracking', () => {
    it('sends analytics data with feedback submission', async () => {
      const user = userEvent.setup()
      const mockAnalytics = {
        track: jest.fn()
      }
      window.analytics = mockAnalytics

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          success: true,
          id: 'feedback-analytics-123'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /feature request/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Analytics test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing analytics integration.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })

      // Verify analytics tracking
      expect(mockAnalytics.track).toHaveBeenCalledWith('feedback_submitted', {
        category: 'feature-request',
        rating: 5,
        hasScreenshot: false,
        feedbackId: 'feedback-analytics-123'
      })

      // Cleanup
      delete window.analytics
    })

    it('tracks feedback form abandonment', async () => {
      const user = userEvent.setup()
      const mockAnalytics = {
        track: jest.fn()
      }
      window.analytics = mockAnalytics

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Start filling form
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Abandoned feedback')

      // Close dialog without submitting
      await user.keyboard('{Escape}')

      expect(mockAnalytics.track).toHaveBeenCalledWith('feedback_abandoned', {
        completionPercentage: expect.any(Number),
        filledFields: ['rating', 'title']
      })

      // Cleanup
      delete window.analytics
    })
  })
})