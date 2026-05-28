import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'

test.describe('Status page empty states', () => {
  test('shows "No data yet" when queue/services are missing', async ({ page }) => {
    await page.route('**/api/health/full', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          services: [],
          timestamp: Math.floor(Date.now() / 1000)
        })
      })
    })

    await page.goto(`${BASE}/status`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'System Status' })).toBeVisible()
    await expect(page.getByText('Job Queue')).toBeVisible()
    await expect(page.getByText('Services')).toBeVisible()
    await expect(page.getByText('No data yet.').first()).toBeVisible()
  })
})
