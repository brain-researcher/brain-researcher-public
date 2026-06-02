import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockFetch = vi.fn()

global.fetch = mockFetch

describe('kg-api browser routing', () => {
  beforeEach(() => {
    mockFetch.mockReset()
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('uses same-origin KG proxy even when NEXT_PUBLIC_BR_KG_API is set', async () => {
    vi.stubEnv('NEXT_PUBLIC_BR_KG_API', 'http://localhost:5000')
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const { fetchConcepts } = await import('@/lib/kg-api')

    await fetchConcepts({ limit: 5 })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/kg/concepts?limit=5',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
})
