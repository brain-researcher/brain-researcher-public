import { describe, it, expect } from 'vitest'

describe('API Routes: Demo analysis', () => {
  it('returns demo_disabled for demo analysis route', async () => {
    const { GET } = await import('@/app/api/demo/analysis/[demoId]/route')
    const res = await GET()

    expect(res.status).toBe(410)
    const data = await res.json()
    expect(data.error).toBe('demo_disabled')
  })

  it('returns demo_disabled for unknown demos', async () => {
    const { GET } = await import('@/app/api/demo/analysis/[demoId]/route')
    const res = await GET()
    expect(res.status).toBe(410)
  })
})
