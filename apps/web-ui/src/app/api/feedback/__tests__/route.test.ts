// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: vi.fn(() => 'http://orchestrator'),
}))

import { GET, POST } from '../route'

describe('/api/feedback route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('proxies feedback submissions to orchestrator /api/feedback', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: 'feedback_123', message: 'Feedback recorded' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const req = new NextRequest('http://localhost/api/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        rating: 5,
        category: 'bug-report',
        title: 'Broken chart',
        description: 'The visualization panel failed to render.',
      }),
    })

    const response = await POST(req)

    expect(response.status).toBe(201)
    expect(await response.json()).toEqual({ id: 'feedback_123', message: 'Feedback recorded' })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/feedback',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rating: 5,
          category: 'bug-report',
          title: 'Broken chart',
          description: 'The visualization panel failed to render.',
        }),
        signal: expect.any(AbortSignal),
      }),
    )
  })

  it('proxies feedback listing to orchestrator /api/feedback', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ submissions: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const response = await GET()

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ submissions: [] })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/feedback',
      expect.objectContaining({
        signal: expect.any(AbortSignal),
      }),
    )
  })
})
