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
        <div id="main-app">
          <header>
            <h1>Brain Researcher</h1>
            <nav>
              <button id="nav-home">Home</button>
              <button id="nav-datasets">Datasets</button>
              <button id="nav-analysis">Analysis</button>
            </nav>
          </header>
          <main>
            <button id="main-content-button">Main Content Button</button>
            {children}
            <button id="another-button">Another Button</button>
          </main>
          <footer>
            <button id="footer-button">Footer Button</button>
          </footer>
        </div>
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

// Helper function to get currently focused element
const getFocusedElement = () => document.activeElement as HTMLElement

describe('Feedback Widget Focus Management', () => {
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

  describe('Initial Focus Management', () => {
    it('does not steal focus when widget loads', () => {
      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Focus should remain on body or not interfere with existing focus
      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      expect(trigger).not.toHaveFocus()
    })

    it('can receive focus naturally through tab order', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Start from a known element
      const navButton = screen.getByText('Home')
      navButton.focus()

      // Tab through to feedback widget
      await user.tab() // Datasets
      await user.tab() // Analysis
      await user.tab() // Main Content Button
      await user.tab() // Feedback Widget

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      expect(trigger).toHaveFocus()
    })

    it('integrates properly in page tab order', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget position="top-right" />
        </TestWrapper>
      )

      // Tab through entire page
      let currentFocus = getFocusedElement()
      const focusOrder: string[] = []

      // Tab through all focusable elements
      for (let i = 0; i < 10; i++) {
        await user.tab()
        currentFocus = getFocusedElement()
        if (currentFocus.tagName !== 'BODY') {
          focusOrder.push(currentFocus.textContent || currentFocus.id || currentFocus.tagName)
        }
      }

      // Feedback widget should appear in logical order
      expect(focusOrder).toContain('Open feedback menu')
    })
  })

  describe('Dialog Opening Focus Management', () => {
    it('moves focus to dialog when opened', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        const dialog = screen.getByRole('dialog')
        expect(dialog).toBeInTheDocument()

        // Focus should be on first interactive element in dialog
        const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
        expect(firstStar).toHaveFocus()
      })
    })

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
      const focusableElements = Array.from(dialog.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )) as HTMLElement[]

      expect(focusableElements.length).toBeGreaterThan(0)

      // Tab through all elements and verify focus stays within dialog
      for (let i = 0; i < focusableElements.length + 2; i++) {
        const currentFocus = getFocusedElement()
        expect(dialog.contains(currentFocus)).toBe(true)
        await user.tab()
      }

      // After tabbing past last element, should return to first
      const firstElement = focusableElements[0]
      expect(firstElement).toHaveFocus()
    })

    it('handles Shift+Tab focus trapping correctly', async () => {
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

      const dialog = screen.getByRole('dialog')
      const focusableElements = Array.from(dialog.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )) as HTMLElement[]

      // Start from first element and Shift+Tab
      const firstElement = focusableElements[0]
      firstElement.focus()

      await user.tab({ shift: true })

      // Should go to last element
      const lastElement = focusableElements[focusableElements.length - 1]
      expect(lastElement).toHaveFocus()

      // Shift+Tab through all elements backward
      for (let i = focusableElements.length - 2; i >= 0; i--) {
        await user.tab({ shift: true })
        expect(focusableElements[i]).toHaveFocus()
      }

      // Shift+Tab from first should go to last
      await user.tab({ shift: true })
      expect(lastElement).toHaveFocus()
    })

    it('prevents focus from leaving dialog to background elements', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      // Focus a background element first
      const backgroundButton = screen.getByText('Main Content Button')
      backgroundButton.focus()

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Try to focus background elements - should fail
      backgroundButton.focus()

      // Focus should remain in dialog
      const dialog = screen.getByRole('dialog')
      const currentFocus = getFocusedElement()
      expect(dialog.contains(currentFocus)).toBe(true)

      // Try clicking outside dialog
      const backgroundElement = document.querySelector('main')
      if (backgroundElement) {
        backgroundElement.click()
      }

      // Focus should still be in dialog
      expect(dialog.contains(getFocusedElement())).toBe(true)
    })
  })

  describe('Dialog Closing Focus Management', () => {
    it('restores focus to trigger when closed with Escape', async () => {
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

      await user.keyboard('{Escape}')

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(trigger).toHaveFocus()
      })
    })

    it('restores focus to trigger when closed with cancel button', async () => {
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

      await user.click(screen.getByRole('button', { name: /cancel/i }))

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(trigger).toHaveFocus()
      })
    })

    it('restores focus after successful submission', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Focus test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing focus restoration.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Wait for success and close
      await waitFor(() => {
        expect(screen.getByText(/feedback.*submitted.*successfully/i)).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: /close/i }))

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(trigger).toHaveFocus()
      })
    })

    it('handles focus restoration when trigger element is removed', async () => {
      const user = userEvent.setup()

      const { rerender } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Remove the widget while dialog is open
      rerender(
        <TestWrapper>
          <div>Widget removed</div>
        </TestWrapper>
      )

      // Focus should go to a safe fallback (document.body or main content)
      const fallbackElement = document.querySelector('main') || document.body
      expect(document.activeElement).toBe(fallbackElement)
    })
  })

  describe('Form Focus Management', () => {
    it('moves focus to first error field on validation failure', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to submit empty form
      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Focus should move to first required field with error
      await waitFor(() => {
        const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
        expect(firstStar).toHaveFocus()
      })
    })

    it('maintains focus on current field during validation', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.click(titleInput)
      await user.type(titleInput, 'Hi') // Too short, will cause error

      // Focus should remain on title input
      expect(titleInput).toHaveFocus()

      await user.tab() // Trigger validation

      // Error appears but focus moves naturally to next field
      expect(screen.getByText(/title must be at least 5 characters/i)).toBeInTheDocument()

      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      expect(descriptionTextarea).toHaveFocus()
    })

    it('handles focus for dynamic form elements', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Upload screenshot to show remove button
      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot'], 'test.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // Remove button should be focusable
      const removeButton = screen.getByRole('button', { name: /remove.*screenshot/i })
      removeButton.focus()
      expect(removeButton).toHaveFocus()

      // Click remove button
      await user.click(removeButton)

      // Focus should return to file input
      await waitFor(() => {
        expect(fileInput).toHaveFocus()
      })
    })

    it('manages focus in multi-step forms', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget multiStep />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Step 1: Focus should be on first interactive element
      const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
      expect(firstStar).toHaveFocus()

      // Fill step 1
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')

      // Navigate to next step
      const nextButton = screen.getByRole('button', { name: /next/i })
      await user.click(nextButton)

      // Step 2: Focus should move to first field
      await waitFor(() => {
        const titleInput = screen.getByRole('textbox', { name: /title/i })
        expect(titleInput).toHaveFocus()
      })

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Multi-step focus test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing multi-step focus management.')

      // Navigate to final step
      await user.click(screen.getByRole('button', { name: /next/i }))

      // Step 3: Focus should be on submit button
      await waitFor(() => {
        const submitButton = screen.getByRole('button', { name: /submit.*feedback/i })
        expect(submitButton).toHaveFocus()
      })

      // Navigate back
      await user.click(screen.getByRole('button', { name: /back/i }))

      // Should return to first field of step 2
      await waitFor(() => {
        const titleInput = screen.getByRole('textbox', { name: /title/i })
        expect(titleInput).toHaveFocus()
      })
    })
  })

  describe('Error State Focus Management', () => {
    it('maintains focus during error display', async () => {
      const user = userEvent.setup()
      mockFetch.mockRejectedValue(new Error('Network error'))

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[2])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'bug-report')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Error focus test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing error focus management.')

      const submitButton = screen.getByRole('button', { name: /submit/i })
      await user.click(submitButton)

      // Wait for error
      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      // Focus should remain on submit button or move to retry button
      const retryButton = screen.getByRole('button', { name: /retry/i })
      expect(retryButton).toHaveFocus()
    })

    it('focuses retry button after failed submission', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({
          success: false,
          error: 'Server error'
        })
      })

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Server error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing server error focus.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/server error/i)).toBeInTheDocument()
      })

      // Focus should be on retry button
      const retryButton = screen.getByRole('button', { name: /retry/i })
      expect(retryButton).toHaveFocus()
    })
  })

  describe('Success State Focus Management', () => {
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
      await user.selectOptions(categorySelect, 'feature-request')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Success focus test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing success state focus management.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback.*submitted.*successfully/i)).toBeInTheDocument()
      })

      // Focus should be on close button
      const closeButton = screen.getByRole('button', { name: /close/i })
      expect(closeButton).toHaveFocus()
    })

    it('provides additional action focus options in success state', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget showSuccessActions />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'ui-ux')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Success actions test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing success actions focus.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback.*submitted.*successfully/i)).toBeInTheDocument()
      })

      // Should have multiple action buttons
      const submitAnotherButton = screen.getByRole('button', { name: /submit.*another/i })
      const closeButton = screen.getByRole('button', { name: /close/i })

      // Focus should start on primary action (submit another)
      expect(submitAnotherButton).toHaveFocus()

      // Tab to close button
      await user.tab()
      expect(closeButton).toHaveFocus()

      // Tab should cycle back
      await user.tab()
      expect(submitAnotherButton).toHaveFocus()
    })
  })

  describe('Quick Actions Focus Management', () => {
    it('manages focus when quick actions are shown', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        expect(screen.getByText('Report Bug')).toBeInTheDocument()
      })

      // Focus should remain on trigger initially
      expect(trigger).toHaveFocus()

      // Tab to first quick action
      await user.tab()
      expect(screen.getByRole('button', { name: /report bug/i })).toHaveFocus()

      // Continue tabbing through quick actions
      await user.tab()
      expect(screen.getByRole('button', { name: /feature idea/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /ui issue/i })).toHaveFocus()

      await user.tab()
      expect(screen.getByRole('button', { name: /general feedback/i })).toHaveFocus()

      // Tab should cycle back to trigger
      await user.tab()
      expect(trigger).toHaveFocus()
    })

    it('handles quick action selection focus', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Select a quick action
      await user.click(screen.getByRole('button', { name: /report bug/i }))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Focus should be on first form element (stars)
      const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
      expect(firstStar).toHaveFocus()

      // Category should be pre-selected with bug-report
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      expect(categorySelect).toHaveValue('bug-report')
    })
  })

  describe('Performance and Edge Cases', () => {
    it('handles rapid focus changes gracefully', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      // Rapidly open and close dialog
      for (let i = 0; i < 5; i++) {
        await user.click(trigger)

        await waitFor(() => {
          expect(screen.getByRole('dialog')).toBeInTheDocument()
        })

        await user.keyboard('{Escape}')

        await waitFor(() => {
          expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        })
      }

      // Focus should still be properly managed
      expect(trigger).toHaveFocus()
    })

    it('handles focus when multiple dialogs are present', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
          <dialog open data-testid="existing-dialog">
            <h2>Existing Dialog</h2>
            <button>Existing Button</button>
          </dialog>
        </TestWrapper>
      )

      // Existing dialog should not interfere with feedback widget focus
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        expect(screen.getByRole('dialog', { name: /send.*feedback/i })).toBeInTheDocument()
      })

      // Focus should be properly trapped in feedback dialog
      const dialog = screen.getByRole('dialog', { name: /send.*feedback/i })
      const focusedElement = getFocusedElement()
      expect(dialog.contains(focusedElement)).toBe(true)
    })

    it('maintains focus accessibility during animations', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget animationDuration={300} />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      // During animation, focus should still be properly managed
      // Don't wait for animation to complete
      const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
      expect(firstStar).toHaveFocus()

      // Close dialog during animation
      await user.keyboard('{Escape}')

      // Focus should return to trigger even during animation
      await waitFor(() => {
        expect(trigger).toHaveFocus()
      })
    })
  })
})