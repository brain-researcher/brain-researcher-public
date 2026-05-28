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

describe('API Routes: chat proxies', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('POST /api/chat normalizes resume checkpoint ids into canonical ctx', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: { content: 'ok' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const { POST } = await import('@/app/api/chat/route')
    const response = await POST(
      createRequest('http://test/api/chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          message: 'continue',
          resume_checkpoint_id: 'ck-resume-1',
          ctx: {
            checkpointId: 'stale-legacy-ck',
          },
        }),
      }),
    )

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(init?.body || '{}'))
    expect(body.ctx.resume_checkpoint_id).toBe('ck-resume-1')
    expect(body.ctx.checkpointId).toBeUndefined()
    expect(body.ctx.checkpoint_id).toBeUndefined()
    expect(body.resume_checkpoint_id).toBeUndefined()
  })

  it('POST /api/chat/stream normalizes resume checkpoint ids into canonical ctx', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('event: done\ndata: {"ok":true}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }),
    )

    const { POST } = await import('@/app/api/chat/stream/route')
    const response = await POST(
      createRequest('http://test/api/chat/stream', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          message: 'continue',
          resume_checkpoint_id: 'ck-stream-1',
          ctx: {
            resumeCheckpointId: 'stale-stream-ck',
          },
        }),
      }),
    )

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(init?.body || '{}'))
    expect(body.ctx.resume_checkpoint_id).toBe('ck-stream-1')
    expect(body.ctx.resumeCheckpointId).toBeUndefined()
    expect(body.ctx.checkpoint_id).toBeUndefined()
    expect(body.resume_checkpoint_id).toBeUndefined()
  })
})
