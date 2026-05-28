import { test, expect } from '@playwright/test'

const BASE =
  process.env.E2E_BASE_URL ||
  process.env.BASE_URL ||
  'http://localhost:3000'

const EMAIL =
  process.env.E2E_DEV_EMAIL ||
  process.env.DEV_CREDENTIALS_EMAIL ||
  'demo@example.com'

const PASSWORD =
  process.env.E2E_DEV_PASSWORD ||
  process.env.DEV_CREDENTIALS_PASSWORD ||
  'DemoPass123!'

test.describe('Auth login UI', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('login form signs in and redirects', async ({ page }) => {
    await page.goto(`${BASE}/auth/login?callbackUrl=/profile`, {
      waitUntil: 'domcontentloaded',
    })

    const ready = page.locator('[data-auth-ready="true"]')
    await expect(ready).toBeVisible({ timeout: 20_000 })

    await page.getByLabel('Email').fill(EMAIL)
    await page.getByLabel('Password').fill(PASSWORD)

    const submit = page.getByRole('button', { name: /^Sign in$/i })
    await expect(submit).toBeEnabled()
    await submit.click()

    await expect
      .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
      .toBe('/profile')
    await expect(page.getByRole('heading', { name: /Profile/i })).toBeVisible({
      timeout: 30_000,
    })
  })
})
