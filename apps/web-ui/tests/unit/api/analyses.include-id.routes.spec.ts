import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { makeJsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch
const mockGetDataset = vi.fn()
const mockGetWorkflowById = vi.fn()

vi.mock('@/lib/server/request-auth', () => ({
  getRequestAuthToken: vi.fn().mockResolvedValue({ sub: 'test-user', tenant_id: 'test-tenant' }),
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent',
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: mockGetDataset,
}))

vi.mock('@/lib/server/workflow-catalog', () => ({
  getWorkflowById: mockGetWorkflowById,
}))

const createRequest = (url: string, options: RequestInit = {}) => new NextRequest(new URL(url), options)

describe('API Routes: Analyses include_id discoverability', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    mockGetDataset.mockReturnValue(null)
    mockGetWorkflowById.mockReturnValue({ workflow: null, version: 'vFinal' })
  })

  afterEach(() => {
    vi.resetAllMocks()
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('forwards include_id upstream for exact run discoverability', async () => {
    mockFetch.mockResolvedValueOnce(makeJsonResponse({ items: [], count: 0 }))

    const { GET } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses?limit=20&include_id=job_da1c8f299607')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain(
      '/api/analyses?limit=20&include_id=job_da1c8f299607',
    )
  })
})
