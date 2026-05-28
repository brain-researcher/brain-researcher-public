import { NextRequest, NextResponse } from 'next/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { proxyHypothesis } from '@/lib/server/hypothesis-proxy'
import {
  __resetHypothesisLocalMemoryStoreForTests,
} from '@/lib/server/hypothesis-local-store'
import { __resetHypothesisPersistenceForTests } from '@/lib/server/hypothesis-persistence'

vi.mock('@/lib/server/hypothesis-proxy', () => ({
  proxyHypothesis: vi.fn(),
  shouldFallbackToLocalHypothesis: (status: number) =>
    [404, 502, 503, 504].includes(status),
}))

function createRequest(url: string, options: RequestInit = {}) {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: hypothesis proxies', () => {
  const proxyMock = vi.mocked(proxyHypothesis)

  beforeEach(async () => {
    vi.resetAllMocks()
    __resetHypothesisLocalMemoryStoreForTests()
    await __resetHypothesisPersistenceForTests()
    proxyMock.mockResolvedValue(
      NextResponse.json({ ok: true }, { status: 200 }),
    )
  })

  it('GET /api/hypothesis/session delegates to upstream session endpoint', async () => {
    const { GET } = await import('@/app/api/hypothesis/session/route')
    const req = createRequest('http://test/api/hypothesis/session?datasetId=ds_demo')
    await GET(req)

    expect(proxyMock).toHaveBeenCalledTimes(1)
    const [, options] = proxyMock.mock.calls[0]
    expect(options).toMatchObject({ method: 'GET', pathname: '/session' })
  })

  it('POST /api/hypothesis/explore mirrors upstream candidates into local persisted session', async () => {
    proxyMock.mockResolvedValueOnce(
      NextResponse.json(
        {
          session_id: 'sess_explore_mirror',
          open_questions: [
            {
              id: 'oq-upstream',
              title: 'Upstream question',
              description: 'Question from upstream explore.',
              status: 'open',
              priority: 'high',
            },
          ],
          candidates: [
            {
              id: 'hyp-upstream-1',
              title: 'Upstream direction',
              statement: 'Evidence-backed candidate from upstream explore.',
              status: 'provisional',
              score: {
                total_score: 0.78,
                novelty: 0.8,
                coherence: 0.76,
                leverage: 0.79,
                feasibility: 0.7,
                risk: 0.2,
              },
            },
          ],
          messages: [
            {
              id: 'msg-upstream-1',
              role: 'assistant',
              content: 'Seeded from explore.',
              timestamp: '2026-02-20T00:00:00.000Z',
            },
          ],
        },
        { status: 200 },
      ),
    )

    const { POST: postExplore } = await import('@/app/api/hypothesis/explore/route')
    const exploreRes = await postExplore(
      createRequest('http://test/api/hypothesis/explore', {
        method: 'POST',
        body: JSON.stringify({ session_id: 'sess_explore_mirror', n_candidates: 4 }),
        headers: { 'content-type': 'application/json' },
      }),
    )
    expect(exploreRes.status).toBe(200)

    proxyMock.mockResolvedValueOnce(
      NextResponse.json(
        {
          session_id: 'sess_explore_mirror',
          context: { session_id: 'sess_explore_mirror' },
          open_questions: [],
          candidates: [],
          messages: [],
          runs: [],
        },
        { status: 200 },
      ),
    )

    const { GET: getSession } = await import('@/app/api/hypothesis/session/route')
    const sessionRes = await getSession(
      createRequest('http://test/api/hypothesis/session?sessionId=sess_explore_mirror'),
    )
    expect(sessionRes.status).toBe(200)
    const sessionPayload = await sessionRes.json()
    const candidates = Array.isArray(sessionPayload.candidates) ? sessionPayload.candidates : []
    const messages = Array.isArray(sessionPayload.messages) ? sessionPayload.messages : []
    const openQuestions = Array.isArray(sessionPayload.open_questions)
      ? sessionPayload.open_questions
      : []

    expect(candidates.some((item: any) => item?.id === 'hyp-upstream-1')).toBe(true)
    expect(messages.some((item: any) => item?.id === 'msg-upstream-1')).toBe(true)
    expect(openQuestions.some((item: any) => item?.id === 'oq-upstream')).toBe(true)
  })

  it('GET /api/hypothesis/session merges persisted hypothesis runs by session id', async () => {
    const { createRun, markRunCompleted } = await import('@/lib/server/hypothesis-run-store')
    const run = createRun({
      sessionId: 'sess_merge_runs',
      state: 'running',
      intentSummary: {
        term: 'brain decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
    })
    markRunCompleted(run.run_id, 'done')

    proxyMock.mockResolvedValueOnce(
      NextResponse.json(
        {
          session_id: 'sess_merge_runs',
          context: { session_id: 'sess_merge_runs' },
          runs: [],
        },
        { status: 200 },
      ),
    )

    const { GET } = await import('@/app/api/hypothesis/session/route')
    const req = createRequest('http://test/api/hypothesis/session?sessionId=sess_merge_runs')
    const res = await GET(req)
    expect(res.status).toBe(200)
    const payload = await res.json()
    const runs = Array.isArray(payload.runs) ? payload.runs : []
    expect(runs.some((item: any) => item?.run_id === run.run_id)).toBe(true)
  })

  it('POST /api/hypothesis/chat rejects missing message', async () => {
    const { POST } = await import('@/app/api/hypothesis/chat/route')
    const req = createRequest('http://test/api/hypothesis/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: 'sess_1' }),
      headers: { 'content-type': 'application/json' },
    })

    const res = await POST(req)
    expect(res.status).toBe(400)
    expect(proxyMock).not.toHaveBeenCalled()
  })

  it('POST /api/hypothesis/chat delegates when payload is valid', async () => {
    const { POST } = await import('@/app/api/hypothesis/chat/route')
    const req = createRequest('http://test/api/hypothesis/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: 'sess_1', message: 'improve mde' }),
      headers: { 'content-type': 'application/json' },
    })

    await POST(req)

    expect(proxyMock).toHaveBeenCalledTimes(1)
    const [, options] = proxyMock.mock.calls[0]
    expect(options).toMatchObject({ method: 'POST', pathname: '/chat' })
    expect((options as any).body.session_id).toBe('sess_1')
  })

  it('POST /api/hypothesis/run-batch rejects missing ids', async () => {
    const { POST } = await import('@/app/api/hypothesis/run-batch/route')
    const req = createRequest('http://test/api/hypothesis/run-batch', {
      method: 'POST',
      body: JSON.stringify({ session_id: 'sess_2' }),
      headers: { 'content-type': 'application/json' },
    })

    const res = await POST(req)
    expect(res.status).toBe(400)
    expect(proxyMock).not.toHaveBeenCalled()
  })

  it('POST /api/hypothesis/run-batch normalizes selected_ids', async () => {
    const { POST } = await import('@/app/api/hypothesis/run-batch/route')
    const req = createRequest('http://test/api/hypothesis/run-batch', {
      method: 'POST',
      body: JSON.stringify({ session_id: 'sess_2', selected_ids: ['h1', 'h2'] }),
      headers: { 'content-type': 'application/json' },
    })

    await POST(req)

    expect(proxyMock).toHaveBeenCalledTimes(1)
    const [, options] = proxyMock.mock.calls[0]
    expect(options).toMatchObject({ method: 'POST', pathname: '/run-batch' })
    expect((options as any).body.hypothesis_ids).toEqual(['h1', 'h2'])
  })

  it('GET /api/hypothesis/run/:runId delegates with encoded run id', async () => {
    const { GET } = await import('@/app/api/hypothesis/run/[runId]/route')
    const req = createRequest('http://test/api/hypothesis/run/run%201')

    await GET(req, { params: { runId: 'run 1' } })

    expect(proxyMock).toHaveBeenCalledTimes(1)
    const [, options] = proxyMock.mock.calls[0]
    expect(options).toMatchObject({ method: 'GET', pathname: '/run/run%201' })
  })

  it('GET /api/hypothesis/run/:runId returns local stream snapshot for hrun ids', async () => {
    const { createRun } = await import('@/lib/server/hypothesis-run-store')
    const run = createRun({
      sessionId: 'sess_local',
      state: 'running',
      intentSummary: {
        term: 'working memory',
        goal: null,
        modality: null,
        population: null,
        output_mode: null,
        intent_ready: false,
        missing_fields: ['goal_or_output_mode'],
      },
    })

    const { GET } = await import('@/app/api/hypothesis/run/[runId]/route')
    const req = createRequest(`http://test/api/hypothesis/run/${encodeURIComponent(run.run_id)}`)
    const res = await GET(req, { params: { runId: run.run_id } })

    expect(res.status).toBe(200)
    const payload = await res.json()
    expect(payload.run?.run_id).toBe(run.run_id)
    expect(proxyMock).not.toHaveBeenCalled()
  })

  it('restores fallback chat messages across refresh for the same session id', async () => {
    proxyMock.mockResolvedValue(NextResponse.json({ detail: 'upstream unavailable' }, { status: 502 }))

    const { GET: getSession } = await import('@/app/api/hypothesis/session/route')
    const { POST: postChat } = await import('@/app/api/hypothesis/chat/route')

    const sessionId = 'sess_refresh_restore'

    const first = await getSession(
      createRequest(`http://test/api/hypothesis/session?sessionId=${sessionId}`),
    )
    expect(first.status).toBe(200)

    const chatRes = await postChat(
      createRequest('http://test/api/hypothesis/chat', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, message: 'test persistence message' }),
        headers: { 'content-type': 'application/json' },
      }),
    )
    expect(chatRes.status).toBe(200)

    const refreshed = await getSession(
      createRequest(`http://test/api/hypothesis/session?sessionId=${sessionId}`),
    )
    expect(refreshed.status).toBe(200)
    const refreshedPayload = await refreshed.json()
    const messages = Array.isArray(refreshedPayload.messages) ? refreshedPayload.messages : []

    expect(messages.length).toBeGreaterThanOrEqual(2)
    expect(messages.some((item: any) => item.role === 'user' && /test persistence/i.test(item.content))).toBe(true)
    expect(messages.some((item: any) => item.role === 'assistant')).toBe(true)
  })
})
