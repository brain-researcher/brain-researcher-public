import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Shared artifact path facade', () => {
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
      if (url === 'http://orchestrator/api/jobs/job_1') {
        return new Response(
          JSON.stringify({
            artifacts: [
              {
                name: 'outputs/result.txt',
                download_url: '/api/jobs/job_1/artifacts/files/outputs/result.txt',
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
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

  it('proxies canonical orchestrator artifact URLs for shared path downloads', async () => {
    const { GET } = await import('@/app/api/share/[token]/artifacts/[...path]/route')
    const req = createRequest('http://test/api/share/tok/artifacts/outputs/result.txt')
    const res = await GET(req, { params: { token: 'tok', path: ['outputs', 'result.txt'] } })

    expect(res.status).toBe(200)
    expect(await res.text()).toBe('artifact-bytes')
    expect(mockFetch).toHaveBeenCalledTimes(3)
    expect(String(mockFetch.mock.calls[2]?.[0] || '')).toBe(
      'http://orchestrator/api/jobs/job_1/artifacts/files/outputs/result.txt',
    )
  })

  it('blocks summary-share access to restricted artifacts on the direct path route', async () => {
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('http://orchestrator/api/share/')) {
        return new Response(JSON.stringify({ analysis_id: 'job_1', share_level: 'summary' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url === 'http://orchestrator/api/jobs/job_1') {
        return new Response(
          JSON.stringify({
            artifacts: [
              {
                name: 'outputs/stat_map.nii.gz',
                download_url: '/api/jobs/job_1/artifacts/files/outputs/stat_map.nii.gz',
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response('artifact-bytes', {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })
    })

    const { GET } = await import('@/app/api/share/[token]/artifacts/[...path]/route')
    const req = createRequest('http://test/api/share/tok/artifacts/outputs/stat_map.nii.gz')
    const res = await GET(req, { params: { token: 'tok', path: ['outputs', 'stat_map.nii.gz'] } })

    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({
      detail: 'This shared link is summary-only; this artifact is not available.',
    })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('rejects artifacts that do not expose canonical orchestrator download URLs', async () => {
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('http://orchestrator/api/share/')) {
        return new Response(JSON.stringify({ analysis_id: 'job_1', share_level: 'full' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url === 'http://orchestrator/api/jobs/job_1') {
        return new Response(
          JSON.stringify({
            artifacts: [
              {
                name: 'outputs/result.txt',
                url: '/api/files/legacy_artifact',
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response('artifact-bytes', {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })
    })

    const { GET } = await import('@/app/api/share/[token]/artifacts/[...path]/route')
    const req = createRequest('http://test/api/share/tok/artifacts/outputs/result.txt')
    const res = await GET(req, { params: { token: 'tok', path: ['outputs', 'result.txt'] } })

    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({
      detail: 'Artifact is missing a canonical Orchestrator download URL.',
    })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})
