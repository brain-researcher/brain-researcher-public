// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { makeJsonResponse } from '../helpers/fetch-mocks'

const fetchMock = vi.fn()
const forwardAuthHeadersMock = vi.fn()

global.fetch = fetchMock as typeof fetch

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent.test',
  forwardAuthHeaders: (...args: any[]) => forwardAuthHeadersMock(...args),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: legacy agent proxies', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    forwardAuthHeadersMock.mockReset()
    forwardAuthHeadersMock.mockReturnValue(
      new Headers({
        authorization: 'Bearer test-token',
        cookie: 'session=test',
      }),
    )
  })

  it('GET /api/files resolves through the shared agent base', async () => {
    fetchMock.mockResolvedValueOnce(makeJsonResponse({ items: [] }, 200))

    const { GET } = await import('@/app/api/files/route')
    const res = await GET(createRequest('http://test/api/files'))

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://agent.test/api/files',
      expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers),
      }),
    )
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    expect(headers.get('authorization')).toBe('Bearer test-token')
  })

  it('GET /api/files/[fileId] resolves download through the shared agent base', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('file-bytes', {
        status: 200,
        headers: {
          'content-type': 'application/octet-stream',
          'content-disposition': 'attachment; filename="demo.bin"',
        },
      }),
    )

    const { GET } = await import('@/app/api/files/[fileId]/route')
    const res = await GET(createRequest('http://test/api/files/file_123'), {
      params: { fileId: 'file_123' },
    })

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://agent.test/api/files/file_123',
      expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers),
      }),
    )
    expect(res.headers.get('content-disposition')).toContain('demo.bin')
  })

  it('DELETE /api/files/[fileId] resolves deletion through the shared agent base', async () => {
    fetchMock.mockResolvedValueOnce(makeJsonResponse({ deleted: true }, 200))

    const { DELETE } = await import('@/app/api/files/[fileId]/route')
    const res = await DELETE(createRequest('http://test/api/files/file_123', { method: 'DELETE' }), {
      params: { fileId: 'file_123' },
    })

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://agent.test/api/files/file_123',
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.any(Headers),
      }),
    )
  })

  it('POST /api/datasets/search resolves through the shared agent base', async () => {
    fetchMock.mockResolvedValueOnce(makeJsonResponse({ items: [] }, 200))

    const { POST } = await import('@/app/api/datasets/search/route')
    const res = await POST(
      createRequest('http://test/api/datasets/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query: 'memory' }),
      }),
    )

    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://agent.test/api/datasets/search',
      expect.objectContaining({
        method: 'POST',
        headers: expect.any(Headers),
        body: JSON.stringify({ query: 'memory' }),
      }),
    )
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    expect(headers.get('content-type')).toBe('application/json')
  })

  it('GET dataset detail and quality routes resolve through the shared agent base', async () => {
    fetchMock
      .mockResolvedValueOnce(makeJsonResponse({ id: 'ds1' }, 200))
      .mockResolvedValueOnce(makeJsonResponse({ quality_score: 0.9 }, 200))

    const { GET: getDataset } = await import('@/app/api/datasets/[datasetId]/route')
    const { GET: getQuality } = await import('@/app/api/datasets/[datasetId]/quality/route')

    const datasetRes = await getDataset(createRequest('http://test/api/datasets/ds1'), {
      params: { datasetId: 'ds1' },
    })
    const qualityRes = await getQuality(
      createRequest('http://test/api/datasets/ds1/quality'),
      {
        params: { datasetId: 'ds1' },
      },
    )

    expect(datasetRes.status).toBe(200)
    expect(qualityRes.status).toBe(200)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://agent.test/api/datasets/ds1',
      expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://agent.test/api/datasets/ds1/quality',
      expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers),
        cache: 'no-store',
      }),
    )
  })
})
