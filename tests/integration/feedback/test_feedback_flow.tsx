/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackWidget } from '@/components/feedback/FeedbackWidget'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Mock API responses
const mockFetch = jest.fn()
global.fetch = mockFetch

// Mock html-to-image for screenshot functionality
jest.mock('html-to-image', () => ({
  toPng: jest.fn().mockResolvedValue('data:image/png;base64,mockscreenshot')
}))

// Mock next/router
jest.mock('next/router', () => ({
  useRouter: () => ({
    pathname: '/test-page',
    query: {},
    push: jest.fn(),
  })
}))

// Test wrapper with all necessary providers
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
        <div id="test-app">
          {children}
        </div>
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

describe('Feedback Flow Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        success: true,
        id: 'feedback-123',
        message: 'Feedback submitted successfully'
      })
    })
  })

  describe('Complete Feedback Submission Flow', () => {
    it('completes full feedback submission with all fields', async () => {
      const user = userEvent.setup()
      const onSubmitted = jest.fn()

      render(
        <TestWrapper>
          <FeedbackWidget onFeedbackSubmitted={onSubmitted} />
        </TestWrapper>
      )

      // 1. Open feedback widget
      const triggerButton = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(triggerButton)

      // 2. Wait for dialog to open
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // 3. Fill out rating
      const stars = screen.getAllByRole('button', { name: /star/i })
      await user.click(stars[3]) // 4 stars

      // 4. Select emoji rating
      const happyEmoji = screen.getByRole('button', { name: /happy/i })
      await user.click(happyEmoji)

      // 5. Select category
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))

      // 6. Fill out title
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.type(titleInput, 'Chart rendering issue')

      // 7. Fill out description
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      await user.type(descriptionTextarea, 'The charts are not rendering properly when I select multiple datasets. This happens consistently across different browsers.')

      // 8. Add screenshot (mock file upload)
      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot data'], 'screenshot.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // 9. Submit form
      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)

      // 10. Verify API call
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/feedback', expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData)
        }))
      })

      // 11. Verify success callback
      expect(onSubmitted).toHaveBeenCalledWith('feedback-123')

      // 12. Verify success message
      expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()

      // 13. Verify dialog closes
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })
    })

    it('handles submission with minimal required fields', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Open dialog
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill minimum required fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[2]) // 3 stars
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Quick feedback')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Just wanted to say the app is working well.')

      // Submit
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify submission
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })

      expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
    })

    it('pre-populates form with quick action selection', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Click main trigger to show quick actions
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Click bug report quick action
      await user.click(screen.getByText('Report Bug'))

      // Verify dialog opens with bug-report category pre-selected
      await waitFor(() => {
        const categorySelect = screen.getByRole('combobox', { name: /category/i })
        expect(categorySelect).toHaveValue('bug-report')
      })

      // Verify template text is pre-filled
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      expect(descriptionTextarea).toHaveValue(expect.stringContaining('Steps to reproduce'))
    })
  })

  describe('Error Handling Flows', () => {
    it('handles network errors gracefully', async () => {
      const user = userEvent.setup()
      mockFetch.mockRejectedValue(new Error('Network error'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Fill and submit form
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Test bug')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'This is a test bug report.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify error message appears
      await waitFor(() => {
        expect(screen.getByText(/failed to submit feedback/i)).toBeInTheDocument()
      })

      // Verify dialog remains open for retry
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('handles API validation errors', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({
          success: false,
          error: 'Title is required'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Submit with missing title
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Description only')
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify server validation error is displayed
      await waitFor(() => {
        expect(screen.getByText('Title is required')).toBeInTheDocument()
      })
    })

    it('handles screenshot upload failures', async () => {
      const user = userEvent.setup()
      mockFetch
        .mockResolvedValueOnce({
          ok: false,
          status: 413,
          json: () => Promise.resolve({
            success: false,
            error: 'File too large'
          })
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-456'
          })
        })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      
      // Try to upload large screenshot
      const fileInput = screen.getByLabelText(/screenshot/i)
      const largeFile = new File([new ArrayBuffer(10 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      // Fill other fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Test feedback')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Test description')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should show error about file size
      await waitFor(() => {
        expect(screen.getByText('File too large')).toBeInTheDocument()
      })

      // Remove screenshot and resubmit
      await user.click(screen.getByRole('button', { name: /remove screenshot/i }))
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should succeed without screenshot
      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })
  })

  describe('Form Validation Flows', () => {
    it('prevents submission with missing required fields', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to submit empty form
      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).toBeDisabled()

      // Add rating
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      expect(submitButton).toBeDisabled()

      // Add category
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))
      expect(submitButton).toBeDisabled()

      // Add title
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Test')
      expect(submitButton).toBeDisabled()

      // Add description
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Test description')
      
      // Now submit should be enabled
      expect(submitButton).not.toBeDisabled()
    })

    it('shows real-time validation errors', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Enter short title
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.type(titleInput, 'Hi')
      await user.tab() // Trigger blur

      expect(screen.getByText(/title must be at least 5 characters/i)).toBeInTheDocument()

      // Fix title
      await user.clear(titleInput)
      await user.type(titleInput, 'Proper title')
      await user.tab()

      expect(screen.queryByText(/title must be at least 5 characters/i)).not.toBeInTheDocument()

      // Enter short description
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      await user.type(descriptionTextarea, 'Short')
      await user.tab()

      expect(screen.getByText(/description must be at least 20 characters/i)).toBeInTheDocument()
    })

    it('validates character limits', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Test title character limit
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      const longTitle = 'x'.repeat(101) // Over 100 char limit
      await user.type(titleInput, longTitle)

      expect(screen.getByText(/title cannot exceed 100 characters/i)).toBeInTheDocument()

      // Test description character limit
      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      const longDescription = 'x'.repeat(2001) // Over 2000 char limit
      await user.type(descriptionTextarea, longDescription)

      expect(screen.getByText(/description cannot exceed 2000 characters/i)).toBeInTheDocument()
    })
  })

  describe('Screenshot Integration Flows', () => {
    it('integrates automatic screenshot capture', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget enableAutoCapture />
        </TestWrapper>
      )

      // Open feedback - should automatically capture screenshot
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Wait for auto-capture to complete
      await waitFor(() => {
        expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
      })

      // Screenshot should be automatically included in submission
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Auto screenshot test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing automatic screenshot capture')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify screenshot was included in submission
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/feedback', expect.objectContaining({
          body: expect.any(FormData)
        }))
      })

      const formData = mockFetch.mock.calls[0][1].body
      expect(formData.get('screenshot')).toBeTruthy()
    })

    it('handles manual screenshot capture', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Manually capture screenshot
      await user.click(screen.getByRole('button', { name: /capture.*page/i }))

      // Wait for capture to complete
      await waitFor(() => {
        expect(screen.getByTestId('screenshot-preview')).toBeInTheDocument()
      })

      // Continue with form submission
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /ui-ux/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Manual screenshot test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing manual screenshot capture')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })
  })

  describe('User Experience Flows', () => {
    it('preserves form data when dialog is accidentally closed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Fill out form
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /feature request/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Export feature')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Would like to export charts as PDF')

      // Close dialog accidentally
      await user.keyboard('{Escape}')

      // Reopen dialog
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Verify form data is preserved
      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /title/i })).toHaveValue('Export feature')
        expect(screen.getByRole('textbox', { name: /description/i })).toHaveValue('Would like to export charts as PDF')
        expect(screen.getByRole('combobox', { name: /category/i })).toHaveValue('feature-request')
      })
    })

    it('provides contextual help and templates', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Select bug report category
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))

      // Verify bug report template appears
      expect(screen.getByText(/steps to reproduce/i)).toBeInTheDocument()
      expect(screen.getByText(/expected behavior/i)).toBeInTheDocument()
      expect(screen.getByText(/actual behavior/i)).toBeInTheDocument()

      // Change to feature request
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /feature request/i }))

      // Verify feature request template appears
      expect(screen.getByText(/describe.*feature/i)).toBeInTheDocument()
      expect(screen.getByText(/use case/i)).toBeInTheDocument()
    })

    it('shows progress indicator during submission', async () => {
      const user = userEvent.setup()
      let resolveSubmission: (value: any) => void
      
      mockFetch.mockImplementation(() => new Promise(resolve => {
        resolveSubmission = resolve
      }))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Fill and submit form
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /other/i }))
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Great app!')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Really enjoying using this application.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Verify loading state
      expect(screen.getByRole('button', { name: /submitting/i })).toBeDisabled()
      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()

      // Complete submission
      act(() => {
        resolveSubmission!({
          ok: true,
          json: () => Promise.resolve({
            success: true,
            id: 'feedback-789'
          })
        })
      })

      // Verify success state
      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })
  })

  describe('Multi-step Form Flow', () => {
    it('navigates through multi-step form correctly', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget multiStep />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Step 1: Rating and Category
      expect(screen.getByText(/step 1.*3/i)).toBeInTheDocument()
      
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /performance/i }))
      
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Step 2: Details
      expect(screen.getByText(/step 2.*3/i)).toBeInTheDocument()
      
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'App is slow')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'The application takes a long time to load charts with large datasets.')
      
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Step 3: Screenshot and Review
      expect(screen.getByText(/step 3.*3/i)).toBeInTheDocument()
      expect(screen.getByText(/review.*submission/i)).toBeInTheDocument()

      // Review shows all entered data
      expect(screen.getByText('4 stars')).toBeInTheDocument()
      expect(screen.getByText('Performance')).toBeInTheDocument()
      expect(screen.getByText('App is slow')).toBeInTheDocument()

      // Submit final form
      await user.click(screen.getByRole('button', { name: /submit feedback/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })
    })

    it('allows navigation back and forth in multi-step form', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget multiStep />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill step 1
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])
      
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.click(categorySelect)
      await user.click(screen.getByRole('option', { name: /bug report/i }))
      
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Fill step 2
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Login issue')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Cannot log in with correct credentials')
      
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Go back to step 1
      await user.click(screen.getByRole('button', { name: /back/i }))
      await user.click(screen.getByRole('button', { name: /back/i }))

      // Verify step 1 data is preserved
      expect(screen.getByRole('combobox', { name: /category/i })).toHaveValue('bug-report')
      
      const stars = screen.getAllByRole('button', { name: /star/i })
      expect(stars[0]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[1]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[2]).toHaveAttribute('aria-pressed', 'true')
      expect(stars[3]).toHaveAttribute('aria-pressed', 'false')

      // Navigate forward again
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Verify step 2 data is preserved
      expect(screen.getByRole('textbox', { name: /title/i })).toHaveValue('Login issue')
      expect(screen.getByRole('textbox', { name: /description/i })).toHaveValue('Cannot log in with correct credentials')
    })
  })
})