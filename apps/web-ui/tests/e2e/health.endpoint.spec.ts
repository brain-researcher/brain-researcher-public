import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'

test.describe('Web UI health endpoint', () => {
  test('responds 200 JSON without auth redirect', async ({ page }) => {
    const resp = await page.request.get(`${BASE}/health`)
    expect(resp.ok()).toBeTruthy()
    const json = await resp.json()
    expect(json?.status).toBe('ok')
    expect(json?.service).toBe('web_ui')
  })
})
