// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: vi.fn(() => new Headers({ authorization: 'Bearer proxy-token' })),
}))

vi.mock('@/lib/server/kg-proxy', () => ({
  normalizeKgSubpath: vi.fn((value: string[]) => value.join('/')),
  resolveKgBaseUrl: vi.fn(() => 'http://kg'),
}))

import { GET, POST } from '../route'

describe('/api/neurokg/[...path] route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('proxies legacy root subgraph requests without injecting /api', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ nodes: [], edges: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const req = new NextRequest('http://localhost/api/neurokg/subgraph?label=Concept&name=wm')
    const response = await GET(req, { params: { path: ['subgraph'] } })

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://kg/subgraph?label=Concept&name=wm',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        headers: expect.any(Headers),
      }),
    )
  })

  it('proxies legacy root graphql requests without injecting /api', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ data: { ok: true } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const req = new NextRequest('http://localhost/api/neurokg/graphql', {
      method: 'POST',
      body: JSON.stringify({ query: '{ health }' }),
      headers: { 'content-type': 'application/json' },
    })
    const response = await POST(req, { params: { path: ['graphql'] } })

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://kg/graphql',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        headers: expect.any(Headers),
        body: expect.any(ArrayBuffer),
      }),
    )
  })
})
