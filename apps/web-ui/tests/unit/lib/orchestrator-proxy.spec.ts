import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'

import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { makeJsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer test' }),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('Server lib: orchestrator-proxy', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('requireAuth returns 401 when request is not authenticated', async () => {
    authMock.mockResolvedValue(false)
    const { requireAuth } = await import('@/lib/server/orchestrator-proxy')

    const req = createRequest('http://test/api/analyses/ana_1')
    const res = await requireAuth(req)

    expect(res?.status).toBe(401)
  })

  it('proxyStream returns upstream error response when upstream is not ok', async () => {
    mockFetch.mockResolvedValueOnce(makeJsonResponse({ detail: 'nope' }, 503))

    const { proxyStream } = await import('@/lib/server/orchestrator-proxy')
    const req = createRequest('http://test/api/analyses/ana_1/analysis-stream')
    const res = await proxyStream(req, 'http://orchestrator/api/jobs/ana_1/analysis-stream')

    expect(res.status).toBe(503)
    expect(res.headers.get('content-type')).toContain('application/json')
    const text = await res.text()
    expect(text).toContain('nope')
  })

  it('proxyStream returns upstream body when upstream is ok', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response('event: ok\ndata: {}\n\n', {
        status: 200,
        headers: {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache',
        },
      }),
    )

    const { proxyStream } = await import('@/lib/server/orchestrator-proxy')
    const req = createRequest('http://test/api/analyses/ana_1/analysis-stream')
    const res = await proxyStream(req, 'http://orchestrator/api/jobs/ana_1/analysis-stream')

    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('text/event-stream')
    expect(res.headers.get('cache-control')).toBe('no-cache')
    const text = await res.text()
    expect(text).toContain('event: ok')
  })
})
