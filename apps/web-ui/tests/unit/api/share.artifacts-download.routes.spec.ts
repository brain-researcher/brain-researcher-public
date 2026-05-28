import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Shared artifact download facade', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('http://orchestrator/api/share/')) {
        return new Response(JSON.stringify({ analysis_id: 'job_1', share_level: 'full' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response('artifact-bytes', {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })
    })
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('proxies orchestrator artifact download paths for shared analyses', async () => {
    const { GET } = await import('@/app/api/share/[token]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/share/tok/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_1%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { token: 'tok' } })
    const text = await res.text()

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(2)
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toBe(
      'http://orchestrator/api/jobs/job_1/artifacts/files/outputs/result.txt',
    )
    expect(text).toBe('artifact-bytes')
  })

  it('surfaces upstream share-resolution failures without local fallback', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'share_not_found_or_expired' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const { GET } = await import('@/app/api/share/[token]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/share/tok/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_1%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { token: 'tok' } })

    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: 'share_not_found_or_expired' })
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('rejects legacy agent-owned artifact paths for shared analyses', async () => {
    const { GET } = await import('@/app/api/share/[token]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/share/tok/artifacts/download?url=%2Fapi%2Ffiles%2Fartifact_1',
    )
    const res = await GET(req, { params: { token: 'tok' } })
    const data = await res.json()

    expect(res.status).toBe(400)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(data.detail).toContain('Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.')
  })

  it('rejects shared artifact downloads for a different analysis id', async () => {
    const { GET } = await import('@/app/api/share/[token]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/share/tok/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_2%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { token: 'tok' } })
    const data = await res.json()

    expect(res.status).toBe(403)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(data.detail).toBe('Requested artifact does not belong to this analysis.')
  })

  it('blocks summary-share downloads for NIfTI outputs', async () => {
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('http://orchestrator/api/share/')) {
        return new Response(JSON.stringify({ analysis_id: 'job_1', share_level: 'summary' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response('artifact-bytes', {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })
    })

    const { GET } = await import('@/app/api/share/[token]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/share/tok/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_1%2Fartifacts%2Ffiles%2Foutputs%2Fstat_map.nii.gz',
    )
    const res = await GET(req, { params: { token: 'tok' } })
    const data = await res.json()

    expect(res.status).toBe(403)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(data.detail).toContain('summary-only')
  })
})
