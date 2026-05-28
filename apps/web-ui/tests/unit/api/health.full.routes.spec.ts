// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent.primary:8000',
}))

const fetchMock = vi.fn()
global.fetch = fetchMock as typeof fetch

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: health/full proxy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    delete process.env.AGENT_HOST
    delete process.env.AGENT_PORT
    delete process.env.POD_NAMESPACE
    delete process.env.K8S_NAMESPACE
  })

  it('tries the shared agent base first', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const { GET } = await import('@/app/api/health/full/route')
    const response = await GET(createRequest('http://test/api/health/full'))

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith('http://agent.primary:8000/api/health/full', {
      cache: 'no-store',
    })
  })

  it('falls back to host and namespaced host when the primary base fails', async () => {
    process.env.AGENT_HOST = 'agent-host'
    process.env.AGENT_PORT = '9000'
    process.env.POD_NAMESPACE = 'br-test'

    fetchMock
      .mockRejectedValueOnce(new Error('primary failed'))
      .mockRejectedValueOnce(new Error('host failed'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )

    const { GET } = await import('@/app/api/health/full/route')
    const response = await GET(createRequest('http://test/api/health/full'))

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://agent.primary:8000/api/health/full',
      { cache: 'no-store' },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://agent-host:9000/api/health/full',
      { cache: 'no-store' },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://agent-host.br-test.svc.cluster.local:9000/api/health/full',
      { cache: 'no-store' },
    )
  })
})
