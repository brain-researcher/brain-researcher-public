import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'

import { makeJsonResponse, queueFetchMock } from '../helpers/fetch-mocks'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

const buildAnalysisDetailMock = vi.fn()
vi.mock('@/lib/server/analysis-detail', () => ({
  buildAnalysisDetail: (...args: any[]) => buildAnalysisDetailMock(...args),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Share contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    buildAnalysisDetailMock.mockResolvedValue({
      ok: true,
      detail: { analysis_id: 'ana_1', artifacts: [], warnings: [] },
    })
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('POST /api/analyses/:id/share returns orchestrator-issued token when available', async () => {
    const analysisId = `analysis_${Date.now()}`
    const expiresAt = new Date(Date.now() + 3600_000).toISOString()

    queueFetchMock(
      mockFetch,
      [
        makeJsonResponse({
          share_token: 'tok-1',
          share_level: 'summary',
          expires_at: expiresAt,
        }),
      ],
    )

    const { POST } = await import('@/app/api/analyses/[analysisId]/share/route')
    const req = createRequest(`http://test/api/analyses/${analysisId}/share`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ share_level: 'summary', expires_in_hours: 2 }),
    })

    const res = await POST(req, { params: { analysisId } })
    expect(res.status).toBe(201)
    const data = await res.json()
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(mockFetch.mock.calls[0]?.[1]?.method).toBe('POST')
    expect(data.analysis_id).toBe(analysisId)
    expect(data.share_token).toBe('tok-1')
    expect(data.share_level).toBe('summary')
    expect(data.share_url).toBe(`http://test/share/tok-1`)
    expect(data.revocable).toBe(true)
  })

  it('POST /api/analyses/:id/share surfaces orchestrator 404 when the share endpoint rejects the request', async () => {
    const analysisId = `analysis_${Date.now()}`

    queueFetchMock(mockFetch, [makeJsonResponse({ detail: 'missing endpoint' }, 404)])

    const { POST } = await import('@/app/api/analyses/[analysisId]/share/route')
    const req = createRequest(`http://test/api/analyses/${analysisId}/share`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ share_level: 'full', expires_in_hours: 24 }),
    })

    const res = await POST(req, { params: { analysisId } })
    expect(res.status).toBe(404)
    const data = await res.json()
    expect(data.detail).toBe('missing endpoint')
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('POST /api/analyses/:id/share surfaces orchestrator 503 when the share service is unavailable', async () => {
    const analysisId = `analysis_${Date.now()}`

    queueFetchMock(mockFetch, [makeJsonResponse({ detail: 'share unavailable' }, 503)])

    const { POST } = await import('@/app/api/analyses/[analysisId]/share/route')
    const req = createRequest(`http://test/api/analyses/${analysisId}/share`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ share_level: 'summary', expires_in_hours: 24 }),
    })

    const res = await POST(req, { params: { analysisId } })
    const data = await res.json()
    expect(res.status).toBe(503)
    expect(data.detail).toBe('share unavailable')
  })

  it('GET /api/share/:token filters artifacts when share_level=summary', async () => {
    const token = `tok_${Date.now()}`
    const analysisId = `analysis_${Date.now()}`
    const expiresAt = new Date(Date.now() + 3600_000).toISOString()

    queueFetchMock(
      mockFetch,
      [
        makeJsonResponse({
          analysis_id: analysisId,
          share_level: 'summary',
          expires_at: expiresAt,
        }),
      ],
    )

    buildAnalysisDetailMock.mockResolvedValue({
      ok: true,
      detail: {
        analysis_id: analysisId,
        warnings: ['Base warning'],
        artifacts: [
          { id: 'a1', name: 'matrix.csv', type: 'file' },
          { id: 'a2', name: 'report.html', type: 'file' },
          { id: 'a3', name: 'stdout.log', type: 'log' },
          { id: 'a4', name: 'stderr.txt', type: 'text/plain' },
          { id: 'a5', name: 'brain.nii.gz', type: 'file' },
        ],
      },
    })

    const { GET } = await import('@/app/api/share/[token]/route')
    const req = createRequest(`http://test/api/share/${token}`)
    const res = await GET(req, { params: { token } })

    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.analysis_id).toBe(analysisId)
    expect(data.share_level).toBe('summary')

    const names = (data.artifacts ?? []).map((a: any) => a.name)
    expect(names).toContain('matrix.csv')
    expect(names).toContain('report.html')
    expect(names).not.toContain('stdout.log')
    expect(names).not.toContain('stderr.txt')
    expect(names).not.toContain('brain.nii.gz')

    expect(String(data.warnings.join(' '))).toContain('shared link')
    expect(String(data.warnings.join(' '))).toContain('summary only')
  })

  it('GET /api/share/:token surfaces upstream invalid-token responses without local fallback', async () => {
    const token = `tok_${Date.now()}`
    queueFetchMock(mockFetch, [makeJsonResponse({ detail: 'share_not_found_or_expired' }, 404)])

    const { GET } = await import('@/app/api/share/[token]/route')
    const req = createRequest(`http://test/api/share/${token}`)
    const res = await GET(req, { params: { token } })

    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: 'share_not_found_or_expired' })
    expect(buildAnalysisDetailMock).not.toHaveBeenCalled()
  })

  it('DELETE /api/share/:token proxies orchestrator revocation', async () => {
    const token = `tok_${Date.now()}`
    queueFetchMock(mockFetch, [makeJsonResponse({ revoked: true }, 200)])

    const { DELETE } = await import('@/app/api/share/[token]/route')
    const req = createRequest(`http://test/api/share/${token}`, { method: 'DELETE' })
    const res = await DELETE(req, { params: { token } })

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ revoked: true })
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(mockFetch.mock.calls[0]?.[1]?.method).toBe('DELETE')
  })

  it('DELETE /api/share/:token surfaces upstream owner checks', async () => {
    const token = `tok_${Date.now()}`
    queueFetchMock(
      mockFetch,
      [makeJsonResponse({ detail: 'Only the share link owner can revoke it.' }, 403)],
    )

    const { DELETE } = await import('@/app/api/share/[token]/route')
    const req = createRequest(`http://test/api/share/${token}`, { method: 'DELETE' })
    const res = await DELETE(req, { params: { token } })

    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({ detail: 'Only the share link owner can revoke it.' })
  })
})
