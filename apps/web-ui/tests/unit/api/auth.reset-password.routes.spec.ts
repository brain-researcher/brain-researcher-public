import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { jsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

const createRequest = (body: unknown) =>
  new NextRequest('http://test/api/orchestrator/auth/reset-password', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  })

describe('API Routes: reset password proxy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('rejects malformed request bodies', async () => {
    const { POST } = await import('@/app/api/orchestrator/auth/reset-password/route')

    const res = await POST(createRequest('not-json'))

    expect(res.status).toBe(400)
    expect(await res.json()).toEqual({ detail: 'Invalid request body' })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('proxies valid reset requests to orchestrator auth', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, detail: 'sent' }))
    const { POST } = await import('@/app/api/orchestrator/auth/reset-password/route')

    const res = await POST(createRequest({ email: 'researcher@example.org' }))

    expect(res.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator/auth/reset-password',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'researcher@example.org' }),
        cache: 'no-store',
      }),
    )
    expect(await res.json()).toEqual({ ok: true, detail: 'sent' })
  })

  it('forwards upstream reset failures', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Unknown account' }, 404))
    const { POST } = await import('@/app/api/orchestrator/auth/reset-password/route')

    const res = await POST(createRequest({ email: 'missing@example.org' }))

    expect(res.status).toBe(404)
    expect(await res.json()).toEqual({ detail: 'Unknown account' })
  })

  it('returns 502 when the upstream reset service is unavailable', async () => {
    mockFetch.mockRejectedValueOnce(new Error('offline'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { POST } = await import('@/app/api/orchestrator/auth/reset-password/route')

    const res = await POST(createRequest({ email: 'researcher@example.org' }))

    expect(res.status).toBe(502)
    expect(await res.json()).toEqual({ detail: 'Password reset service temporarily unavailable' })
    consoleSpy.mockRestore()
  })
})
