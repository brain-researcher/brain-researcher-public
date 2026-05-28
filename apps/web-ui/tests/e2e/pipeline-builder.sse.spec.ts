import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'

test.describe('Pipeline builder SSE', () => {
  test('execution monitor shows durations', async ({ page }) => {
    test.skip(
      !process.env.PIPELINE_SSE,
      'Set PIPELINE_SSE=1 to run pipeline SSE test'
    )

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

    const runButton = page.getByRole('button', { name: /run pipeline/i })
    // This page can be relatively heavy under parallel E2E runs; allow a bit more time.
    await runButton.waitFor({ state: 'visible', timeout: 60000 })

    const sseResponsePromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/jobs/') &&
        resp.url().endsWith('/events') &&
        resp.status() === 200,
      { timeout: 60000 }
    )

    await runButton.click()
    const sseResponse = await sseResponsePromise
    const contentType = sseResponse.headers()['content-type'] || ''
    expect(contentType).toContain('text/event-stream')

    const durationText = page.locator('text=/\\d+ms/')
    await expect(durationText.first()).toBeVisible({ timeout: 20000 })
  })
})
