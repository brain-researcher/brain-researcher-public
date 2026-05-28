import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { isRequestAuthenticated } from '@/lib/server/request-auth'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn(),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer user-token' }),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Analyses steps facade', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/analyses/:id/steps proxies orchestrator steps without Agent fallback', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: 'ana_1', state: 'running', steps: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/route')
    const req = createRequest('http://test/api/analyses/ana_1/steps')
    const res = await GET(req, { params: { analysisId: 'ana_1' } })
    const data = await res.json()

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain(
      'http://orchestrator/api/jobs/ana_1/steps',
    )
    expect(data.job_id).toBe('ana_1')
  })

  it('GET /api/analyses/:id/steps surfaces orchestrator 404s directly', async () => {
    mockFetch.mockResolvedValueOnce(new Response('{"detail":"not found"}', { status: 404 }))

    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/route')
    const req = createRequest('http://test/api/analyses/missing/steps')
    const res = await GET(req, { params: { analysisId: 'missing' } })
    const text = await res.text()

    expect(res.status).toBe(404)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(text).toContain('not found')
  })

  it('GET /api/analyses/:id/steps/stream proxies orchestrator SSE without fallback', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response('event: steps_update\ndata: {"job_id":"ana_1"}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      }),
    )

    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/stream/route')
    const req = createRequest('http://test/api/analyses/ana_1/steps/stream')
    const res = await GET(req, { params: { analysisId: 'ana_1' } })
    const text = await res.text()

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain(
      'http://orchestrator/api/jobs/ana_1/steps/stream',
    )
    expect(text).toContain('steps_update')
  })

  it('GET /api/analyses/:id/steps/stream surfaces orchestrator 503s directly', async () => {
    mockFetch.mockResolvedValueOnce(new Response('service unavailable', { status: 503 }))

    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/stream/route')
    const req = createRequest('http://test/api/analyses/ana_1/steps/stream')
    const res = await GET(req, { params: { analysisId: 'ana_1' } })
    const text = await res.text()

    expect(res.status).toBe(503)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(text).toContain('service unavailable')
  })
})
