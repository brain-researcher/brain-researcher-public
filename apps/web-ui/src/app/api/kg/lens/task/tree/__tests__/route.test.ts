// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: vi.fn(() => new Headers({ authorization: 'Bearer proxy-token' })),
}))

vi.mock('@/lib/server/kg-proxy', () => ({
  resolveKgBaseUrl: vi.fn(() => 'http://kg'),
}))

import { GET } from '../route'

describe('/api/kg/lens/task/tree route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns upstream task tree payload on success', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ families: [{ id: 'memory', label: 'Memory', children: [] }] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const req = new NextRequest('http://localhost/api/kg/lens/task/tree?limit=10')
    const response = await GET(req)

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      families: [{ id: 'memory', label: 'Memory', children: [] }],
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://kg/api/kg/lens/task/tree?limit=10',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        headers: expect.any(Headers),
      }),
    )
  })

  it('returns quiet unavailable payload when BR-KG is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('connection refused')
    }) as typeof fetch)

    const req = new NextRequest('http://localhost/api/kg/lens/task/tree?limit=10')
    const response = await GET(req)

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      ok: false,
      error: 'unreachable',
      upstream_status: 503,
    })
  })
})
