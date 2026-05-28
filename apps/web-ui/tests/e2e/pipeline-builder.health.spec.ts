import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'

test.describe('Pipeline builder health UI', () => {
  test('shows healthy status without pipeline WS errors', async ({ page }) => {
    const wsErrors: string[] = []
    page.on('console', (msg) => {
      const text = msg.text()
      if (
        msg.type() === 'error' &&
        (text.includes('Pipeline monitoring WebSocket') ||
          text.includes('ws://localhost:3000/dashboard') ||
          text.includes('/dashboard?userId=user-1&userName=Pipeline%20Monitor'))
      ) {
        wsErrors.push(text)
      }
    })

    await page.goto(`${BASE}/pipeline-builder`, { waitUntil: 'domcontentloaded' })

    const emailInput = page.locator('#email')
    if (await emailInput.isVisible().catch(() => false)) {
      const email = process.env.E2E_DEV_EMAIL || process.env.DEV_CREDENTIALS_EMAIL
      const password = process.env.E2E_DEV_PASSWORD || process.env.DEV_CREDENTIALS_PASSWORD
      test.skip(!email || !password, 'Set DEV_CREDENTIALS_EMAIL/DEV_CREDENTIALS_PASSWORD for auth')
      const csrfResponse = await page.request.get(`${BASE}/api/auth/csrf`)
      const csrfData = await csrfResponse.json()
      const csrfToken = csrfData?.csrfToken
      if (!csrfToken) {
        throw new Error('Missing CSRF token for auth flow')
      }
      const authResponse = await page.request.post(`${BASE}/api/auth/callback/credentials`, {
        form: {
          csrfToken,
          email,
          password,
          callbackUrl: `${BASE}/pipeline-builder`,
          json: 'true'
        }
      })
      if (!authResponse.ok()) {
        throw new Error(`Auth failed (${authResponse.status()})`)
      }
      await page.goto(`${BASE}/pipeline-builder`, { waitUntil: 'domcontentloaded' })
    }

    const skipOnboarding = page.getByRole('button', { name: /skip for now/i })
    if (await skipOnboarding.isVisible().catch(() => false)) {
      await skipOnboarding.click()
    }

    await expect(page.getByText('All systems operational')).toBeVisible({ timeout: 30000 })
    await expect(page.getByText('Service issues detected')).toHaveCount(0, { timeout: 30000 })

    await page.waitForTimeout(1500)
    expect(wsErrors).toEqual([])
  })
})
