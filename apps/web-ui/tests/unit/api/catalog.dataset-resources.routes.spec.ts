import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { makeJsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
const mockForwardAuthHeaders = vi.fn()

global.fetch = mockFetch

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent:8000',
  forwardAuthHeaders: (...args: any[]) => mockForwardAuthHeaders(...args),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: catalog dataset resources', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockForwardAuthHeaders.mockReturnValue(new Headers())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns auth_required for public requests without bearer token', async () => {
    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest('http://test/api/catalog/datasets/ds:openneuro:ds000001/resources')

    const res = await GET(req, { params: { datasetId: 'ds:openneuro:ds000001' } })
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.dataset_ref).toBe('ds:openneuro:ds000001')
    expect(payload.readiness?.status).toBe('auth_required')
    expect(payload.addresses?.openneuro_url).toBe('https://openneuro.org/datasets/ds000001')
    expect(payload.addresses?.s3_uri).toBe('s3://openneuro.org/ds000001')
    expect(payload.exists_summary?.dataset_in_catalog).toBe(true)
    expect(payload.dataset_summary?.dataset_id).toBe('ds:openneuro:ds000001')
    expect(payload.storage_summary?.bids_path).toBeUndefined()
    expect(payload.files_summary?.analysis_goal).toBeUndefined()
    expect(Array.isArray(payload.versions)).toBe(true)
    expect(payload.default_version).toBeTruthy()
    expect(payload.unavailable).toBe(false)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('maps missing_bearer_token upstream errors to auth_required status', async () => {
    mockForwardAuthHeaders.mockReturnValue(new Headers({ authorization: 'Bearer test-token' }))
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse(
        { error: 'missing_bearer_token', detail: 'Authorization header required' },
        401,
      ),
    )

    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest('http://test/api/catalog/datasets/ds:openneuro:ds000005/resources')

    const res = await GET(req, { params: { datasetId: 'ds:openneuro:ds000005' } })
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.readiness?.status).toBe('auth_required')
    expect(payload.unavailable).toBe(false)
    expect(payload.addresses?.openneuro_url).toBe('https://openneuro.org/datasets/ds000005')
    expect(payload.exists_summary?.dataset_in_catalog).toBe(true)
    expect(Array.isArray(payload.versions)).toBe(true)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const upstreamCall = mockFetch.mock.calls[0]
    const init = upstreamCall?.[1] as RequestInit | undefined
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
    expect(body.tool).toBe('datasets.list_resources')
    expect(body.arguments?.dataset_ref).toBe('ds:openneuro:ds000005')
    expect(body.args?.dataset_ref).toBe('ds:openneuro:ds000005')
    expect(init?.signal).toBeInstanceOf(AbortSignal)
  })

  it('forwards requested datasetVersion to upstream tool arguments', async () => {
    mockForwardAuthHeaders.mockReturnValue(new Headers({ authorization: 'Bearer test-token' }))
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse(
        { error: 'missing_bearer_token', detail: 'Authorization header required' },
        401,
      ),
    )

    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest(
      'http://test/api/catalog/datasets/ds:openneuro:ds000005/resources?datasetVersion=v1.0.0',
    )

    const res = await GET(req, { params: { datasetId: 'ds:openneuro:ds000005' } })
    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const upstreamCall = mockFetch.mock.calls[0]
    const init = upstreamCall?.[1] as RequestInit | undefined
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
    expect(body.arguments?.dataset_version).toBe('v1.0.0')
    expect(body.args?.dataset_version).toBe('v1.0.0')
    expect(init?.signal).toBeInstanceOf(AbortSignal)
  })

  it('forwards local-fast source-access preference to upstream tool arguments', async () => {
    mockForwardAuthHeaders.mockReturnValue(new Headers({ authorization: 'Bearer test-token' }))
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse(
        { error: 'missing_bearer_token', detail: 'Authorization header required' },
        401,
      ),
    )

    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest(
      'http://test/api/catalog/datasets/ds:openneuro:ds000114/resources?checkSourceAccess=false',
    )

    const res = await GET(req, { params: { datasetId: 'ds:openneuro:ds000114' } })
    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const upstreamCall = mockFetch.mock.calls[0]
    const init = upstreamCall?.[1] as RequestInit | undefined
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
    expect(body.arguments?.check_source_access).toBe(false)
    expect(body.args?.check_source_access).toBe(false)
  })

  it('returns degraded static OpenNeuro hints when ds000114 readiness times out', async () => {
    vi.useFakeTimers()
    mockForwardAuthHeaders.mockReturnValue(new Headers({ authorization: 'Bearer test-token' }))
    mockFetch.mockImplementationOnce((_url: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        const signal = init?.signal as AbortSignal | undefined
        signal?.addEventListener('abort', () => reject(signal.reason), { once: true })
      })
    })

    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest('http://test/api/catalog/datasets/ds:openneuro:ds000114/resources')

    const pending = GET(req, { params: { datasetId: 'ds:openneuro:ds000114' } })
    await vi.advanceTimersByTimeAsync(5000)
    const res = await pending
    const payload = await res.json()

    expect(res.status).toBe(200)
    expect(payload.dataset_ref).toBe('ds:openneuro:ds000114')
    expect(payload.unavailable).toBe(false)
    expect(payload.error).toBe('resource_readiness_timeout_after_5000ms')
    expect(payload.readiness?.status).toBe('degraded')
    expect(payload.readiness?.reason).toContain('Static OpenNeuro source addresses are available')
    expect(payload.addresses?.openneuro_url).toBe('https://openneuro.org/datasets/ds000114')
    expect(payload.addresses?.s3_uri).toBe('s3://openneuro.org/ds000114')
    expect(payload.source_access?.provider).toBe('openneuro')
    expect(payload.source_access?.bucket_uri).toBe('s3://openneuro.org/ds000114')
    expect(payload.source_access?.bucket_check?.state).toBe('unreachable')
    expect(payload.source_access?.bucket_check?.method).toBeUndefined()
    expect(payload.source_access?.bucket_check?.message).toContain('static OpenNeuro address hints')
    expect(payload.exists_summary?.dataset_in_catalog).toBe(true)
    expect(payload.exists_summary?.source_repo_id).toBe('ds000114')
    expect(payload.default_version).toBeTruthy()
  })

  it('honors requested datasetVersion when it exists in version options', async () => {
    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest(
      'http://test/api/catalog/datasets/ds:openneuro:ds000005/resources?datasetVersion=latest',
    )

    const res = await GET(req, { params: { datasetId: 'ds:openneuro:ds000005' } })
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.default_version).toBeTruthy()
    expect(payload.selected_version).toBe('latest')
  })

  it('resolves short dataset ids against catalog aliases', async () => {
    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest('http://test/api/catalog/datasets/hcp_ya/resources')

    const res = await GET(req, { params: { datasetId: 'hcp_ya' } })
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.dataset_ref).toBe('hcp_ya')
    expect(payload.readiness?.status).toBe('auth_required')
    expect(payload.exists_summary?.dataset_in_catalog).toBe(true)
    expect(payload.exists_summary?.source_repo).toBe('HCP DB / AWS')
    expect(payload.dataset_summary?.subjects_count).toBe(1206)
    expect(payload.default_version).toBeTruthy()
  })

  it('does not surface placeholder NaN strings as human-readable size', async () => {
    const { GET } = await import('@/app/api/catalog/datasets/[datasetId]/resources/route')
    const req = createRequest('http://test/api/catalog/datasets/abcd/resources')

    const res = await GET(req, { params: { datasetId: 'abcd' } })
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.dataset_summary?.dataset_id).toBe('ds:manual:abcd')
    expect(payload.storage_summary?.size_human).toBeUndefined()
  })
})
