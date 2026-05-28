import { test, expect } from '@playwright/test'

test.describe('viz demo endpoints', () => {
  test('base endpoint reflects query filename', async ({ request }) => {
    const response = await request.get('/api/viz/demo/base?filename=e2e_base_map.nii.gz')
    expect(response.status()).toBe(200)
    const cd = response.headers()['content-disposition'] || ''
    expect(cd).toMatch(/filename=.*e2e_base_map\.nii\.gz/i)
    const body = await response.body()
    expect(body.byteLength).toBeGreaterThan(0)
  })

  test('overlay endpoint provides default name when missing', async ({ request }) => {
    const response = await request.get('/api/viz/demo/overlay')
    expect(response.status()).toBe(200)
    const cd = response.headers()['content-disposition'] || ''
    expect(cd).toMatch(/filename=.*\.(nii(\.gz)?|mgz|mgh)/i)
  })
})
