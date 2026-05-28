// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: vi.fn(() => new Headers({ authorization: 'Bearer proxy-token' })),
  resolveOrchestratorBaseUrl: vi.fn(() => 'http://orchestrator'),
}))

import { POST } from '../route'

describe('/api/events route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('proxies analytics events to orchestrator /api/events', async () => {
    const fetchMock = vi.fn(async (_input: Parameters<typeof fetch>[0], _init?: Parameters<typeof fetch>[1]) =>
      new Response(JSON.stringify({ status: 'success', events_received: 1 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const req = new NextRequest('http://localhost/api/events', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-tracking-id': 'track-demo',
      },
      body: JSON.stringify({
        events: [{ name: 'page_view', category: 'navigation', timestamp: 1, sessionId: 's1', pageUrl: 'http://localhost', userAgent: 'vitest' }],
      }),
    })

    const response = await POST(req)
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ status: 'success', events_received: 1 })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/events',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        body: expect.stringContaining('"events"'),
        headers: expect.any(Headers),
      }),
    )

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(headers.get('authorization')).toBe('Bearer proxy-token')
    expect(headers.get('x-tracking-id')).toBe('track-demo')
    expect(headers.get('content-type')).toBe('application/json')
  })

  it('returns 502 when orchestrator is unreachable', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('connection refused')
    }) as typeof fetch)

    const req = new NextRequest('http://localhost/api/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ events: [] }),
    })

    const response = await POST(req)
    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({ detail: 'Analytics service temporarily unavailable' })
    errorSpy.mockRestore()
  })
})
