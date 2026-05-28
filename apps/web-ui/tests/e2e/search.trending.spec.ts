import { test, expect } from '@playwright/test'

const BASE =
  process.env.E2E_BASE_URL ??
  process.env.BASE_URL ??
  'http://localhost:3000'

test.describe('Search trending', () => {
  test('trending list populates from /api/search/track', async ({ page }) => {
    const query = `pw-trending-${Date.now()}-${Math.random().toString(16).slice(2)}`

    // Boost the query so it reliably shows up in the top-3 trending list.
    for (let i = 0; i < 10; i += 1) {
      const resp = await page.request.post(
        `${BASE}/api/search/track?query=${encodeURIComponent(query)}`,
        { timeout: 10_000 }
      )
      expect(resp.ok()).toBeTruthy()
    }

    // Ensure the UI shows Trending (it hides Trending when local history exists).
    await page.addInitScript(() => {
      localStorage.removeItem('searchHistory')
    })

    await page.goto(`${BASE}/vault/datasets`, { waitUntil: 'domcontentloaded' })

    const headerSearch = page.locator('[data-tour="search"] input')
    await expect(headerSearch).toBeVisible()
    await headerSearch.click()

    await expect(page.getByText(query)).toBeVisible({ timeout: 20_000 })
  })
})
