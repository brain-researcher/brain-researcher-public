// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: vi.fn(() => new Headers({ authorization: 'Bearer proxy-token' })),
  resolveOrchestratorBaseUrl: vi.fn(() => 'http://orchestrator'),
}))

vi.mock('@/lib/server/request-auth', () => ({
  getVerifiedBearerToken: vi.fn(async () => null),
}))

import { GET, POST } from '../route'
import { getVerifiedBearerToken } from '@/lib/server/request-auth'

describe('/api/studio/[...path] route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('proxies studio session create requests to orchestrator', async () => {
    const fetchMock = vi.fn(async (_input: Parameters<typeof fetch>[0], _init?: Parameters<typeof fetch>[1]) =>
      new Response(JSON.stringify({ session: { id: 'studio_s_1' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const request = new NextRequest('http://localhost/api/studio/sessions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ project_id: 'proj_demo' }),
    })

    const response = await POST(request, { params: { path: ['sessions'] } })
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ session: { id: 'studio_s_1' } })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/studio/sessions',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        body: JSON.stringify({ project_id: 'proj_demo' }),
        headers: expect.any(Headers),
      }),
    )

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(headers.get('authorization')).toBe('Bearer proxy-token')
    expect(headers.get('content-type')).toBe('application/json')
    expect(headers.get('accept')).toBe('application/json')
  })

  it('preserves query strings for studio execution reads', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const request = new NextRequest(
      'http://localhost/api/studio/sessions?project_id=proj_demo&limit=5',
    )
    const response = await GET(request, { params: { path: ['sessions'] } })

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/studio/sessions?project_id=proj_demo&limit=5',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        headers: expect.any(Headers),
      }),
    )
  })

  it('prefers a verified bearer token when one can be resolved from the request', async () => {
    vi.mocked(getVerifiedBearerToken).mockResolvedValueOnce('verified-token')
    const fetchMock = vi.fn(async (_input: Parameters<typeof fetch>[0], _init?: Parameters<typeof fetch>[1]) =>
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const request = new NextRequest('http://localhost/api/studio/sessions')
    const response = await GET(request, { params: { path: ['sessions'] } })

    expect(response.status).toBe(200)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(headers.get('authorization')).toBe('Bearer verified-token')
  })

  it('returns 502 when the studio gateway is unreachable', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('connection refused')
      }) as typeof fetch,
    )

    const request = new NextRequest('http://localhost/api/studio/sessions')
    const response = await GET(request, { params: { path: ['sessions'] } })

    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({ detail: 'Studio gateway temporarily unavailable' })
    errorSpy.mockRestore()
  })
})
