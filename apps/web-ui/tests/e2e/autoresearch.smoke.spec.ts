import { expect, test } from '@playwright/test'

test.describe('Autoresearch public page', () => {
  test('switches programs, searches topics, and prefills a proposal on desktop', async ({ page }) => {
    await page.context().clearCookies()
    await page.goto('/autoresearch')
    await expect(page).toHaveURL(/\/autoresearch(?:\?|$)/)
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
    await expect(
      page.getByRole('heading', {
        name: "Let's explore and define AI-assisted research together, as a community.",
      }),
    ).toBeVisible()
    await expect(page.getByText(/Selected participants join the BR Autoresearch Consortium/i)).toContainText(
      'co-authors on the consortium paper',
    )

    await page.getByRole('tab', { name: 'BCI' }).click()
    await expect(page.getByRole('heading', { name: 'BCI and neural interfaces' })).toBeVisible()

    await page.getByRole('tab', { name: 'Neuroimaging' }).click()
    await page.getByRole('searchbox', { name: 'Search the source index' }).fill('ADHD')
    await page.getByRole('button', { name: 'ADHD' }).click()
    await page.getByRole('button', { name: 'See source' }).click()
    await expect(page.getByText('Source paper')).toBeVisible()
    await page.getByRole('button', { name: /Use starting question: After recomputing ALFF\/fALFF/i }).click()

    await expect(page.getByLabel('Scientific question')).toHaveValue(/After recomputing ALFF\/fALFF/)
    await expect(page.getByLabel('Research area')).toHaveValue('Neuroimaging and brain measurement')
    await expect(page.getByRole('heading', { name: 'From exploration to experiment.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit proposal' })).toBeEnabled()
    await expect(page.getByRole('status')).toContainText('Your proposal will be sent to the BR team at brainresearcherinitiative@gmail.com through FormSubmit')
    const form = page.locator('form')
    await expect(form).toHaveAttribute('action', 'https://formsubmit.co/brainresearcherinitiative@gmail.com')
    await expect(form.locator('input[name="_subject"]')).toHaveValue('BR Autoresearch proposal')
    await expect(form.locator('input[name="_template"]')).toHaveValue('table')
    await expect(form.locator('input[name="_next"]')).toHaveValue(
      'https://brain-researcher.com/autoresearch?submitted=1',
    )
  })

  test('uses compact navigation and has no horizontal overflow at 320px', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 })
    await page.goto('/autoresearch')

    await expect(page.getByRole('tablist', { name: 'Research programs' })).toBeVisible()
    await page.getByRole('tab', { name: 'BCI' }).click()
    await expect(page.getByLabel('Choose a research direction')).toBeVisible()
    await page.getByRole('tab', { name: 'Neuroimaging' }).click()
    await page.getByRole('searchbox', { name: 'Search the source index' }).fill('ADHD')
    await page.getByLabel('Choose a neuroimaging topic').selectOption('adhd')
    await page.getByRole('button', { name: /Use starting question: After recomputing ALFF\/fALFF/i }).click()
    await expect(page.getByLabel('Scientific question')).toHaveValue(/After recomputing ALFF\/fALFF/)
    await expect(page.getByRole('heading', { name: 'From exploration to experiment.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit proposal' })).toBeEnabled()

    const widths = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))

    expect(widths.scrollWidth).toBeLessThanOrEqual(widths.clientWidth + 1)
  })
})
