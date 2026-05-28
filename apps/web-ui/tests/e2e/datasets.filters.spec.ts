import { test, expect } from '@playwright/test'

test.describe('Datasets numeric filters', () => {
  test.setTimeout(180_000)

  test('shows chips + unsupported helper text on /vault/datasets', async ({ page }) => {
    await page.goto('/vault/datasets?tr_min=2', { waitUntil: 'domcontentloaded' })

    await expect(page.getByText('Parsed filters')).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('button', { name: /TR >= 2s/i })).toBeVisible()
    await expect(page.getByText(/1 active/i)).toBeVisible()
    await expect(
      page.getByText(/TR filters are not available in the current (dataset )?catalog\./i)
    ).toBeVisible()
  })

  test('shows chips + unsupported helper text on /finder/datasets', async ({ page }) => {
    await page.goto('/finder/datasets?tr_min=2', { waitUntil: 'domcontentloaded' })

    await expect(page.getByText('Parsed filters')).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('button', { name: /TR >= 2s/i })).toBeVisible()
    await expect(page.getByText(/1 active/i)).toBeVisible()
    await expect(
      page.getByText(/TR filters are not available in the current (dataset )?catalog\./i)
    ).toBeVisible()
  })
})
