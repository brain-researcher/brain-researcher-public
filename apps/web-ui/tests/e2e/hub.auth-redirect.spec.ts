import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

const BASE = resolveE2EBaseUrl()

test.describe('Hub auth redirects', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('hub route redirects to auth gate with callbackUrl', async ({ page }) => {
    await page.goto(`${BASE}/hub`, { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/auth\/login\?callbackUrl=%2Fhub(?:$|&)/, {
      timeout: 30_000,
    })
    await expect(
      page.getByRole('heading', { name: /Sign in to your account/i }),
    ).toBeVisible()
  })

  test('legacy /login redirects into /auth/login and preserves redirect target', async ({
    page,
  }) => {
    await page.goto(`${BASE}/login?redirect=%2Fhub`, {
      waitUntil: 'domcontentloaded',
    })
    await expect(page).toHaveURL(/\/auth\/login\?callbackUrl=%2Fhub(?:$|&)/, {
      timeout: 30_000,
    })
    await expect(
      page.getByRole('heading', { name: /Sign in to your account/i }),
    ).toBeVisible()
  })
})
