import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'

import { makeJsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

const createRequest = (url: string) => new NextRequest(new URL(url))

describe('API Routes: Demo real-* proxy routes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockResolvedValue(makeJsonResponse({ ok: true }))
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('GET /api/demo/real-results/:demo_id proxies orchestrator endpoint', async () => {
    const { GET } = await import('@/app/api/demo/real-results/[demo_id]/route')
    const req = createRequest('http://test/api/demo/real-results/demo_1?share=abc')
    const res = await GET(req, { params: { demo_id: 'demo_1' } })
    const payload = await res.json()
    expect(res.status).toBe(200)
    expect(payload.ok).toBe(true)
    expect(String(mockFetch.mock.calls[0][0])).toContain(
      'http://orchestrator/api/demo/real-results/demo_1?share=abc',
    )
  })

  it('GET /api/demo/real-evidence/:demo_id returns 400 for missing demo id', async () => {
    const { GET } = await import('@/app/api/demo/real-evidence/[demo_id]/route')
    const req = createRequest('http://test/api/demo/real-evidence/%20')
    const res = await GET(req, { params: { demo_id: ' ' } })
    expect(res.status).toBe(400)
  })

  it('GET /api/demo/real-artifacts/:demo_id proxies orchestrator endpoint', async () => {
    const { GET } = await import('@/app/api/demo/real-artifacts/[demo_id]/route')
    const req = createRequest('http://test/api/demo/real-artifacts/demo_2')
    const res = await GET(req, { params: { demo_id: 'demo_2' } })
    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0][0])).toContain(
      'http://orchestrator/api/demo/real-artifacts/demo_2',
    )
  })
})
