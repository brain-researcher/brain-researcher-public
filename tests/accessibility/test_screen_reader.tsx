/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackWidget } from '@/components/feedback/FeedbackWidget'
import { FeedbackProvider } from '@/contexts/FeedbackContext'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { axe, toHaveNoViolations } from 'jest-axe'
import '@testing-library/jest-dom'

// Extend Jest matchers
expect.extend(toHaveNoViolations)

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
        {children}
      </FeedbackProvider>
    </QueryClientProvider>
  )
}

describe('Feedback Widget Screen Reader Accessibility', () => {
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

  describe('ARIA Attributes and Labels', () => {
    it('has proper ARIA attributes on trigger button', () => {
      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })

      expect(trigger).toHaveAttribute('aria-label', 'Open feedback menu')
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
      expect(trigger).toHaveAttribute('type', 'button')
    })

    it('updates ARIA attributes when quick actions are shown', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const trigger = screen.getByRole('button', { name: /feedback menu/i })
      await user.click(trigger)

      await waitFor(() => {
        expect(trigger).toHaveAttribute('aria-expanded', 'true')
        expect(trigger).toHaveAttribute('aria-controls', expect.stringContaining('menu'))
      })
    })

    it('has proper dialog ARIA attributes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        const dialog = screen.getByRole('dialog')

        expect(dialog).toHaveAttribute('aria-modal', 'true')
        expect(dialog).toHaveAttribute('aria-labelledby', expect.stringContaining('title'))
        expect(dialog).toHaveAttribute('aria-describedby', expect.stringContaining('description'))
      })

      const title = screen.getByRole('heading', { level: 2 })
      expect(title).toBeInTheDocument()

      const description = screen.getByText(/share your thoughts/i)
      expect(description).toBeInTheDocument()
    })

    it('has proper form field ARIA attributes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Rating section
      const ratingGroup = screen.getByRole('group', { name: /overall rating/i })
      expect(ratingGroup).toHaveAttribute('aria-describedby', expect.stringContaining('rating-help'))

      const stars = screen.getAllByRole('button', { name: /star/i })
      stars.forEach((star, index) => {
        expect(star).toHaveAttribute('aria-label', `${index + 1} star`)
        expect(star).toHaveAttribute('aria-pressed', 'false')
      })

      // Category field
      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      expect(categorySelect).toHaveAttribute('aria-required', 'true')
      expect(categorySelect).toHaveAttribute('aria-describedby', expect.stringContaining('category-help'))

      // Text fields
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      expect(titleInput).toHaveAttribute('aria-required', 'true')
      expect(titleInput).toHaveAttribute('aria-describedby', expect.stringContaining('title-help'))

      const descriptionTextarea = screen.getByRole('textbox', { name: /description/i })
      expect(descriptionTextarea).toHaveAttribute('aria-required', 'true')
      expect(descriptionTextarea).toHaveAttribute('aria-describedby', expect.stringContaining('description-help'))

      // Screenshot section
      const fileInput = screen.getByLabelText(/screenshot/i)
      expect(fileInput).toHaveAttribute('aria-describedby', expect.stringContaining('screenshot-help'))
      expect(fileInput).toHaveAttribute('accept', 'image/*')
    })

    it('has proper ARIA attributes for validation errors', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Try to submit invalid form
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.type(titleInput, 'Hi') // Too short
      await user.tab() // Trigger validation

      // Error should be associated with field
      const errorMessage = screen.getByText(/title must be at least 5 characters/i)
      expect(errorMessage).toHaveAttribute('role', 'alert')
      expect(errorMessage).toHaveAttribute('aria-live', 'polite')

      const errorId = errorMessage.getAttribute('id')
      expect(titleInput).toHaveAttribute('aria-describedby', expect.stringContaining(errorId))
      expect(titleInput).toHaveAttribute('aria-invalid', 'true')
    })
  })

  describe('Live Regions and Announcements', () => {
    it('announces rating changes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Click on rating
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      // Should have live announcement
      const announcement = screen.getByRole('status')
      expect(announcement).toHaveTextContent('4 stars selected')
      expect(announcement).toHaveAttribute('aria-live', 'polite')
    })

    it('announces emoji rating changes', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Click on emoji
      await user.click(screen.getByRole('button', { name: /happy/i }))

      // Should announce emoji selection
      const announcement = screen.getByRole('status')
      expect(announcement).toHaveTextContent(/happy.*selected/i)
    })

    it('announces form submission status', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill form
      await user.click(screen.getAllByRole('button', { name: /star/i })[4])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Screen reader test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing screen reader announcements.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should announce submission started
      let announcement = screen.getByRole('status')
      expect(announcement).toHaveTextContent(/submitting.*feedback/i)

      // Should announce success
      await waitFor(() => {
        announcement = screen.getByRole('status')
        expect(announcement).toHaveTextContent(/feedback.*submitted.*successfully/i)
      })
    })

    it('announces error states', async () => {
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

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Error test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing error announcements.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      // Should announce error
      await waitFor(() => {
        const errorAlert = screen.getByRole('alert')
        expect(errorAlert).toHaveTextContent(/failed.*submit.*feedback/i)
      })
    })

    it('announces screenshot upload status', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Upload screenshot
      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot'], 'test.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // Should announce upload success
      const announcement = screen.getByRole('status')
      expect(announcement).toHaveTextContent(/screenshot.*uploaded.*successfully/i)
    })
  })

  describe('Semantic HTML Structure', () => {
    it('uses proper heading hierarchy', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Dialog should have h2 title
      const dialogTitle = screen.getByRole('heading', { level: 2 })
      expect(dialogTitle).toHaveTextContent(/send.*feedback/i)

      // Sections should have h3 headings
      const sectionHeadings = screen.getAllByRole('heading', { level: 3 })
      expect(sectionHeadings.length).toBeGreaterThan(0)

      const headingTexts = sectionHeadings.map(h => h.textContent?.toLowerCase())
      expect(headingTexts).toEqual(expect.arrayContaining([
        expect.stringContaining('rating'),
        expect.stringContaining('category'),
        expect.stringContaining('details'),
        expect.stringContaining('screenshot')
      ]))
    })

    it('uses proper form structure', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Should have form element
      const form = screen.getByRole('form')
      expect(form).toBeInTheDocument()

      // Should have fieldsets for logical grouping
      const fieldsets = screen.getAllByRole('group')
      expect(fieldsets.length).toBeGreaterThan(0)

      // Each fieldset should have legend
      fieldsets.forEach(fieldset => {
        const legend = fieldset.querySelector('legend')
        expect(legend).toBeInTheDocument()
      })
    })

    it('uses proper list structure for options', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Quick actions should be in a list
      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        const quickActionsList = screen.getByRole('menu')
        expect(quickActionsList).toBeInTheDocument()

        const quickActionItems = screen.getAllByRole('menuitem')
        expect(quickActionItems.length).toBeGreaterThan(0)
      })
    })
  })

  describe('Screen Reader Instructions', () => {
    it('provides helpful instructions for star rating', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const ratingInstructions = screen.getById(expect.stringContaining('rating-help'))
      expect(ratingInstructions).toHaveTextContent(/use arrow keys to navigate.*space or enter to select/i)
    })

    it('provides category selection guidance', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const categoryHelp = screen.getById(expect.stringContaining('category-help'))
      expect(categoryHelp).toHaveTextContent(/choose the category that best describes your feedback/i)
    })

    it('provides form completion guidance', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const formInstructions = screen.getByText(/required fields are marked with an asterisk/i)
      expect(formInstructions).toBeInTheDocument()
      expect(formInstructions).toHaveAttribute('aria-live', 'polite')
    })

    it('provides screenshot upload instructions', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      const screenshotHelp = screen.getById(expect.stringContaining('screenshot-help'))
      expect(screenshotHelp).toHaveTextContent(/optional.*upload.*image.*png.*jpg.*gif.*5mb/i)
    })
  })

  describe('Focus Management', () => {
    it('announces focus changes appropriately', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Focus on first interactive element
      const firstStar = screen.getAllByRole('button', { name: /star/i })[0]
      firstStar.focus()

      // Should have focus announcement
      expect(firstStar).toHaveAttribute('aria-label', '1 star')

      // Move focus and verify announcement
      await user.tab()
      const happyEmoji = screen.getByRole('button', { name: /very.*happy/i })
      expect(happyEmoji).toHaveFocus()
      expect(happyEmoji).toHaveAttribute('aria-label', expect.stringContaining('very happy'))
    })

    it('manages focus for dynamic content', async () => {
      const user = userEvent.setup()

      render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Upload screenshot to show dynamic content
      const fileInput = screen.getByLabelText(/screenshot/i)
      const mockFile = new File(['screenshot'], 'test.png', { type: 'image/png' })
      await user.upload(fileInput, mockFile)

      // Remove button should be properly announced when focused
      const removeButton = screen.getByRole('button', { name: /remove.*screenshot/i })
      removeButton.focus()

      expect(removeButton).toHaveAttribute('aria-label', 'Remove screenshot test.png')
      expect(removeButton).toHaveAttribute('aria-describedby', expect.stringContaining('remove-help'))
    })
  })

  describe('Accessible Notifications', () => {
    it('provides accessible success notifications', async () => {
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
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Success notification test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing accessible success notifications.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        const successMessage = screen.getByRole('alert')
        expect(successMessage).toHaveTextContent(/feedback.*submitted.*successfully/i)
        expect(successMessage).toHaveAttribute('aria-live', 'assertive')
      })

      // Success dialog should have proper focus
      const closeButton = screen.getByRole('button', { name: /close/i })
      expect(closeButton).toHaveFocus()
      expect(closeButton).toHaveAttribute('aria-label', 'Close feedback confirmation')
    })

    it('provides accessible error notifications', async () => {
      const user = userEvent.setup()
      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        json: () => Promise.resolve({
          success: false,
          error: 'Validation failed',
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

      // Submit invalid form
      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        const errorAlert = screen.getByRole('alert')
        expect(errorAlert).toHaveTextContent(/validation failed/i)
        expect(errorAlert).toHaveAttribute('aria-live', 'assertive')
      })

      // Field-specific errors should be properly associated
      const titleError = screen.getByText('Title is required')
      expect(titleError).toHaveAttribute('role', 'alert')

      const titleInput = screen.getByRole('textbox', { name: /title/i })
      expect(titleInput).toHaveAttribute('aria-invalid', 'true')
      expect(titleInput).toHaveAttribute('aria-describedby', expect.stringContaining(titleError.id))
    })
  })

  describe('Axe Accessibility Testing', () => {
    it('passes accessibility audit for closed widget', async () => {
      const { container } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      const results = await axe(container)
      expect(results).toHaveNoViolations()
    })

    it('passes accessibility audit for open dialog', async () => {
      const user = userEvent.setup()

      const { container } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      const results = await axe(container)
      expect(results).toHaveNoViolations()
    })

    it('passes accessibility audit with form errors', async () => {
      const user = userEvent.setup()

      const { container } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Create validation errors
      const titleInput = screen.getByRole('textbox', { name: /title/i })
      await user.type(titleInput, 'Hi')
      await user.tab()

      await waitFor(() => {
        expect(screen.getByText(/title must be at least 5 characters/i)).toBeInTheDocument()
      })

      const results = await axe(container)
      expect(results).toHaveNoViolations()
    })

    it('passes accessibility audit for success state', async () => {
      const user = userEvent.setup()

      const { container } = render(
        <TestWrapper>
          <FeedbackWidget />
        </TestWrapper>
      )

      await user.click(screen.getByRole('button', { name: /feedback menu/i }))

      // Fill and submit form
      await user.click(screen.getAllByRole('button', { name: /star/i })[3])

      const categorySelect = screen.getByRole('combobox', { name: /category/i })
      await user.selectOptions(categorySelect, 'other')

      await user.type(screen.getByRole('textbox', { name: /title/i }), 'Accessibility test')
      await user.type(screen.getByRole('textbox', { name: /description/i }), 'Testing accessibility compliance.')

      await user.click(screen.getByRole('button', { name: /submit/i }))

      await waitFor(() => {
        expect(screen.getByText(/feedback.*submitted.*successfully/i)).toBeInTheDocument()
      })

      const results = await axe(container)
      expect(results).toHaveNoViolations()
    })
  })
})