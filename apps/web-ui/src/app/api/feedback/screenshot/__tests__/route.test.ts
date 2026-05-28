// @vitest-environment node
import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: vi.fn(() => 'http://orchestrator'),
}))

import { POST } from '../route'

describe('/api/feedback/screenshot route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('proxies screenshot uploads to orchestrator /api/feedback/screenshot', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ success: true, url: '/api/feedback/screenshot/shot_123' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock as typeof fetch)

    const formData = new FormData()
    formData.append('feedback_id', 'feedback_123')
    formData.append(
      'screenshot',
      new File([new Uint8Array([1, 2, 3])], 'screenshot.png', { type: 'image/png' }),
    )

    const req = new NextRequest('http://localhost/api/feedback/screenshot', {
      method: 'POST',
      body: formData,
    })

    const response = await POST(req)

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      success: true,
      url: '/api/feedback/screenshot/shot_123',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://orchestrator/api/feedback/screenshot',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
        signal: expect.any(AbortSignal),
      }),
    )
  })
})
