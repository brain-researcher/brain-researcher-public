import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { getRequestAuthToken, isRequestAuthenticated } from '@/lib/server/request-auth'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/request-auth', () => ({
  getRequestAuthToken: vi.fn().mockResolvedValue({ sub: 'user-token', tenant_id: 'tenant-token' }),
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer token' }),
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function createRequest(url: string, options: RequestInit = {}) {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: credits identity proxying', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getRequestAuthToken).mockResolvedValue({ sub: 'user-token', tenant_id: 'tenant-token' })
    vi.mocked(isRequestAuthenticated).mockResolvedValue(true)
    mockFetch.mockResolvedValue(jsonResponse({ ok: true }))
  })

  afterEach(() => {
    vi.clearAllMocks()
    delete process.env.BR_ENABLE_CREDITS_GRANT_PROXY
    delete process.env.BR_ENABLE_API_USD_MONTHLY_TOP_UP_PROXY
  })

  it('GET /api/credits/balance injects authenticated account identity', async () => {
    const { GET } = await import('@/app/api/credits/balance/route')

    const res = await GET(
      createRequest(
        'http://test/api/credits/balance?workspace_id=tenant-override&user_id=user-override',
      ),
    )

    expect(res.status).toBe(200)
    const target = new URL(String(mockFetch.mock.calls[0]?.[0]))
    expect(target.pathname).toBe('/api/credits/balance')
    expect(target.searchParams.get('workspace_id')).toBe('tenant-token')
    expect(target.searchParams.get('user_id')).toBe('user-token')
  })

  it('GET /api/credits/balance forwards distinct authenticated accounts separately', async () => {
    const { GET } = await import('@/app/api/credits/balance/route')

    vi.mocked(getRequestAuthToken)
      .mockResolvedValueOnce({ sub: 'user-a', tenant_id: 'tenant-a' })
      .mockResolvedValueOnce({ sub: 'user-b', tenant_id: 'tenant-b' })

    await GET(createRequest('http://test/api/credits/balance'))
    await GET(createRequest('http://test/api/credits/balance'))

    const firstTarget = new URL(String(mockFetch.mock.calls[0]?.[0]))
    const secondTarget = new URL(String(mockFetch.mock.calls[1]?.[0]))
    expect(firstTarget.searchParams.get('workspace_id')).toBe('tenant-a')
    expect(firstTarget.searchParams.get('user_id')).toBe('user-a')
    expect(secondTarget.searchParams.get('workspace_id')).toBe('tenant-b')
    expect(secondTarget.searchParams.get('user_id')).toBe('user-b')
  })

  it('GET /api/credits/ledger uses authenticated identity over query account overrides', async () => {
    const { GET } = await import('@/app/api/credits/ledger/route')

    const res = await GET(
      createRequest(
        'http://test/api/credits/ledger?workspace_id=tenant-override&user_id=user-override&limit=10',
      ),
    )

    expect(res.status).toBe(200)
    const target = new URL(String(mockFetch.mock.calls[0]?.[0]))
    expect(target.pathname).toBe('/api/credits/ledger')
    expect(target.searchParams.get('workspace_id')).toBe('tenant-token')
    expect(target.searchParams.get('user_id')).toBe('user-token')
    expect(target.searchParams.get('limit')).toBe('10')
  })

  it('POST /api/credits/grants is disabled unless explicitly enabled', async () => {
    const { POST } = await import('@/app/api/credits/grants/route')

    const res = await POST(
      createRequest('http://test/api/credits/grants', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ amount: 10, reason: 'monthly_api_credit' }),
      }),
    )

    expect(res.status).toBe(404)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/credits/grants injects authenticated account identity into body when enabled', async () => {
    process.env.BR_ENABLE_CREDITS_GRANT_PROXY = '1'
    const { POST } = await import('@/app/api/credits/grants/route')

    const res = await POST(
      createRequest('http://test/api/credits/grants', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          amount: 10,
          reason: 'monthly_api_credit',
          workspace_id: 'tenant-override',
          user_id: 'user-override',
        }),
      }),
    )

    expect(res.status).toBe(200)
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual(
      expect.objectContaining({
        amount: 10,
        reason: 'monthly_api_credit',
        workspace_id: 'tenant-token',
        user_id: 'user-token',
      }),
    )
  })

  it('POST /api/credits/grants rejects non-object JSON when enabled', async () => {
    process.env.BR_ENABLE_CREDITS_GRANT_PROXY = '1'
    const { POST } = await import('@/app/api/credits/grants/route')

    const res = await POST(
      createRequest('http://test/api/credits/grants', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: 'null',
      }),
    )

    expect(res.status).toBe(400)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('GET /api/credits/api-usd/balance injects authenticated identity and ignores query overrides', async () => {
    const { GET } = await import('@/app/api/credits/api-usd/balance/route')

    const res = await GET(
      createRequest(
        'http://test/api/credits/api-usd/balance?workspace_id=tenant-override&user_id=user-override',
      ),
    )

    expect(res.status).toBe(200)
    const target = new URL(String(mockFetch.mock.calls[0]?.[0]))
    expect(target.pathname).toBe('/api/credits/api-usd/balance')
    expect(target.searchParams.get('workspace_id')).toBe('tenant-token')
    expect(target.searchParams.get('user_id')).toBe('user-token')
  })

  it('POST /api/credits/api-usd/monthly-top-up is disabled unless explicitly enabled', async () => {
    const { POST } = await import('@/app/api/credits/api-usd/monthly-top-up/route')

    const res = await POST(
      createRequest('http://test/api/credits/api-usd/monthly-top-up', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ amount: 1000 }),
      }),
    )

    expect(res.status).toBe(404)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/credits/api-usd/monthly-top-up proxies only authenticated identity when enabled', async () => {
    process.env.BR_ENABLE_API_USD_MONTHLY_TOP_UP_PROXY = '1'
    const { POST } = await import('@/app/api/credits/api-usd/monthly-top-up/route')

    const res = await POST(
      createRequest('http://test/api/credits/api-usd/monthly-top-up', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          workspace_id: 'tenant-override',
          user_id: 'user-override',
          amount: 1000,
          cap: 1000,
          month: '2099-01',
        }),
      }),
    )

    expect(res.status).toBe(200)
    const [targetUrl, init] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(new URL(targetUrl).pathname).toBe('/api/credits/api-usd/monthly-top-up')
    expect(JSON.parse(String(init.body))).toEqual({
      workspace_id: 'tenant-token',
      user_id: 'user-token',
    })
  })
})
