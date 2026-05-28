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
  forwardAuthHeaders: () => new Headers(),
}))

const createRequest = (url: string, options: RequestInit = {}) => new NextRequest(new URL(url), options)

describe('API Routes: Project by ID contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/projects/:id proxies upstream', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        project_id: 'proj_alpha',
        name: 'Alpha Project',
      }),
    )

    const { GET } = await import('@/app/api/projects/[projectId]/route')
    const req = createRequest('http://test/api/projects/proj_alpha')
    const res = await GET(req, { params: { projectId: 'proj_alpha' } })
    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('/api/projects/proj_alpha')
    expect(String(mockFetch.mock.calls[0]?.[1]?.method || '')).toBe('GET')
  })

  it('PATCH /api/projects/:id proxies update payload upstream', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        project_id: 'proj_alpha',
        name: 'Renamed',
      }),
    )

    const { PATCH } = await import('@/app/api/projects/[projectId]/route')
    const req = createRequest('http://test/api/projects/proj_alpha', {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: 'Renamed' }),
    })
    const res = await PATCH(req, { params: { projectId: 'proj_alpha' } })
    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0]?.[1]?.method || '')).toBe('PATCH')
    const body = JSON.parse(String(mockFetch.mock.calls[0]?.[1]?.body || '{}'))
    expect(body.name).toBe('Renamed')
  })

  it('DELETE /api/projects/:id rejects unauthenticated requests', async () => {
    authMock.mockResolvedValueOnce(false)
    const { DELETE } = await import('@/app/api/projects/[projectId]/route')
    const req = createRequest('http://test/api/projects/proj_alpha', { method: 'DELETE' })
    const res = await DELETE(req, { params: { projectId: 'proj_alpha' } })
    expect(res.status).toBe(401)
    expect(mockFetch).not.toHaveBeenCalled()
  })
})
