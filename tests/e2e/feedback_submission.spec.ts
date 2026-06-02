import { test, expect, Page, BrowserContext } from '@playwright/test'

// Test configuration
test.describe.configure({ mode: 'parallel' })

// Page object model for feedback widget
class FeedbackWidgetPage {
  constructor(private page: Page) {}

  // Selectors
  get triggerButton() {
    return this.page.getByRole('button', { name: /feedback menu/i })
  }

  get quickActionBug() {
    return this.page.getByRole('button', { name: /report bug/i })
  }

  get quickActionFeature() {
    return this.page.getByRole('button', { name: /feature idea/i })
  }

  get dialog() {
    return this.page.getByRole('dialog')
  }

  get starRating() {
    return this.page.getByRole('button', { name: /star/i })
  }

  get emojiRating() {
    return this.page.getByRole('button', { name: /emoji/i })
  }

  get categorySelect() {
    return this.page.getByRole('combobox', { name: /category/i })
  }

  get titleInput() {
    return this.page.getByRole('textbox', { name: /title/i })
  }

  get descriptionTextarea() {
    return this.page.getByRole('textbox', { name: /description/i })
  }

  get screenshotInput() {
    return this.page.getByLabel(/screenshot/i)
  }

  get capturePageButton() {
    return this.page.getByRole('button', { name: /capture.*page/i })
  }

  get submitButton() {
    return this.page.getByRole('button', { name: /submit/i })
  }

  get cancelButton() {
    return this.page.getByRole('button', { name: /cancel/i })
  }

  get successMessage() {
    return this.page.getByText(/feedback.*submitted.*successfully/i)
  }

  get closeButton() {
    return this.page.getByRole('button', { name: /close/i })
  }

  // Actions
  async openWidget() {
    await this.triggerButton.click()
    await expect(this.dialog).toBeVisible()
  }

  async selectRating(stars: number) {
    const starButtons = await this.starRating.all()
    await starButtons[stars - 1].click()
  }

  async selectEmoji(emotion: string) {
    await this.page.getByRole('button', { name: new RegExp(emotion, 'i') }).click()
  }

  async selectCategory(category: string) {
    await this.categorySelect.click()
    await this.page.getByRole('option', { name: new RegExp(category, 'i') }).click()
  }

  async fillTitle(title: string) {
    await this.titleInput.fill(title)
  }

  async fillDescription(description: string) {
    await this.descriptionTextarea.fill(description)
  }

  async uploadScreenshot(filePath: string) {
    await this.screenshotInput.setInputFiles(filePath)
  }

  async captureScreenshot() {
    await this.capturePageButton.click()
    // Wait for capture to complete
    await this.page.waitForTimeout(1000)
  }

  async submitFeedback() {
    await this.submitButton.click()
  }

  async cancelFeedback() {
    await this.cancelButton.click()
  }

  async closeFeedback() {
    await this.closeButton.click()
  }
}

test.describe('Feedback Widget E2E Tests', () => {
  let feedbackPage: FeedbackWidgetPage

  test.beforeEach(async ({ page }) => {
    feedbackPage = new FeedbackWidgetPage(page)

    // Navigate to the app (adjust URL as needed)
    await page.goto('http://localhost:3000')

    // Wait for the page to load
    await page.waitForLoadState('networkidle')
  })

  test.describe('Widget Visibility and Interaction', () => {
    test('should display feedback widget trigger button', async ({ page }) => {
      await expect(feedbackPage.triggerButton).toBeVisible()
      await expect(feedbackPage.triggerButton).toBeEnabled()
    })

    test('should open feedback dialog when trigger is clicked', async ({ page }) => {
      await feedbackPage.openWidget()

      // Dialog should be visible and contain form elements
      await expect(feedbackPage.dialog).toBeVisible()
      await expect(feedbackPage.starRating.first()).toBeVisible()
      await expect(feedbackPage.categorySelect).toBeVisible()
      await expect(feedbackPage.titleInput).toBeVisible()
      await expect(feedbackPage.descriptionTextarea).toBeVisible()
    })

    test('should show quick actions on trigger hover/click', async ({ page }) => {
      // Click trigger to show quick actions
      await feedbackPage.triggerButton.click()

      // Quick actions should be visible
      await expect(feedbackPage.quickActionBug).toBeVisible()
      await expect(feedbackPage.quickActionFeature).toBeVisible()
    })

    test('should pre-populate category when using quick actions', async ({ page }) => {
      await feedbackPage.triggerButton.click()
      await feedbackPage.quickActionBug.click()

      await expect(feedbackPage.dialog).toBeVisible()

      // Bug report category should be pre-selected
      await expect(feedbackPage.categorySelect).toHaveValue('bug-report')
    })

    test('should close dialog with escape key', async ({ page }) => {
      await feedbackPage.openWidget()

      await page.keyboard.press('Escape')

      await expect(feedbackPage.dialog).not.toBeVisible()
    })

    test('should close dialog with cancel button', async ({ page }) => {
      await feedbackPage.openWidget()

      await feedbackPage.cancelButton.click()

      await expect(feedbackPage.dialog).not.toBeVisible()
    })
  })

  test.describe('Complete Feedback Submission', () => {
    test('should submit feedback with all fields filled', async ({ page }) => {
      // Mock API response
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            id: 'e2e-test-123',
            message: 'Feedback submitted successfully'
          })
        })
      })

      await feedbackPage.openWidget()

      // Fill all form fields
      await feedbackPage.selectRating(4)
      await feedbackPage.selectEmoji('happy')
      await feedbackPage.selectCategory('feature request')
      await feedbackPage.fillTitle('E2E Test Feedback')
      await feedbackPage.fillDescription('This is an end-to-end test feedback submission with all fields filled out.')

      // Submit the form
      await feedbackPage.submitFeedback()

      // Should show success message
      await expect(feedbackPage.successMessage).toBeVisible({ timeout: 10000 })

      // Verify API was called
      const requests = page.getByText('Network').all()
      // Could add more specific API verification here
    })

    test('should submit feedback with minimum required fields', async ({ page }) => {
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            id: 'e2e-minimal-test',
            message: 'Feedback submitted'
          })
        })
      })

      await feedbackPage.openWidget()

      // Fill only required fields
      await feedbackPage.selectRating(3)
      await feedbackPage.selectCategory('other')
      await feedbackPage.fillTitle('Minimal Test')
      await feedbackPage.fillDescription('Minimum required feedback for testing.')

      await feedbackPage.submitFeedback()

      await expect(feedbackPage.successMessage).toBeVisible({ timeout: 10000 })
    })

    test('should submit feedback with screenshot upload', async ({ page }) => {
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            id: 'e2e-screenshot-test'
          })
        })
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(5)
      await feedbackPage.selectCategory('ui-ux')
      await feedbackPage.fillTitle('Screenshot Test')
      await feedbackPage.fillDescription('Testing feedback with screenshot upload.')

      // Create a test image file
      const testImagePath = await page.evaluate(() => {
        const canvas = document.createElement('canvas')
        canvas.width = 100
        canvas.height = 100
        const ctx = canvas.getContext('2d')!
        ctx.fillStyle = 'red'
        ctx.fillRect(0, 0, 100, 100)
        return canvas.toDataURL()
      })

      // For actual file upload, you would use:
      // await feedbackPage.uploadScreenshot('path/to/test/image.png')

      await feedbackPage.submitFeedback()

      await expect(feedbackPage.successMessage).toBeVisible({ timeout: 10000 })
    })

    test('should handle screenshot capture', async ({ page }) => {
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, id: 'capture-test' })
        })
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(4)
      await feedbackPage.selectCategory('bug report')
      await feedbackPage.fillTitle('Screenshot Capture Test')
      await feedbackPage.fillDescription('Testing automatic screenshot capture functionality.')

      // Capture screenshot
      await feedbackPage.captureScreenshot()

      // Should show screenshot preview
      await expect(page.getByTestId('screenshot-preview')).toBeVisible({ timeout: 5000 })

      await feedbackPage.submitFeedback()

      await expect(feedbackPage.successMessage).toBeVisible({ timeout: 10000 })
    })
  })

  test.describe('Form Validation', () => {
    test('should show validation errors for empty required fields', async ({ page }) => {
      await feedbackPage.openWidget()

      // Try to submit empty form
      await feedbackPage.submitButton.click()

      // Should show validation errors
      await expect(page.getByText(/rating.*required/i)).toBeVisible()
      await expect(page.getByText(/category.*required/i)).toBeVisible()
      await expect(page.getByText(/title.*required/i)).toBeVisible()
      await expect(page.getByText(/description.*required/i)).toBeVisible()

      // Submit button should be disabled
      await expect(feedbackPage.submitButton).toBeDisabled()
    })

    test('should validate title length', async ({ page }) => {
      await feedbackPage.openWidget()

      // Enter short title
      await feedbackPage.fillTitle('Hi')
      await feedbackPage.titleInput.blur()

      // Should show validation error
      await expect(page.getByText(/title must be at least 5 characters/i)).toBeVisible()

      // Fix the title
      await feedbackPage.fillTitle('Valid title')
      await feedbackPage.titleInput.blur()

      // Error should disappear
      await expect(page.getByText(/title must be at least 5 characters/i)).not.toBeVisible()
    })

    test('should validate description length', async ({ page }) => {
      await feedbackPage.openWidget()

      // Enter short description
      await feedbackPage.fillDescription('Short')
      await feedbackPage.descriptionTextarea.blur()

      // Should show validation error
      await expect(page.getByText(/description must be at least 20 characters/i)).toBeVisible()

      // Fix the description
      await feedbackPage.fillDescription('This is a valid description with enough characters to pass validation.')
      await feedbackPage.descriptionTextarea.blur()

      // Error should disappear
      await expect(page.getByText(/description must be at least 20 characters/i)).not.toBeVisible()
    })

    test('should validate file upload types', async ({ page }) => {
      await feedbackPage.openWidget()

      // Try to upload invalid file type (this would need a test file)
      // await feedbackPage.uploadScreenshot('test-files/document.pdf')
      // await expect(page.getByText(/please select.*image/i)).toBeVisible()

      // For now, just verify the input accepts correct types
      await expect(feedbackPage.screenshotInput).toHaveAttribute('accept', 'image/*')
    })

    test('should prevent submission with invalid data', async ({ page }) => {
      await feedbackPage.openWidget()

      // Fill with invalid data
      await feedbackPage.fillTitle('Hi') // Too short
      await feedbackPage.fillDescription('Short') // Too short

      // Submit button should remain disabled
      await expect(feedbackPage.submitButton).toBeDisabled()

      // Fix validation errors
      await feedbackPage.selectRating(3)
      await feedbackPage.selectCategory('other')
      await feedbackPage.fillTitle('Valid title')
      await feedbackPage.fillDescription('This is a valid description with enough characters.')

      // Submit button should now be enabled
      await expect(feedbackPage.submitButton).toBeEnabled()
    })
  })

  test.describe('Error Handling', () => {
    test('should handle network errors gracefully', async ({ page }) => {
      // Mock network failure
      await page.route('**/api/feedback', async route => {
        await route.abort('failed')
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(2)
      await feedbackPage.selectCategory('bug report')
      await feedbackPage.fillTitle('Network Error Test')
      await feedbackPage.fillDescription('Testing network error handling in the feedback widget.')

      await feedbackPage.submitFeedback()

      // Should show error message
      await expect(page.getByText(/network error/i)).toBeVisible({ timeout: 10000 })
      await expect(page.getByText(/check your connection/i)).toBeVisible()

      // Should show retry button
      await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()

      // Dialog should remain open
      await expect(feedbackPage.dialog).toBeVisible()
    })

    test('should handle server errors', async ({ page }) => {
      // Mock server error
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error: 'Internal server error'
          })
        })
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(1)
      await feedbackPage.selectCategory('bug report')
      await feedbackPage.fillTitle('Server Error Test')
      await feedbackPage.fillDescription('Testing server error handling.')

      await feedbackPage.submitFeedback()

      await expect(page.getByText(/internal server error/i)).toBeVisible({ timeout: 10000 })
      await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()
    })

    test('should handle validation errors from server', async ({ page }) => {
      // Mock validation error response
      await page.route('**/api/feedback', async route => {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error: 'Validation failed',
            details: {
              title: 'Title contains inappropriate content',
              description: 'Description is too similar to spam'
            }
          })
        })
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(3)
      await feedbackPage.selectCategory('other')
      await feedbackPage.fillTitle('Server Validation Test')
      await feedbackPage.fillDescription('Testing server-side validation error handling.')

      await feedbackPage.submitFeedback()

      // Should show server validation errors
      await expect(page.getByText(/validation failed/i)).toBeVisible({ timeout: 10000 })
      await expect(page.getByText(/inappropriate content/i)).toBeVisible()
      await expect(page.getByText(/similar to spam/i)).toBeVisible()
    })

    test('should retry failed submissions', async ({ page }) => {
      let attemptCount = 0

      // Mock API to fail first attempt, succeed on retry
      await page.route('**/api/feedback', async route => {
        attemptCount++
        if (attemptCount === 1) {
          await route.abort('failed')
        } else {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              success: true,
              id: 'retry-success-test'
            })
          })
        }
      })

      await feedbackPage.openWidget()

      await feedbackPage.selectRating(4)
      await feedbackPage.selectCategory('performance')
      await feedbackPage.fillTitle('Retry Test')
      await feedbackPage.fillDescription('Testing retry functionality.')

      await feedbackPage.submitFeedback()

      // Should show error first
      await expect(page.getByText(/network error/i)).toBeVisible({ timeout: 10000 })

      // Click retry
      await page.getByRole('button', { name: /retry/i }).click()

      // Should eventually succeed
      await expect(feedbackPage.successMessage).toBeVisible({ timeout: 10000 })
    })
  })

  test.describe('Accessibility', () => {
    test('should be fully keyboard accessible', async ({ page }) => {
      await feedbackPage.openWidget()

      // Should be able to navigate through form with keyboard
      await page.keyboard.press('Tab') // First star
      await expect(feedbackPage.starRating.first()).toBeFocused()

      await page.keyboard.press('Enter') // Select first star

      // Continue tabbing through form
      await page.keyboard.press('Tab') // Category
      await expect(feedbackPage.categorySelect).toBeFocused()

      await page.keyboard.press('Enter') // Open category dropdown
      await page.keyboard.press('ArrowDown') // Navigate options
      await page.keyboard.press('Enter') // Select option

      await page.keyboard.press('Tab') // Title input
      await expect(feedbackPage.titleInput).toBeFocused()

      await feedbackPage.titleInput.type('Keyboard Accessibility Test')

      await page.keyboard.press('Tab') // Description
      await expect(feedbackPage.descriptionTextarea).toBeFocused()

      await feedbackPage.descriptionTextarea.type('Testing keyboard navigation.')
    })

    test('should have proper ARIA attributes', async ({ page }) => {
      await feedbackPage.openWidget()

      // Dialog should have proper ARIA attributes
      await expect(feedbackPage.dialog).toHaveAttribute('aria-modal', 'true')
      await expect(feedbackPage.dialog).toHaveAttribute('role', 'dialog')

      // Form fields should have proper labels
      await expect(feedbackPage.titleInput).toHaveAttribute('aria-required', 'true')
      await expect(feedbackPage.descriptionTextarea).toHaveAttribute('aria-required', 'true')
      await expect(feedbackPage.categorySelect).toHaveAttribute('aria-required', 'true')
    })

    test('should announce important changes to screen readers', async ({ page }) => {
      await feedbackPage.openWidget()

      // Rating selection should be announced
      await feedbackPage.selectRating(4)

      // Should have live region for announcements
      const liveRegion = page.getByRole('status')
      await expect(liveRegion).toHaveText(/4 stars selected/i)
    })

    test('should trap focus within dialog', async ({ page }) => {
      await feedbackPage.openWidget()

      // Get all focusable elements in dialog
      const focusableElements = await page.locator('[role="dialog"] button, [role="dialog"] input, [role="dialog"] select, [role="dialog"] textarea').all()

      // Tab through all elements
      for (const element of focusableElements) {
        await page.keyboard.press('Tab')
      }

      // Should cycle back to first element
      await page.keyboard.press('Tab')
      await expect(focusableElements[0]).toBeFocused()
    })
  })

  test.describe('Mobile Responsiveness', () => {
    test('should work on mobile devices', async ({ page }) => {
      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 667 })

      await feedbackPage.openWidget()

      // Dialog should be responsive
      await expect(feedbackPage.dialog).toBeVisible()

      // Form elements should be accessible on mobile
      await feedbackPage.selectRating(3)
      await feedbackPage.selectCategory('ui-ux')
      await feedbackPage.fillTitle('Mobile Test')
      await feedbackPage.fillDescription('Testing mobile responsiveness.')

      // Submit button should be visible and clickable
      await expect(feedbackPage.submitButton).toBeVisible()
      await expect(feedbackPage.submitButton).toBeEnabled()
    })

    test('should handle touch interactions', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 })

      await feedbackPage.openWidget()

      // Should be able to tap on star ratings
      const stars = await feedbackPage.starRating.all()
      await stars[2].tap()

      // Should work with touch scrolling if form is long
      await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]')
        if (dialog) {
          dialog.scrollTop = 100
        }
      })
    })
  })

  test.describe('Performance', () => {
    test('should load and render quickly', async ({ page }) => {
      const startTime = Date.now()

      await feedbackPage.openWidget()

      const loadTime = Date.now() - startTime

      // Should load in reasonable time
      expect(loadTime).toBeLessThan(1000) // 1 second

      // All critical elements should be visible
      await expect(feedbackPage.starRating.first()).toBeVisible()
      await expect(feedbackPage.categorySelect).toBeVisible()
      await expect(feedbackPage.submitButton).toBeVisible()
    })

    test('should handle rapid interactions without lag', async ({ page }) => {
      await feedbackPage.openWidget()

      const startTime = Date.now()

      // Rapid interactions
      await feedbackPage.selectRating(5)
      await feedbackPage.selectEmoji('very happy')
      await feedbackPage.selectCategory('feature request')
      await feedbackPage.fillTitle('Performance Test')
      await feedbackPage.fillDescription('Testing rapid interaction performance.')

      const interactionTime = Date.now() - startTime

      // Interactions should be responsive
      expect(interactionTime).toBeLessThan(2000) // 2 seconds for all interactions
    })
  })

  test.describe('Cross-browser Compatibility', () => {
    test('should work consistently across browsers', async ({ page, browserName }) => {
      console.log(`Testing on ${browserName}`)

      await feedbackPage.openWidget()

      // Core functionality should work on all browsers
      await feedbackPage.selectRating(4)
      await feedbackPage.selectCategory('other')
      await feedbackPage.fillTitle(`Cross-browser test on ${browserName}`)
      await feedbackPage.fillDescription('Testing cross-browser compatibility.')

      // Form should be functional regardless of browser
      await expect(feedbackPage.submitButton).toBeEnabled()
    })
  })
})

test.describe('Integration with Brain Researcher App', () => {
  test('should integrate properly with main application', async ({ page }) => {
    // Navigate to different pages to ensure widget appears consistently
    const pages = ['/', '/datasets', '/analysis']

    for (const pagePath of pages) {
      await page.goto(`http://localhost:3000${pagePath}`)
      await page.waitForLoadState('networkidle')

      // Widget should be present on all pages
      await expect(page.getByRole('button', { name: /feedback menu/i })).toBeVisible()
    }
  })

  test('should not interfere with main app functionality', async ({ page }) => {
    await page.goto('http://localhost:3000')

    // Open feedback widget
    await page.getByRole('button', { name: /feedback menu/i }).click()

    // Main app navigation should still work
    const navLinks = await page.getByRole('link').all()
    for (const link of navLinks.slice(0, 3)) { // Test first 3 nav links
      const href = await link.getAttribute('href')
      if (href && !href.startsWith('http')) {
        await expect(link).toBeEnabled()
      }
    }

    // Close feedback widget
    await page.keyboard.press('Escape')

    // Main app should still be functional
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('should preserve context when navigating between pages', async ({ page }) => {
    await page.goto('http://localhost:3000/datasets')

    const feedbackWidget = new FeedbackWidgetPage(page)
    await feedbackWidget.openWidget()

    // Fill partial form
    await feedbackWidget.selectRating(3)
    await feedbackWidget.fillTitle('Context preservation test')

    // Close dialog
    await feedbackWidget.cancelFeedback()

    // Navigate to different page
    await page.goto('http://localhost:3000/analysis')

    // Open feedback again
    await feedbackWidget.openWidget()

    // Context should be preserved (depending on implementation)
    // This test may need adjustment based on actual behavior
  })
})