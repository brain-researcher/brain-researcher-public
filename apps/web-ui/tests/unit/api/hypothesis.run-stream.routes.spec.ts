import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createRun,
  emitAssistantMessage,
  emitRunState,
  markRunClarifying,
} from '@/lib/server/hypothesis-run-store'
import { executeHypothesisRun } from '@/lib/server/hypothesis-runner'

vi.mock('@/lib/server/hypothesis-runner', () => ({
  executeHypothesisRun: vi.fn(),
}))

function createRequest(url: string, options: RequestInit = {}) {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: hypothesis run + stream', () => {
  const executeHypothesisRunMock = vi.mocked(executeHypothesisRun)
  const originalMaxPollsEnv = process.env.HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS
  const originalUiWaitEnv = process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC
  const originalBackgroundCapEnv = process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC
  const originalKgFirstEnv = process.env.HYPOTHESIS_KG_FIRST
  const originalKgTimeoutEnv = process.env.HYPOTHESIS_KG_TIMEOUT_SEC
  const originalKgPromptTopKEnv = process.env.HYPOTHESIS_KG_PROMPT_TOPK
  const originalKgPromptMaxCharsEnv = process.env.HYPOTHESIS_KG_PROMPT_MAX_CHARS

  beforeEach(() => {
    vi.clearAllMocks()
    executeHypothesisRunMock.mockResolvedValue(undefined)
  })

  afterEach(() => {
    if (originalMaxPollsEnv === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS = originalMaxPollsEnv
    }
    if (originalUiWaitEnv === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC = originalUiWaitEnv
    }
    if (originalBackgroundCapEnv === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC = originalBackgroundCapEnv
    }
    if (originalKgFirstEnv === undefined) {
      delete process.env.HYPOTHESIS_KG_FIRST
    } else {
      process.env.HYPOTHESIS_KG_FIRST = originalKgFirstEnv
    }
    if (originalKgTimeoutEnv === undefined) {
      delete process.env.HYPOTHESIS_KG_TIMEOUT_SEC
    } else {
      process.env.HYPOTHESIS_KG_TIMEOUT_SEC = originalKgTimeoutEnv
    }
    if (originalKgPromptTopKEnv === undefined) {
      delete process.env.HYPOTHESIS_KG_PROMPT_TOPK
    } else {
      process.env.HYPOTHESIS_KG_PROMPT_TOPK = originalKgPromptTopKEnv
    }
    if (originalKgPromptMaxCharsEnv === undefined) {
      delete process.env.HYPOTHESIS_KG_PROMPT_MAX_CHARS
    } else {
      process.env.HYPOTHESIS_KG_PROMPT_MAX_CHARS = originalKgPromptMaxCharsEnv
    }
  })

  it('POST /api/hypothesis/run rejects missing fields', async () => {
    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ session_id: 'sess_1' }),
    })

    const res = await POST(req)
    expect(res.status).toBe(400)
  })

  it('POST /api/hypothesis/run starts a run and returns run metadata', async () => {
    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2',
        message: 'working memory mechanism fMRI in healthy adults',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)

    const payload = await res.json()
    expect(payload.run_id).toMatch(/^hrun-/)
    expect(payload.session_id).toBe('sess_2')
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
  })

  it('POST /api/hypothesis/run forwards body deep_research_max_polls=0 as unlimited', async () => {
    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2b',
        message: 'working memory mechanism fMRI in healthy adults',
        deep_research_max_polls: 0,
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.maxPolls).toBe(0)
  })

  it('POST /api/hypothesis/run forwards env HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS=0 as unlimited', async () => {
    process.env.HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS = '0'

    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2c',
        message: 'working memory mechanism fMRI in healthy adults',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.maxPolls).toBe(0)
  })

  it('POST /api/hypothesis/run forwards deep research UI wait and background cap settings', async () => {
    process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC = '300'
    process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC = '21600'

    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2d',
        message: 'working memory mechanism fMRI in healthy adults',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.uiWaitSec).toBe(300)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.backgroundCapSec).toBe(
      21600,
    )
  })

  it('POST /api/hypothesis/run forwards n_candidates to runner', async () => {
    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2d-candidates',
        message: 'working memory mechanism fMRI in healthy adults',
        n_candidates: 12,
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.nCandidates).toBe(12)
  })

  it('POST /api/hypothesis/run forwards KG orchestration options to runner', async () => {
    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_kg_orch',
        message: 'working memory mechanism fMRI in healthy adults',
        kg_first: true,
        kg_timeout_sec: 120,
        kg_prompt_topk: 8,
        kg_prompt_max_chars: 1500,
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.kgOrchestrationOptions).toMatchObject({
      kgFirst: true,
      timeoutSec: 120,
      promptTopK: 8,
      promptMaxChars: 1500,
    })
  })

  it('POST /api/hypothesis/run prioritizes body deep research wait settings over env defaults', async () => {
    process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC = '300'
    process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC = '21600'

    const { POST } = await import('@/app/api/hypothesis/run/route')
    const req = createRequest('http://test/api/hypothesis/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: 'sess_2e',
        message: 'working memory mechanism fMRI in healthy adults',
        deep_research_ui_wait_sec: 120,
        deep_research_background_cap_sec: 3600,
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(executeHypothesisRunMock).toHaveBeenCalledTimes(1)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.uiWaitSec).toBe(120)
    expect(executeHypothesisRunMock.mock.calls[0]?.[0]?.deepResearchOptions?.backgroundCapSec).toBe(
      3600,
    )
  })

  it('GET /api/hypothesis/run/:runId/stream emits snapshot and done for completed run', async () => {
    const run = createRun({
      sessionId: 'sess_stream',
      state: 'clarifying',
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

    emitRunState(run.run_id, 'clarifying', 'Waiting for clarification')
    emitAssistantMessage(run.run_id, 'Please specify your goal and modality.')
    markRunClarifying(run.run_id, 'Need more detail before execution.')

    const { GET } = await import('@/app/api/hypothesis/run/[runId]/stream/route')
    const req = createRequest(
      `http://test/api/hypothesis/run/${encodeURIComponent(run.run_id)}/stream`,
    )

    const res = await GET(req, { params: { runId: run.run_id } })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('text/event-stream')

    const text = await res.text()
    expect(text).toContain('event: snapshot')
    expect(text).toContain('event: done')
  })
})
