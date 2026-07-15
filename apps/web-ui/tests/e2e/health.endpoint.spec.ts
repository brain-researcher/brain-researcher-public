import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

const BASE = resolveE2EBaseUrl()

test.describe('Web UI local smoke', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('responds with the Web UI health contract without an auth redirect', async ({ request }) => {
    const resp = await request.get(`${BASE}/health`)
    expect(resp.status()).toBe(200)
    expect(resp.headers()['content-type']).toContain('application/json')
    const json = await resp.json()
    expect(json).toMatchObject({ status: 'ok', service: 'web_ui' })
    expect(json.timestamp).toEqual(expect.any(String))
  })

  test('renders the landing page', async ({ page }) => {
    await page.goto(BASE)
    await expect(page.getByTestId('landing-page')).toBeVisible()
    await expect(
      page.getByRole('heading', { level: 1, name: 'Brain Researcher', exact: true }),
    ).toBeVisible()
  })
})
