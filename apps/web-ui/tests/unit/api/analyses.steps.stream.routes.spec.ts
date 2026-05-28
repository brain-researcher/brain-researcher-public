import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest, NextResponse } from 'next/server'

const requireAuthMock = vi.fn()
const proxyStreamMock = vi.fn()

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

vi.mock('@/lib/server/orchestrator-proxy', () => ({
  requireAuth: (...args: any[]) => requireAuthMock(...args),
  proxyStream: (...args: any[]) => proxyStreamMock(...args),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Analyses steps stream proxy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    requireAuthMock.mockResolvedValue(null)
    proxyStreamMock.mockResolvedValue(
      new NextResponse('event: ping\ndata: {"ok":true}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }),
    )
  })

  it('GET /api/analyses/:id/steps/stream proxies to orchestrator steps stream', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/stream/route')
    const req = createRequest('http://test/api/analyses/ana_1/steps/stream')

    const res = await GET(req, { params: { analysisId: 'ana_1' } })

    expect(res.status).toBe(200)
    expect(proxyStreamMock).toHaveBeenCalledTimes(1)
    expect(String(proxyStreamMock.mock.calls[0]?.[1] || '')).toBe(
      'http://orchestrator/api/jobs/ana_1/steps/stream',
    )
  })

  it('GET /api/analyses/:id/steps/stream surfaces orchestrator errors', async () => {
    proxyStreamMock.mockResolvedValueOnce(
      NextResponse.json({ detail: 'not found' }, { status: 404 }),
    )

    const { GET } = await import('@/app/api/analyses/[analysisId]/steps/stream/route')
    const req = createRequest('http://test/api/analyses/ana_missing/steps/stream')

    const res = await GET(req, { params: { analysisId: 'ana_missing' } })
    const data = await res.json()

    expect(res.status).toBe(404)
    expect(data.detail).toBe('not found')
  })
})
