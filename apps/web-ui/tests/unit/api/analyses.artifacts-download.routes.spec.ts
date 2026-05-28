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

describe('API Routes: Analyses artifact download facade', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('proxies orchestrator artifact download paths', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response('artifact-bytes', {
        status: 200,
        headers: {
          'content-type': 'application/octet-stream',
          'content-disposition': 'attachment; filename="result.txt"',
        },
      }),
    )

    const { GET } = await import('@/app/api/analyses/[analysisId]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/analyses/job_1/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_1%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { analysisId: 'job_1' } })
    const text = await res.text()

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toBe(
      'http://orchestrator/api/jobs/job_1/artifacts/files/outputs/result.txt',
    )
    expect(text).toBe('artifact-bytes')
  })

  it('rejects legacy agent-owned artifact URLs', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/analyses/job_1/artifacts/download?url=%2Fapi%2Fruns%2Fjob_1%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { analysisId: 'job_1' } })
    const data = await res.json()

    expect(res.status).toBe(400)
    expect(mockFetch).not.toHaveBeenCalled()
    expect(data.detail).toContain('Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.')
  })

  it('rejects orchestrator artifact downloads for a different analysis id', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/artifacts/download/route')
    const req = createRequest(
      'http://test/api/analyses/job_1/artifacts/download?url=%2Fapi%2Fjobs%2Fjob_2%2Fartifacts%2Ffiles%2Foutputs%2Fresult.txt',
    )
    const res = await GET(req, { params: { analysisId: 'job_1' } })
    const data = await res.json()

    expect(res.status).toBe(403)
    expect(mockFetch).not.toHaveBeenCalled()
    expect(data.detail).toBe('Requested artifact does not belong to this analysis.')
  })
})
