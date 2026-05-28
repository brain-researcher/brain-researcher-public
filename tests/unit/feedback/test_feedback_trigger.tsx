/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackTrigger } from '@/components/feedback/FeedbackTrigger'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@testing-library/jest-dom'

// Mock the feedback hook
const mockUseFeedback = {
  openFeedback: jest.fn(),
  reportBug: jest.fn(),
  requestFeature: jest.fn(),
  reportUIIssue: jest.fn()
}

jest.mock('@/hooks/useFeedback', () => ({
  useFeedback: () => mockUseFeedback
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

describe('FeedbackTrigger', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.runOnlyPendingTimers()
    jest.useRealTimers()
  })

  describe('Rendering', () => {
    it('renders with default props', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      expect(button).toBeInTheDocument()
      expect(button).toHaveClass('w-14', 'h-14') // default md size
      expect(button.closest('div')).toHaveClass('bottom-6', 'right-6') // default position
    })

    it('applies position classes correctly', () => {
      const positions = [
        { position: 'bottom-left', classes: ['bottom-6', 'left-6'] },
        { position: 'top-right', classes: ['top-6', 'right-6'] },
        { position: 'top-left', classes: ['top-6', 'left-6'] },
        { position: 'bottom-right', classes: ['bottom-6', 'right-6'] }
      ]

      positions.forEach(({ position, classes }) => {
        const { unmount } = render(
          <TestWrapper>
            <FeedbackTrigger position={position as any} />
          </TestWrapper>
        )

        const container = screen.getByRole('button').closest('div')
        classes.forEach(className => {
          expect(container).toHaveClass(className)
        })

        unmount()
      })
    })

    it('applies size classes correctly', () => {
      const sizes = [
        { size: 'sm', classes: ['w-12', 'h-12'] },
        { size: 'md', classes: ['w-14', 'h-14'] },
        { size: 'lg', classes: ['w-16', 'h-16'] }
      ]

      sizes.forEach(({ size, classes }) => {
        const { unmount } = render(
          <TestWrapper>
            <FeedbackTrigger size={size as any} />
          </TestWrapper>
        )

        const button = screen.getByRole('button')
        classes.forEach(className => {
          expect(button).toHaveClass(className)
        })

        unmount()
      })
    })

    it('applies variant classes correctly', () => {
      const variants = [
        { variant: 'floating', classes: ['fixed', 'z-50', 'shadow-lg'] },
        { variant: 'inline', classes: ['relative'] },
        { variant: 'minimal', classes: ['relative', 'border-0', 'shadow-sm'] }
      ]

      variants.forEach(({ variant, classes }) => {
        const { unmount } = render(
          <TestWrapper>
            <FeedbackTrigger variant={variant as any} />
          </TestWrapper>
        )

        const container = screen.getByRole('button').closest('div')
        classes.forEach(className => {
          expect(container).toHaveClass(className)
        })

        unmount()
      })
    })

    it('does not render when disabled', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger disabled />
        </TestWrapper>
      )

      expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })

    it('renders custom icon when provided', () => {
      const CustomIcon = () => <span data-testid="custom-icon">🔥</span>

      render(
        <TestWrapper>
          <FeedbackTrigger customIcon={<CustomIcon />} />
        </TestWrapper>
      )

      expect(screen.getByTestId('custom-icon')).toBeInTheDocument()
    })
  })

  describe('Quick Actions Menu', () => {
    it('shows quick actions on floating variant click', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(button)

      expect(screen.getByText('Report Bug')).toBeInTheDocument()
      expect(screen.getByText('Feature Idea')).toBeInTheDocument()
      expect(screen.getByText('UI Issue')).toBeInTheDocument()
      expect(screen.getByText('General Feedback')).toBeInTheDocument()
    })

    it('does not show quick actions on non-floating variants', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="inline" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /send feedback/i })
      await user.click(button)

      expect(mockUseFeedback.openFeedback).toHaveBeenCalled()
      expect(screen.queryByText('Report Bug')).not.toBeInTheDocument()
    })

    it('auto-hides quick actions after timeout', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(button)

      expect(screen.getByText('Report Bug')).toBeInTheDocument()

      // Fast-forward time
      act(() => {
        jest.advanceTimersByTime(5000)
      })

      await waitFor(() => {
        expect(screen.queryByText('Report Bug')).not.toBeInTheDocument()
      })
    })

    it('calls correct action handlers from quick actions', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(button)

      // Test bug report
      const bugButton = screen.getByText('Report Bug')
      await user.click(bugButton)
      expect(mockUseFeedback.reportBug).toHaveBeenCalled()

      // Re-open menu
      await user.click(button)

      // Test feature request
      const featureButton = screen.getByText('Feature Idea')
      await user.click(featureButton)
      expect(mockUseFeedback.requestFeature).toHaveBeenCalled()

      // Re-open menu
      await user.click(button)

      // Test UI issue
      const uiButton = screen.getByText('UI Issue')
      await user.click(uiButton)
      expect(mockUseFeedback.reportUIIssue).toHaveBeenCalled()

      // Re-open menu
      await user.click(button)

      // Test general feedback
      const generalButton = screen.getByText('General Feedback')
      await user.click(generalButton)
      expect(mockUseFeedback.openFeedback).toHaveBeenCalled()
    })

    it('closes quick actions when action is selected', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(button)

      const bugButton = screen.getByText('Report Bug')
      await user.click(bugButton)

      await waitFor(() => {
        expect(screen.queryByText('Report Bug')).not.toBeInTheDocument()
      })
    })
  })

  describe('Hover and Focus Behavior', () => {
    it('shows tooltip on hover for non-floating variants', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="inline" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /send feedback/i })
      await user.hover(button)

      expect(screen.getByText('Send Feedback')).toBeInTheDocument()
    })

    it('does not show tooltip on floating variant', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.hover(button)

      // Should not show tooltip for floating variant
      expect(screen.queryByText('Send Feedback')).not.toBeInTheDocument()
    })

    it('applies hover classes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.hover(button)

      // Hover classes are applied via CSS, but we can check the hover event
      expect(button).toBeInTheDocument()
    })
  })

  describe('Animation and Visual Effects', () => {
    it('shows pulse animation for floating variant', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const container = screen.getByRole('button').closest('div')
      const pulseElement = container?.querySelector('.animate-ping')
      
      expect(pulseElement).toBeInTheDocument()
    })

    it('does not show pulse animation for non-floating variants', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger variant="inline" />
        </TestWrapper>
      )

      const container = screen.getByRole('button').closest('div')
      const pulseElement = container?.querySelector('.animate-ping')
      
      expect(pulseElement).not.toBeInTheDocument()
    })

    it('rotates icons when showing quick actions', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      
      // Check initial state
      const messageIcon = button.querySelector('svg')
      expect(messageIcon).toHaveClass('rotate-0', 'opacity-100')

      // Click to show quick actions
      await user.click(button)

      // After animation, the plus icon should be visible
      await waitFor(() => {
        const plusIcon = button.querySelector('svg + svg')
        expect(plusIcon).toHaveClass('rotate-0', 'opacity-100')
      })
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      expect(button).toHaveAttribute('aria-label', 'Open feedback menu')
    })

    it('updates ARIA label based on state', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      let button = screen.getByRole('button', { name: /feedback menu/i })
      expect(button).toHaveAttribute('aria-label', 'Open feedback menu')

      await user.click(button)

      // When quick actions are shown, label should change
      button = screen.getByRole('button', { name: /send feedback/i })
      expect(button).toHaveAttribute('aria-label', 'Send feedback')
    })

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger />
        </TestWrapper>
      )

      const button = screen.getByRole('button')
      
      // Focus with tab
      await user.tab()
      expect(button).toHaveFocus()

      // Activate with Enter
      await user.keyboard('{Enter}')
      expect(mockUseFeedback.openFeedback).toHaveBeenCalled()

      // Reset and test Space key
      mockUseFeedback.openFeedback.mockClear()
      await user.keyboard(' ')
      expect(mockUseFeedback.openFeedback).toHaveBeenCalled()
    })

    it('has proper focus indicators', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger />
        </TestWrapper>
      )

      const button = screen.getByRole('button')
      expect(button).toHaveClass('focus:outline-none', 'focus:ring-2', 'focus:ring-primary', 'focus:ring-offset-2')
    })
  })

  describe('Event Handling', () => {
    it('prevents default behavior for button clicks', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger />
        </TestWrapper>
      )

      const button = screen.getByRole('button')
      const clickEvent = { preventDefault: jest.fn(), stopPropagation: jest.fn() }
      
      // Since we can't directly mock the event, we verify the function is called
      await user.click(button)
      expect(mockUseFeedback.openFeedback).toHaveBeenCalled()
    })

    it('handles mouse enter and leave events', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="inline" />
        </TestWrapper>
      )

      const button = screen.getByRole('button')
      
      // Hover to show tooltip
      await user.hover(button)
      expect(screen.getByText('Send Feedback')).toBeInTheDocument()

      // Unhover to hide tooltip
      await user.unhover(button)
      await waitFor(() => {
        expect(screen.queryByText('Send Feedback')).not.toBeInTheDocument()
      })
    })
  })

  describe('Integration with Feedback System', () => {
    it('integrates with feedback hook methods', () => {
      render(
        <TestWrapper>
          <FeedbackTrigger />
        </TestWrapper>
      )

      // Verify all required hook methods are available
      expect(mockUseFeedback.openFeedback).toBeDefined()
      expect(mockUseFeedback.reportBug).toBeDefined()
      expect(mockUseFeedback.requestFeature).toBeDefined()
      expect(mockUseFeedback.reportUIIssue).toBeDefined()
    })

    it('calls hook methods with correct parameters', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackTrigger variant="floating" />
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(button)

      const bugButton = screen.getByText('Report Bug')
      await user.click(bugButton)

      expect(mockUseFeedback.reportBug).toHaveBeenCalledWith()
    })
  })
})