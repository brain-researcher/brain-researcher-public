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
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Analyses stream contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/analyses/:id/stream proxies SSE and emits milestone events', async () => {
    const analysisId = `analysis_${Date.now()}`

    const upstreamSse = [
      `event: initial_state`,
      `data: ${JSON.stringify({
        steps: [{ name: 'validate bids' }, { name: 'report' }],
      })}`,
      ``,
      `event: progress_update`,
      `data: ${JSON.stringify({
        status: 'running',
        overall_progress: 50,
        current_step: 0,
      })}`,
      ``,
      `event: job_complete`,
      `data: ${JSON.stringify({
        status: 'succeeded',
        overall_progress: 100,
        current_step: 1,
      })}`,
      ``,
      ``,
    ].join('\n')

    mockFetch.mockImplementation(async (input: any) => {
      const url = String(input)
      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}/stream`)) {
        return new Response(upstreamSse, {
          status: 200,
          headers: { 'content-type': 'text/event-stream; charset=utf-8' },
        })
      }

      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}/artifacts`)) {
        return makeJsonResponse({ artifacts: [] })
      }

      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { GET } = await import('@/app/api/analyses/[analysisId]/stream/route')

    const req = createRequest(`http://test/api/analyses/${analysisId}/stream`)
    const res = await GET(req, { params: { analysisId } })

    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('text/event-stream')

    const text = await res.text()
    expect(text).toContain('event: initial_state')
    expect(text).toContain('event: progress_update')
    expect(text).toContain('event: milestone')
    expect(text).toContain('event: job_complete')
  })

  it('GET /api/analyses/:id/stream falls back to polling when upstream stream unavailable', async () => {
    const analysisId = `analysis_${Date.now()}`

    mockFetch.mockImplementation(async (input: any) => {
      const url = String(input)

      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}/stream`)) {
        return new Response('upstream unavailable', { status: 503 })
      }

      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}`)) {
        return makeJsonResponse({ steps: [{ name: 'validate bids' }, { name: 'report' }] })
      }

      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}/progress`)) {
        return makeJsonResponse({
          status: 'succeeded',
          overall_progress: 100,
          current_step: 1,
        })
      }

      if (url.endsWith(`/api/jobs/${encodeURIComponent(analysisId)}/artifacts`)) {
        return makeJsonResponse({ artifacts: [] })
      }

      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { GET } = await import('@/app/api/analyses/[analysisId]/stream/route')

    const req = createRequest(`http://test/api/analyses/${analysisId}/stream`)
    const res = await GET(req, { params: { analysisId } })

    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('text/event-stream')

    const text = await res.text()
    expect(text).toContain('event: initial_state')
    expect(text).toContain('event: progress_update')
    expect(text).toContain('event: milestone')
    expect(text).toContain('event: job_complete')
  })

  it('GET /api/analyses/:id/stream rejects unauthenticated requests', async () => {
    authMock.mockResolvedValue(false)

    const { GET } = await import('@/app/api/analyses/[analysisId]/stream/route')
    const req = createRequest('http://test/api/analyses/ana_123/stream')
    const res = await GET(req, { params: { analysisId: 'ana_123' } })

    expect(res.status).toBe(401)
  })
})
