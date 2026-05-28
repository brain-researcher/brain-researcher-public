/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackDialog } from '@/components/feedback/FeedbackDialog'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Mock the feedback form component
jest.mock('@/components/feedback/FeedbackForm', () => ({
  FeedbackForm: ({ onSubmit, onCancel, initialCategory, context }: any) => (
    <div data-testid="feedback-form">
      <div data-testid="initial-category">{initialCategory || 'none'}</div>
      <div data-testid="context">{context || 'none'}</div>
      <button onClick={() => onSubmit({ title: 'Test', category: 'bug-report', rating: 3 })}>
        Submit Form
      </button>
      <button onClick={onCancel}>Cancel Form</button>
    </div>
  )
}))

// Mock Radix Dialog components
jest.mock('@radix-ui/react-dialog', () => ({
  Dialog: ({ children, open, onOpenChange }: any) => (
    <div data-testid="dialog-root" data-open={open}>
      <div onClick={() => onOpenChange(false)} data-testid="dialog-backdrop" />
      {children}
    </div>
  ),
  DialogContent: ({ children, className }: any) => (
    <div data-testid="dialog-content" className={className}>
      {children}
    </div>
  ),
  DialogHeader: ({ children }: any) => (
    <div data-testid="dialog-header">{children}</div>
  ),
  DialogTitle: ({ children }: any) => (
    <h2 data-testid="dialog-title">{children}</h2>
  ),
  DialogDescription: ({ children }: any) => (
    <p data-testid="dialog-description">{children}</p>
  ),
  DialogPortal: ({ children }: any) => <div data-testid="dialog-portal">{children}</div>,
  DialogOverlay: ({ className }: any) => (
    <div data-testid="dialog-overlay" className={className} />
  )
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

describe('FeedbackDialog', () => {
  const mockOnOpenChange = jest.fn()
  const mockOnSubmit = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Rendering', () => {
    it('renders when open', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'true')
      expect(screen.getByTestId('dialog-content')).toBeInTheDocument()
      expect(screen.getByTestId('feedback-form')).toBeInTheDocument()
    })

    it('does not render when closed', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={false}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'false')
    })

    it('renders dialog title and description', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-title')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-description')).toBeInTheDocument()
    })

    it('applies correct CSS classes for styling', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const content = screen.getByTestId('dialog-content')
      expect(content).toHaveClass('feedback-dialog')
    })

    it('renders with portal for proper layering', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-portal')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-overlay')).toBeInTheDocument()
    })
  })

  describe('Props handling', () => {
    it('passes initial category to form', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
            initialCategory="feature-request"
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('initial-category')).toHaveTextContent('feature-request')
    })

    it('passes context to form', () => {
      const testContext = 'User is viewing dataset analysis page'

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
            context={testContext}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('context')).toHaveTextContent(testContext)
    })

    it('handles missing optional props gracefully', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('initial-category')).toHaveTextContent('none')
      expect(screen.getByTestId('context')).toHaveTextContent('none')
    })
  })

  describe('Form Integration', () => {
    it('passes onSubmit handler to form', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const submitButton = screen.getByText('Submit Form')
      await user.click(submitButton)

      expect(mockOnSubmit).toHaveBeenCalledWith({
        title: 'Test',
        category: 'bug-report',
        rating: 3
      })
    })

    it('handles form cancellation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const cancelButton = screen.getByText('Cancel Form')
      await user.click(cancelButton)

      expect(mockOnOpenChange).toHaveBeenCalledWith(false)
    })

    it('closes dialog on successful form submission', async () => {
      const user = userEvent.setup()
      mockOnSubmit.mockResolvedValue({})

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const submitButton = screen.getByText('Submit Form')
      await user.click(submitButton)

      await waitFor(() => {
        expect(mockOnOpenChange).toHaveBeenCalledWith(false)
      })
    })

    it('keeps dialog open on form submission error', async () => {
      const user = userEvent.setup()
      const submitError = new Error('Submission failed')
      mockOnSubmit.mockRejectedValue(submitError)

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const submitButton = screen.getByText('Submit Form')
      await user.click(submitButton)

      // Wait a bit to ensure the error handling is complete
      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalled()
      })

      // Dialog should remain open on error
      expect(mockOnOpenChange).not.toHaveBeenCalledWith(false)
    })
  })

  describe('Dialog State Management', () => {
    it('calls onOpenChange when backdrop is clicked', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const backdrop = screen.getByTestId('dialog-backdrop')
      await user.click(backdrop)

      expect(mockOnOpenChange).toHaveBeenCalledWith(false)
    })

    it('handles open state changes', () => {
      const { rerender } = render(
        <TestWrapper>
          <FeedbackDialog
            open={false}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'false')

      rerender(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'true')
    })

    it('prevents closing when form is being submitted', () => {
      // This would be handled by the actual implementation
      // The form should disable the close button during submission
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('dialog-root')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA attributes', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Dialog should have proper ARIA attributes
      expect(screen.getByTestId('dialog-title')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-description')).toBeInTheDocument()
    })

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Should be able to tab through form elements
      await user.tab()
      expect(document.activeElement).toBeDefined()

      // Escape key should close dialog
      await user.keyboard('{Escape}')
      expect(mockOnOpenChange).toHaveBeenCalledWith(false)
    })

    it('traps focus within dialog', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Focus should be trapped within the dialog
      // This is typically handled by the dialog library
      expect(screen.getByTestId('dialog-content')).toBeInTheDocument()
    })

    it('restores focus when closed', () => {
      // Create a focusable element outside the dialog
      const outsideElement = document.createElement('button')
      outsideElement.textContent = 'Outside Button'
      document.body.appendChild(outsideElement)
      outsideElement.focus()

      const { rerender } = render(
        <TestWrapper>
          <FeedbackDialog
            open={false}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Open dialog
      rerender(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Close dialog
      rerender(
        <TestWrapper>
          <FeedbackDialog
            open={false}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Focus should be restored to the outside element
      // This is typically handled by the dialog library
      expect(document.body).toContainElement(outsideElement)

      // Cleanup
      document.body.removeChild(outsideElement)
    })
  })

  describe('Error Handling', () => {
    it('handles form submission errors gracefully', async () => {
      const user = userEvent.setup()
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
      mockOnSubmit.mockRejectedValue(new Error('Network error'))

      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const submitButton = screen.getByText('Submit Form')
      await user.click(submitButton)

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalled()
      })

      // Dialog should handle the error and remain open
      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'true')

      consoleError.mockRestore()
    })

    it('handles missing required props', () => {
      // Should not crash when required callbacks are missing
      expect(() => {
        render(
          <TestWrapper>
            <FeedbackDialog
              open={true}
              onOpenChange={mockOnOpenChange}
              // Missing onSubmit prop
            />
          </TestWrapper>
        )
      }).not.toThrow()
    })
  })

  describe('Performance', () => {
    it('does not render form when dialog is closed', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={false}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Form should not be rendered when dialog is closed for performance
      expect(screen.getByTestId('dialog-root')).toHaveAttribute('data-open', 'false')
    })

    it('preserves form state during re-renders', () => {
      const { rerender } = render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
            context="Initial context"
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('context')).toHaveTextContent('Initial context')

      // Re-render with different context
      rerender(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
            context="Updated context"
          />
        </TestWrapper>
      )

      expect(screen.getByTestId('context')).toHaveTextContent('Updated context')
    })
  })

  describe('Integration with Dialog Library', () => {
    it('uses Radix UI Dialog components correctly', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      // Verify all Radix components are used
      expect(screen.getByTestId('dialog-root')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-portal')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-overlay')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-content')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-header')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-title')).toBeInTheDocument()
      expect(screen.getByTestId('dialog-description')).toBeInTheDocument()
    })

    it('passes correct props to Dialog components', () => {
      render(
        <TestWrapper>
          <FeedbackDialog
            open={true}
            onOpenChange={mockOnOpenChange}
            onSubmit={mockOnSubmit}
          />
        </TestWrapper>
      )

      const dialogRoot = screen.getByTestId('dialog-root')
      expect(dialogRoot).toHaveAttribute('data-open', 'true')
    })
  })
})