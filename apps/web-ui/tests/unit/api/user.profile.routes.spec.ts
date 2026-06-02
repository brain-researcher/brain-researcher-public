import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { isRequestAuthenticated } from '@/lib/server/request-auth'

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

describe('API Routes: user profile proxy', () => {
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
})
