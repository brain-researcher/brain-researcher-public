import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { jsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator:3001',
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer test-session-token' }),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: user profile + notifications proxy', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  it('GET /api/user/profile requires authentication', async () => {
    authMock.mockResolvedValueOnce(false)
    const { GET } = await import('@/app/api/user/profile/route')
    const req = createRequest('http://test/api/user/profile')

    const res = await GET(req)
    expect(res.status).toBe(401)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('GET /api/user/notifications proxies query params', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ notifications: [] }))

    const { GET } = await import('@/app/api/user/notifications/route')
    const req = createRequest('http://test/api/user/notifications?limit=25')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator:3001/api/user/notifications?limit=25',
      expect.objectContaining({ method: 'GET' }),
    )
    const payload = await res.json()
    expect(payload.notifications).toEqual([])
  })

  it('POST /api/user/notifications/mark-read proxies payload', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ marked_count: 2 }))

    const { POST } = await import('@/app/api/user/notifications/mark-read/route')
    const req = createRequest('http://test/api/user/notifications/mark-read', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ notification_ids: ['n1', 'n2'] }),
    })
    const res = await POST(req)

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator:3001/api/user/notifications/mark-read',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ notification_ids: ['n1', 'n2'] }),
      }),
    )
    const payload = await res.json()
    expect(payload.marked_count).toBe(2)
  })
})
