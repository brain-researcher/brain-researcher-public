import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { jsonResponse } from '../helpers/fetch-mocks'

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

describe('API Routes: MCP token proxy', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
  })

  it('GET /api/mcp/tokens requires authentication', async () => {
    authMock.mockResolvedValueOnce(false)
    const { GET } = await import('@/app/api/mcp/tokens/route')
    const req = createRequest('http://test/api/mcp/tokens')

    const res = await GET(req)
    expect(res.status).toBe(401)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/mcp/tokens proxies to orchestrator auth endpoint', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ token: 'brk_kid.secret' }))

    const { POST } = await import('@/app/api/mcp/tokens/route')
    const req = createRequest('http://test/api/mcp/tokens', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    })
    const res = await POST(req)

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator:3001/auth/mcp-tokens',
      expect.objectContaining({
        method: 'POST',
      }),
    )
    const payload = await res.json()
    expect(payload.token).toBe('brk_kid.secret')
  })

  it('DELETE /api/mcp/tokens/[kid] proxies revoke call', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true }))

    const { DELETE } = await import('@/app/api/mcp/tokens/[kid]/route')
    const req = createRequest('http://test/api/mcp/tokens/alice_k1', {
      method: 'DELETE',
    })
    const res = await DELETE(req, { params: { kid: 'alice_k1' } })

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator:3001/auth/mcp-tokens/alice_k1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('GET /api/mcp/tokens/verify proxies verify status', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ backend: 'redis', has_active_token: true }))

    const { GET } = await import('@/app/api/mcp/tokens/verify/route')
    const req = createRequest('http://test/api/mcp/tokens/verify')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator:3001/auth/mcp-tokens/verify',
      expect.objectContaining({ method: 'GET' }),
    )
    const payload = await res.json()
    expect(payload.backend).toBe('redis')
  })
})
