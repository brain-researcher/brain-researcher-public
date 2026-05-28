import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'

import { loadDemoIndex } from '@/lib/server/demo-index'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn(),
}))

vi.mock('@/lib/server/demo-index', () => ({
  loadDemoIndex: vi.fn(),
}))

vi.mock('@/lib/server/internal-jwt', () => ({
  issueInternalJwt: vi.fn(),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer user-token' }),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Analyses analysis-stream proxy', () => {
  const authMock = vi.mocked(isRequestAuthenticated)
  const demoIndexMock = vi.mocked(loadDemoIndex)
  const issueInternalJwtMock = vi.mocked(issueInternalJwt)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    demoIndexMock.mockReturnValue({ demos: [] })
    issueInternalJwtMock.mockReturnValue('demo-internal-token')
    mockFetch.mockResolvedValue(
      new Response('event: ping\ndata: {"ok":true}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      }),
    )
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/analyses/:id/analysis-stream returns 400 for missing id', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/%20/analysis-stream')
    const res = await GET(req, { params: { analysisId: ' ' } })
    expect(res.status).toBe(400)
  })

  it('GET /api/analyses/:id/analysis-stream rejects unauthenticated non-demo', async () => {
    authMock.mockResolvedValue(false)
    demoIndexMock.mockReturnValue({ demos: [{ slug: 'demo', analysis_id: 'demo_1', title: 'Demo' }] })
    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/ana_1/analysis-stream')
    const res = await GET(req, { params: { analysisId: 'ana_1' } })
    expect(res.status).toBe(401)
  })

  it('GET /api/analyses/:id/analysis-stream proxies orchestrator stream for authed users', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/ana_1/analysis-stream?since=1')
    const res = await GET(req, { params: { analysisId: 'ana_1' } })

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const [targetUrl, options] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(String(targetUrl)).toContain('http://orchestrator/api/jobs/ana_1/analysis-stream?since=1')
    const headers = options.headers as Headers
    expect(headers.get('authorization')).toBe('Bearer user-token')
    expect(res.headers.get('cache-control')).toBe('no-cache, no-transform')
    expect(res.headers.get('x-accel-buffering')).toBe('no')
  })

  it('GET /api/analyses/:id/analysis-stream allows unauth demo with internal jwt and redacts payload', async () => {
    authMock.mockResolvedValue(false)
    demoIndexMock.mockReturnValue({
      demos: [{ slug: 'demo-1', analysis_id: 'run_demo_1', title: 'Demo 1' }],
    })
    mockFetch.mockResolvedValue(
      new Response(
        [
          'event: analysis_event',
          'data: {"authorization":"Bearer abc123","token":"x.y.z","path":"/home/secret/data/file.nii.gz","url":"https://example.com/api?token=abc&ok=1","note":"Bearer qwerty and /tmp/private/path"}',
          '',
          '',
        ].join('\n'),
        {
          status: 200,
          headers: { 'content-type': 'text/event-stream; charset=utf-8' },
        },
      ),
    )

    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/run_demo_1/analysis-stream')
    const res = await GET(req, { params: { analysisId: 'run_demo_1' } })
    const text = await res.text()

    expect(res.status).toBe(200)
    expect(issueInternalJwtMock).toHaveBeenCalledTimes(1)
    expect(text).not.toContain('abc123')
    expect(text).not.toContain('x.y.z')
    expect(text).not.toContain('/home/secret')
    expect(text).toContain('[REDACTED]')
    expect(text).toContain('[REDACTED_PATH]')
  })

  it('GET /api/analyses/:id/analysis-stream surfaces orchestrator 404s', async () => {
    mockFetch.mockResolvedValueOnce(new Response('not found', { status: 404 }))
    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/ana_fallback/analysis-stream')
    const res = await GET(req, { params: { analysisId: 'ana_fallback' } })
    const text = await res.text()

    expect(res.status).toBe(404)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(text).toContain('not found')
  })

  it('GET /api/analyses/:id/analysis-stream surfaces orchestrator 503s', async () => {
    mockFetch.mockResolvedValueOnce(new Response('service unavailable', { status: 503 }))
    const { GET } = await import('@/app/api/analyses/[analysisId]/analysis-stream/route')
    const req = createRequest('http://test/api/analyses/ana_fallback_503/analysis-stream')
    const res = await GET(req, { params: { analysisId: 'ana_fallback_503' } })
    const text = await res.text()

    expect(res.status).toBe(503)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(text).toContain('service unavailable')
  })
})
