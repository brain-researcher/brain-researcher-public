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

// Mock API responses
const mockFetch = jest.fn()
global.fetch = mockFetch

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
        <div id="app">
          <button id="before-widget">Before Widget</button>
          {children}
          <button id="after-widget">After Widget</button>
        </div>
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

describe('Feedback Widget Keyboard Navigation', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        success: true,
        id: 'feedback-123'
      })
    })
  })

  describe('Trigger Button Navigation', () => {
    it('can be focused and activated with keyboard', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Tab to the trigger button
      await user.tab()
      await user.tab() // Skip "Before Widget" button

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      expect(trigger).toHaveFocus()

      // Activate with Enter key
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })
    })

    it('can be activated with Space key', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      trigger.focus()

      await user.keyboard(' ')

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })
    })

    it('navigates through quick actions with keyboard', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      trigger.focus()

      // Activate to show quick actions
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(screen.getByText('Report Bug')).toBeInTheDocument()
      })

      // Tab through quick action buttons
      await user.tab()
      expect(screen.getByRole('button', { name: /report bug/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /feature idea/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /ui issue/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /general feedback/i })).toHaveFocus()

      // Activate with Enter
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })
    })

    it('supports arrow key navigation in star rating', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Focus first star
      const stars = screen.getAllByRole('button', { name: /star/i })
      stars[0].focus()

      // Navigate with arrow keys
      await user.keyboard('{ArrowRight}')
      expect(stars[1]).toHaveFocus()

      await user.keyboard('{ArrowRight}')
      expect(stars[2]).toHaveFocus()

      await user.keyboard('{ArrowLeft}')
      expect(stars[1]).toHaveFocus()

      // Home/End keys
      await user.keyboard('{End}')
      expect(stars[4]).toHaveFocus()

      await user.keyboard('{Home}')
      expect(stars[0]).toHaveFocus()

      // Select with Space or Enter
      await user.keyboard(' ')
      expect(stars[0]).toHaveAttribute('aria-pressed', 'true')
    })
  })

  describe('Dialog Navigation', () => {
    it('traps focus within dialog', async () => {
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

      // Get all focusable elements within dialog
      const dialog = screen.getByRole('dialog')
      const focusableElements = dialog.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )

      // Focus should start on first element (rating section)
      const firstElement = focusableElements[0] as HTMLElement
      expect(firstElement).toHaveFocus()

      // Tab through all elements
      for (let i = 1; i < focusableElements.length; i++) {
        await user.tab()
        expect(focusableElements[i]).toHaveFocus()
      }

      // Tab from last element should go to first
      await user.tab()
      expect(firstElement).toHaveFocus()

      // Shift+Tab from first element should go to last
      await user.tab({ shift: true })
      const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement
      expect(lastElement).toHaveFocus()
    })

    it('closes dialog with Escape key', async () => {
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

      await user.keyboard('{Escape}')

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })

      // Focus should return to trigger button
      expect(screen.getByRole('button', { name: /feedback menu/i })).toHaveFocus()
    })

    it('restores focus when dialog closes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      trigger.focus()
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Close with cancel button
      await user.click(screen.getByRole('button', { name: /cancel/i }))

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })

      // Focus should be restored to trigger
      expect(trigger).toHaveFocus()
    })
  })

  describe('Form Navigation', () => {
    it('navigates through form fields in logical order', async () => {
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

      // Tab order should be: stars -> emojis -> category -> title -> description -> screenshot -> buttons
      const expectedOrder = [
        () => screen.getAllByRole('button', { name: /star/i })[0],
        () => screen.getAllByRole('button', { name: /emoji/i })[0],
        () => screen.getByRole('combobox', { name: /category/i }),
        () => screen.getByRole('textbox', { name: /title/i }),
        () => screen.getByRole('textbox', { name: /description/i }),
        () => screen.getByLabelText(/screenshot/i),
        () => screen.getByRole('button', { name: /capture.*page/i }),
        () => screen.getByRole('button', { name: /submit/i }),
        () => screen.getByRole('button', { name: /cancel/i })
      ]

      for (const getElement of expectedOrder) {
        const element = getElement()
        expect(element).toHaveFocus()
        await user.tab()
      }
    })

    it('supports form submission with Enter key on submit button', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill required fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      categorySelect.focus()
      await user.keyboard('{ArrowDown}') // Open dropdown
      await user.keyboard('{ArrowDown}') // Select first option
      await user.keyboard('{Enter}') // Confirm selection

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Keyboard test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing keyboard navigation and form submission.')

      // Navigate to submit button and activate with Enter
      const submitButton = screen.getByRole('button', { name: /submit/i })
      submitButton.focus()
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled()
      })
    })

    it('handles form validation errors with keyboard navigation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to submit empty form
      const submitButton = screen.getByRole('button', { name: /submit/i })
      submitButton.focus()
      await user.keyboard('{Enter}')

      // Focus should move to first invalid field
      await waitFor(() => {
        const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
        expect(firstStar).toHaveFocus()
      })

      // Error message should be announced
      expect(screen.getByRole('alert')).toHaveTextContent(/rating is required/i)
    })
  })

  describe('Screenshot Section Navigation', () => {
    it('navigates between screenshot controls', async () => {
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

      // Navigate to screenshot section
      const fileInput = screen.getByLabelText(/upload.*screenshot/i)
      fileInput.focus()

      // Tab to capture buttons
      await user.tab()
      expect(screen.getByRole('button', { name: /capture.*page/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /capture.*visible/i })).toHaveFocus()

      // Activate capture with keyboard
      await user.keyboard('{Enter}')

      // Should show loading state
      expect(screen.getByText(/capturing/i)).toBeInTheDocument()
    })

    it('handles screenshot removal with keyboard', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Upload a screenshot first
      const fileInput = screen.getByLabelText(/upload.*screenshot/i)
      const mockFile = new File(['screenshot'], 'test.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // Navigate to remove button
      const removeButton = screen.getByRole('button', { name: /remove.*screenshot/i })
      removeButton.focus()

      // Remove with keyboard
      await user.keyboard('{Enter}')

      expect(screen.queryByTestId('screenshot-preview')).not.toBeInTheDocument()

      // Focus should return to file input
      expect(fileInput).toHaveFocus()
    })
  })

  describe('Multi-step Form Navigation', () => {
    it('navigates between form steps with keyboard', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget multiStep />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Step 1: Fill rating and category
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      categorySelect.focus()
      await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')

      // Navigate to Next button and activate with keyboard
      const nextButton = screen.getByRole('button', { name: /next/i })
      nextButton.focus()
      await user.keyboard('{Enter}')

      // Step 2: Should focus on first field
      expect(screen.getByRole('textbox', { name: /title/i })).toHaveFocus()

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Multi-step test')
      await user.tab()
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing multi-step navigation.')

      // Go to next step
      await user.tab()
      await user.keyboard('{Enter}')

      // Step 3: Review step
      expect(screen.getByText(/review.*submission/i)).toBeInTheDocument()

      // Navigate back with keyboard
      const backButton = screen.getByRole('button', { name: /back/i })
      backButton.focus()
      await user.keyboard('{Enter}')

      // Should return to step 2 with focus on first field
      expect(screen.getByRole('textbox', { name: /title/i })).toHaveFocus()
    })

    it('supports keyboard shortcuts for step navigation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget multiStep />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Alt+Right to go to next step (if valid)
      await user.keyboard('{Alt>}{ArrowRight}{/Alt}')

      // Should not advance because step is invalid
      expect(screen.getByText(/step 1.*3/i)).toBeInTheDocument()

      // Fill required fields
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      categorySelect.focus()
      await user.keyboard('{ArrowDown}{Enter}')

      // Now Alt+Right should work
      await user.keyboard('{Alt>}{ArrowRight}{/Alt}')
      expect(screen.getByText(/step 2.*3/i)).toBeInTheDocument()

      // Alt+Left to go back
      await user.keyboard('{Alt>}{ArrowLeft}{/Alt}')
      expect(screen.getByText(/step 1.*3/i)).toBeInTheDocument()
    })
  })

  describe('Success State Navigation', () => {
    it('focuses close button in success message', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      categorySelect.focus()
      await user.keyboard('{ArrowDown}{Enter}')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Success test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing success state navigation.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback submitted successfully/i)).toBeInTheDocument()
      })

      // Focus should be on close button
      const closeButton = screen.getByRole('button', { name: /close/i })
      expect(closeButton).toHaveFocus()

      // Can close with keyboard
      await user.keyboard('{Enter}')

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })
    })
  })

  describe('Accessibility Shortcuts', () => {
    it('supports accessibility shortcuts', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Global shortcut to open feedback (Ctrl+/)
      await user.keyboard('{Control>}/{/Control}')

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Skip to main content shortcut (should focus first form field)
      await user.keyboard('{Control>}{Shift>}m{/Shift}{/Control}')

      const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
      expect(firstStar).toHaveFocus()

      // Skip to submit button shortcut
      await user.keyboard('{Control>}{Shift>}s{/Shift}{/Control}')

      const submitButton = screen.getByRole('button', { name: /submit/i })
      expect(submitButton).toHaveFocus()
    })

    it('announces important state changes to screen readers', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Rating change should be announced
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])
      expect(screen.getByRole('status')).toHaveTextContent(/4 stars selected/i)

      // Category change should be announced
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')
      expect(screen.getByRole('status')).toHaveTextContent(/bug report selected/i)

      // Form submission should be announced
      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Announcement test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing screen reader announcements.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent(/submitting feedback/i)
      })

      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent(/feedback submitted successfully/i)
      })
    })
  })
})