import { NextRequest } from 'next/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: () => new Headers(),
  resolveAgentBaseUrl: () => 'http://agent.test',
}))

const fetchMock = vi.fn()
global.fetch = fetchMock as typeof fetch

function createRequest(url: string, options: RequestInit = {}) {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: legacy runs compatibility proxy', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('POST /api/runs forwards only canonical checkpoint_id', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: 'job-123' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const { POST } = await import('@/app/api/runs/route')
    const response = await POST(
      createRequest('http://test/api/runs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          prompt: 'run',
          pipeline: 'chat',
          resume_checkpoint_id: 'ck-legacy-run',
        }),
      }),
    )

    expect(response.status).toBe(200)
    expect(response.headers.get('x-br-compat-surface')).toBe('agent-runs')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(init?.body || '{}'))
    expect(body.checkpoint_id).toBe('ck-legacy-run')
    expect(body.resume_checkpoint_id).toBeUndefined()
  })
})
