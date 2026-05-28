import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { jsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent',
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

const createRequest = (url: string, options: RequestInit = {}) => new NextRequest(new URL(url), options)

describe('API Routes: Projects contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/projects rejects unauthenticated requests', async () => {
    authMock.mockResolvedValueOnce(false)
    const { GET } = await import('@/app/api/projects/route')
    const req = createRequest('http://test/api/projects')
    const res = await GET(req)
    expect(res.status).toBe(401)
  })

  it('GET /api/projects aggregates runs by project and keeps default fallback', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        projects: [
          {
            project_id: 'proj_alpha',
            name: 'Alpha Project',
            description: 'test description',
          },
        ],
        count: 1,
      }),
    )
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            analysis_id: 'run_1',
            state: 'succeeded',
            created_at: 1700000000000,
            project_id: 'proj_alpha',
          },
          {
            analysis_id: 'run_2',
            state: 'running',
            created_at: 1700000100,
            project_id: 'proj_alpha',
          },
          {
            analysis_id: 'run_3',
            state: 'failed',
            created_at: '2026-02-20T00:00:00Z',
            project_id: '',
          },
        ],
        count: 3,
      }),
    )

    const { GET } = await import('@/app/api/projects/route')
    const req = createRequest('http://test/api/projects?runs_limit=100')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('/api/projects')
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toContain('/api/analyses?limit=100')

    const data = await res.json()
    expect(Array.isArray(data.items)).toBe(true)
    expect(data.count).toBeGreaterThanOrEqual(2)
    expect(data.truncated).toBe(false)

    const alpha = data.items.find((item: any) => item.project_id === 'proj_alpha')
    expect(alpha).toBeTruthy()
    expect(alpha.name).toBe('Alpha Project')
    expect(alpha.description).toBe('test description')
    expect(alpha.run_count).toBe(2)
    expect(alpha.status_counts.completed).toBe(1)
    expect(alpha.status_counts.running).toBe(1)

    const defaultProject = data.items.find((item: any) => item.project_id === 'default')
    expect(defaultProject).toBeTruthy()
    expect(defaultProject.run_count).toBe(1)
    expect(defaultProject.status_counts.failed).toBe(1)
  })

  it('GET /api/projects marks result truncated when sampled runs are below upstream count', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        projects: [],
        count: 0,
      }),
    )
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        items: [{ analysis_id: 'run_1', state: 'queued', created_at: 1700000000 }],
        count: 99,
      }),
    )

    const { GET } = await import('@/app/api/projects/route')
    const req = createRequest('http://test/api/projects?runs_limit=1')
    const res = await GET(req)

    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.sampled_runs).toBe(1)
    expect(data.upstream_total_runs).toBe(99)
    expect(data.truncated).toBe(true)
  })

  it('GET /api/projects clamps runs_limit to orchestrator max', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        projects: [],
        count: 0,
      }),
    )
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        count: 0,
      }),
    )

    const { GET } = await import('@/app/api/projects/route')
    const req = createRequest('http://test/api/projects?runs_limit=250')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toContain('/api/analyses?limit=200')
  })

  it('POST /api/projects proxies create payload upstream', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        project_id: 'proj_new',
        name: 'New Project',
      }, 201),
    )

    const { POST } = await import('@/app/api/projects/route')
    const req = createRequest('http://test/api/projects', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        project_id: 'proj_new',
        name: 'New Project',
        description: 'desc',
      }),
    })
    const res = await POST(req)
    expect(res.status).toBe(201)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('/api/projects')
    expect(String(mockFetch.mock.calls[0]?.[1]?.method || '')).toBe('POST')
    const body = JSON.parse(String(mockFetch.mock.calls[0]?.[1]?.body || '{}'))
    expect(body.project_id).toBe('proj_new')
    expect(body.name).toBe('New Project')
  })
})
