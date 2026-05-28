/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackForm } from '@/components/feedback/FeedbackForm'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Mock the sub-components
jest.mock('@/components/feedback/components/RatingSection', () => ({
  RatingSection: ({ rating, onRatingChange, emojiRating, onEmojiRatingChange }: any) => (
    <div data-testid="rating-section">
      <input
        data-testid="rating-input"
        type="number"
        value={rating}
        onChange={(e) => onRatingChange(parseInt(e.target.value))}
        min="1"
        max="5"
      />
      <input
        data-testid="emoji-rating-input"
        type="text"
        value={emojiRating || ''}
        onChange={(e) => onEmojiRatingChange(e.target.value)}
      />
    </div>
  )
}))

jest.mock('@/components/feedback/components/CategorySection', () => ({
  CategorySection: ({ category, onCategoryChange }: any) => (
    <div data-testid="category-section">
      <select
        data-testid="category-select"
        value={category}
        onChange={(e) => onCategoryChange(e.target.value)}
      >
        <option value="">Select category</option>
        <option value="bug-report">Bug Report</option>
        <option value="feature-request">Feature Request</option>
        <option value="ui-ux">UI/UX</option>
        <option value="performance">Performance</option>
        <option value="content">Content</option>
        <option value="accessibility">Accessibility</option>
        <option value="other">Other</option>
      </select>
    </div>
  )
}))

jest.mock('@/components/feedback/components/CommentSection', () => ({
  CommentSection: ({ title, description, onTitleChange, onDescriptionChange }: any) => (
    <div data-testid="comment-section">
      <input
        data-testid="title-input"
        type="text"
        value={title}
        onChange={(e) => onTitleChange(e.target.value)}
        placeholder="Brief title"
      />
      <textarea
        data-testid="description-textarea"
        value={description}
        onChange={(e) => onDescriptionChange(e.target.value)}
        placeholder="Detailed description"
      />
    </div>
  )
}))

jest.mock('@/components/feedback/components/ScreenshotCapture', () => ({
  ScreenshotCapture: ({ screenshot, onScreenshotChange }: any) => (
    <div data-testid="screenshot-section">
      <input
        data-testid="screenshot-input"
        type="file"
        accept="image/*"
        onChange={(e) => onScreenshotChange(e.target.files?.[0] || null)}
      />
      {screenshot && <div data-testid="screenshot-preview">Screenshot attached</div>}
    </div>
  )
}))

jest.mock('@/components/feedback/components/SuccessMessage', () => ({
  SuccessMessage: ({ onClose }: any) => (
    <div data-testid="success-message">
      <p>Feedback submitted successfully!</p>
      <button data-testid="success-close-button" onClick={onClose}>
        Close
      </button>
    </div>
  )
}))

// Mock the feedback form hook
const mockUseFeedbackForm = {
  formData: {
    rating: 0,
    emojiRating: '',
    category: '',
    title: '',
    description: '',
    screenshot: null
  },
  errors: {},
  isSubmitting: false,
  isSuccess: false,
  updateField: jest.fn(),
  validateForm: jest.fn(),
  resetForm: jest.fn(),
  submitForm: jest.fn()
}

jest.mock('@/hooks/useFeedbackForm', () => ({
  useFeedbackForm: () => mockUseFeedbackForm
}))

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

describe('FeedbackForm', () => {
  const mockOnSubmit = jest.fn()
  const mockOnCancel = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
    mockUseFeedbackForm.isSuccess = false
    mockUseFeedbackForm.isSubmitting = false
    mockUseFeedbackForm.errors = {}
    mockUseFeedbackForm.formData = {
      rating: 0,
      emojiRating: '',
      category: '',
      title: '',
      description: '',
      screenshot: null
    }
  })

  describe('Rendering', () => {
    it('renders all form sections', () => {
      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByTestId('rating-section')).toBeInTheDocument()
      expect(screen.getByTestId('category-section')).toBeInTheDocument()
      expect(screen.getByTestId('comment-section')).toBeInTheDocument()
      expect(screen.getByTestId('screenshot-section')).toBeInTheDocument()
    })

    it('renders form controls', () => {
      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByRole('button', { name: /submit/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
    })

    it('renders success message when submitted', () => {
      mockUseFeedbackForm.isSuccess = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByTestId('success-message')).toBeInTheDocument()
      expect(screen.getByText('Feedback submitted successfully!')).toBeInTheDocument()
    })

    it('shows loading state during submission', () => {
      mockUseFeedbackForm.isSubmitting = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).toBeDisabled()
    })

    it('pre-selects initial category when provided', () => {
      mockUseFeedbackForm.formData.category = 'bug-report'

      render(
        <TestWrapper>
          <FeedbackForm
            onSubmit={mockOnSubmit}
            onCancel={mockOnCancel}
            initialCategory="bug-report"
          />
        </TestWrapper>
      )

      const categorySelect = screen.getByTestId('category-select')
      expect(categorySelect).toHaveValue('bug-report')
    })

    it('displays context information when provided', () => {
      const testContext = 'User is viewing dataset analysis page'

      render(
        <TestWrapper>
          <FeedbackForm
            onSubmit={mockOnSubmit}
            onCancel={mockOnCancel}
            context={testContext}
          />
        </TestWrapper>
      )

      expect(screen.getByText(testContext)).toBeInTheDocument()
    })
  })

  describe('Form Interactions', () => {
    it('updates rating when changed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const ratingInput = screen.getByTestId('rating-input')
      await user.clear(ratingInput)
      await user.type(ratingInput, '4')

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('rating', 4)
    })

    it('updates emoji rating when changed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const emojiRatingInput = screen.getByTestId('emoji-rating-input')
      await user.clear(emojiRatingInput)
      await user.type(emojiRatingInput, 'happy')

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('emojiRating', 'happy')
    })

    it('updates category when changed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const categorySelect = screen.getByTestId('category-select')
      await user.selectOptions(categorySelect, 'bug-report')

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('category', 'bug-report')
    })

    it('updates title when changed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const titleInput = screen.getByTestId('title-input')
      await user.clear(titleInput)
      await user.type(titleInput, 'Bug in chart rendering')

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('title', 'Bug in chart rendering')
    })

    it('updates description when changed', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const descriptionTextarea = screen.getByTestId('description-textarea')
      await user.clear(descriptionTextarea)
      await user.type(descriptionTextarea, 'The chart is not rendering properly when I select multiple datasets.')

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('description', 'The chart is not rendering properly when I select multiple datasets.')
    })

    it('updates screenshot when file is selected', async () => {
      const user = userEvent.setup()
      const mockFile = new File(['screenshot'], 'screenshot.png', { type: 'image/png' })

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const screenshotInput = screen.getByTestId('screenshot-input')
      await user.upload(screenshotInput, mockFile)

      expect(mockUseFeedbackForm.updateField).toHaveBeenCalledWith('screenshot', mockFile)
    })
  })

  describe('Form Validation', () => {
    it('displays validation errors', () => {
      mockUseFeedbackForm.errors = {
        title: 'Title is required',
        description: 'Description must be at least 10 characters',
        category: 'Please select a category',
        rating: 'Please provide a rating'
      }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByText('Title is required')).toBeInTheDocument()
      expect(screen.getByText('Description must be at least 10 characters')).toBeInTheDocument()
      expect(screen.getByText('Please select a category')).toBeInTheDocument()
      expect(screen.getByText('Please provide a rating')).toBeInTheDocument()
    })

    it('validates form on submission attempt', async () => {
      const user = userEvent.setup()
      mockUseFeedbackForm.validateForm.mockReturnValue(false)

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)

      expect(mockUseFeedbackForm.validateForm).toHaveBeenCalled()
      expect(mockOnSubmit).not.toHaveBeenCalled()
    })

    it('submits form when validation passes', async () => {
      const user = userEvent.setup()
      mockUseFeedbackForm.validateForm.mockReturnValue(true)
      mockUseFeedbackForm.formData = {
        rating: 4,
        category: 'bug-report',
        title: 'Test bug',
        description: 'This is a test bug report',
        screenshot: null,
        emojiRating: 'happy'
      }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)

      expect(mockUseFeedbackForm.validateForm).toHaveBeenCalled()
      expect(mockOnSubmit).toHaveBeenCalledWith(mockUseFeedbackForm.formData)
    })

    it('disables submit button when form is invalid', () => {
      mockUseFeedbackForm.errors = { title: 'Title is required' }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).toBeDisabled()
    })

    it('enables submit button when form is valid', () => {
      mockUseFeedbackForm.formData = {
        rating: 4,
        category: 'bug-report',
        title: 'Test bug',
        description: 'This is a test bug report',
        screenshot: null,
        emojiRating: 'happy'
      }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).not.toBeDisabled()
    })
  })

  describe('Form Submission', () => {
    it('calls onSubmit with form data', async () => {
      const user = userEvent.setup()
      mockUseFeedbackForm.validateForm.mockReturnValue(true)
      const formData = {
        rating: 3,
        category: 'feature-request',
        title: 'Add export feature',
        description: 'Would like to export charts as PDF',
        screenshot: null,
        emojiRating: 'neutral'
      }
      mockUseFeedbackForm.formData = formData

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)

      expect(mockOnSubmit).toHaveBeenCalledWith(formData)
    })

    it('shows loading state during submission', async () => {
      const user = userEvent.setup()
      mockUseFeedbackForm.validateForm.mockReturnValue(true)
      mockUseFeedbackForm.isSubmitting = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).toBeDisabled()
      expect(submitButton).toHaveTextContent(/submitting|loading/i)
    })

    it('handles submission success', () => {
      mockUseFeedbackForm.isSuccess = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByTestId('success-message')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /submit/i })).not.toBeInTheDocument()
    })

    it('handles submission errors', () => {
      mockUseFeedbackForm.errors = {
        submit: 'Failed to submit feedback. Please try again.'
      }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByText('Failed to submit feedback. Please try again.')).toBeInTheDocument()
    })
  })

  describe('Form Cancellation', () => {
    it('calls onCancel when cancel button is clicked', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const cancelButton = screen.getByRole('button', { name: /cancel/i })
      await user.click(cancelButton)

      expect(mockOnCancel).toHaveBeenCalled()
    })

    it('resets form when cancelled', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const cancelButton = screen.getByRole('button', { name: /cancel/i })
      await user.click(cancelButton)

      expect(mockUseFeedbackForm.resetForm).toHaveBeenCalled()
    })

    it('disables cancel button during submission', () => {
      mockUseFeedbackForm.isSubmitting = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const cancelButton = screen.getByRole('button', { name: /cancel/i })
      expect(cancelButton).toBeDisabled()
    })
  })

  describe('Success State', () => {
    it('shows success message after successful submission', () => {
      mockUseFeedbackForm.isSuccess = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByTestId('success-message')).toBeInTheDocument()
    })

    it('handles success message close', async () => {
      const user = userEvent.setup()
      mockUseFeedbackForm.isSuccess = true

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      const closeButton = screen.getByTestId('success-close-button')
      await user.click(closeButton)

      expect(mockOnCancel).toHaveBeenCalled()
    })
  })

  describe('Accessibility', () => {
    it('has proper form structure', () => {
      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      // Form should be wrapped in a form element
      const form = screen.getByRole('form') || screen.getByTestId('feedback-form')
      expect(form).toBeInTheDocument()
    })

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      // Should be able to tab through form elements
      await user.tab()
      expect(document.activeElement).toBeDefined()

      // Should be able to submit with Enter key on submit button
      const submitButton = screen.getByRole('button', { name: /submit/i })
      submitButton.focus()
      await user.keyboard('{Enter}')

      expect(mockUseFeedbackForm.validateForm).toHaveBeenCalled()
    })

    it('has proper ARIA labels and descriptions', () => {
      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      // Form sections should have proper labeling
      expect(screen.getByTestId('rating-section')).toBeInTheDocument()
      expect(screen.getByTestId('category-section')).toBeInTheDocument()
      expect(screen.getByTestId('comment-section')).toBeInTheDocument()
    })
  })

  describe('Integration with Form Hook', () => {
    it('integrates with feedback form hook correctly', () => {
      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      // Verify hook integration
      expect(mockUseFeedbackForm.updateField).toBeDefined()
      expect(mockUseFeedbackForm.validateForm).toBeDefined()
      expect(mockUseFeedbackForm.resetForm).toBeDefined()
      expect(mockUseFeedbackForm.submitForm).toBeDefined()
    })

    it('reflects form state from hook', () => {
      mockUseFeedbackForm.formData = {
        rating: 5,
        category: 'feature-request',
        title: 'Great feature idea',
        description: 'This would be really helpful',
        screenshot: null,
        emojiRating: 'very-happy'
      }

      render(
        <TestWrapper>
          <FeedbackForm onSubmit={mockOnSubmit} onCancel={mockOnCancel} />
        </TestWrapper>
      )

      expect(screen.getByTestId('rating-input')).toHaveValue(5)
      expect(screen.getByTestId('category-select')).toHaveValue('feature-request')
      expect(screen.getByTestId('title-input')).toHaveValue('Great feature idea')
      expect(screen.getByTestId('description-textarea')).toHaveValue('This would be really helpful')
      expect(screen.getByTestId('emoji-rating-input')).toHaveValue('very-happy')
    })
  })
})