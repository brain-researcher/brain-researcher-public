import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJsonResponse, queueFetchMock } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()

global.fetch = mockFetch

describe('BrainResearcherAPI copilot/chat fallback behavior', () => {
  beforeEach(() => {
    mockFetch.mockReset()
    queueFetchMock(mockFetch, [], { authSessionResponse: { data: null } })
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'true')
    vi.stubEnv('NEXT_PUBLIC_ORCHESTRATOR_URL', 'http://orchestrator.local')
  })

  it('prefers proxy copilot endpoint first, then falls back to absolute orchestrator endpoint', async () => {
    const payload = {
      query: 'hello',
      metadata: {},
      k: 5,
      exposures: ['chat'],
      domain: undefined,
      function: undefined,
      risk: undefined,
    }

    queueFetchMock(mockFetch, [
      new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
      makeJsonResponse({
        suggestions: [
          {
            name: 'dataset',
            description: 'desc',
            reason: 'reason',
            score: 1.2,
            autocomplete: { dataset_id: 'motor_task_sample' },
          },
        ],
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const result = await brainResearcherAPI.copilotSuggest('hello', {}, 5, {
      exposures: ['chat'],
    })

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      '/copilot/suggest',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      }),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      '/api/auth/session',
      expect.objectContaining({}),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      'http://orchestrator.local/copilot/suggest',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(mockFetch).toHaveBeenCalledTimes(3)
    expect(result.suggestions[0].name).toBe('dataset')
  })

  it('routes copilot autocomplete through proxy first, then orchestrator only', async () => {
    queueFetchMock(mockFetch, [
      new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
      makeJsonResponse({
        tool: 'spm-glm',
        completed: { TR: 2.0 },
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const result = await brainResearcherAPI.copilotAutocomplete(
      'spm-glm',
      { threshold: 0.001 },
      { repetition_time: 2.0 },
    )

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      '/copilot/autocomplete',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          tool: 'spm-glm',
          params: { threshold: 0.001 },
          metadata: { repetition_time: 2.0 },
        }),
      }),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      '/api/auth/session',
      expect.objectContaining({}),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      'http://orchestrator.local/copilot/autocomplete',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(mockFetch).toHaveBeenCalledTimes(3)
    expect(result).toEqual({ tool: 'spm-glm', completed: { TR: 2.0 } })
  })

  it('routes copilot learn through proxy first, then orchestrator only', async () => {
    queueFetchMock(mockFetch, [
      new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
      makeJsonResponse({
        status: 'ok',
        tool: 'spm-glm',
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const result = await brainResearcherAPI.copilotLearn('spm-glm', { TR: 2.0 })

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      '/copilot/learn',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ tool: 'spm-glm', params: { TR: 2.0 } }),
      }),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      '/api/auth/session',
      expect.objectContaining({}),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      'http://orchestrator.local/copilot/learn',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(mockFetch).toHaveBeenCalledTimes(3)
    expect(result).toEqual({ status: 'ok', tool: 'spm-glm' })
  })

  it('returns chat message from /api/chat when backend responds successfully', async () => {
    queueFetchMock(mockFetch, [
      makeJsonResponse({
        message: {
          content: 'How can I help with your analysis?',
        },
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const text = await brainResearcherAPI.chat('How to run analysis?')

    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ message: 'How to run analysis?' }),
      }),
    )
    expect(text).toBe('How can I help with your analysis?')
  })

  it('sends copilot system constraint metadata when copilot mode is requested', async () => {
    queueFetchMock(mockFetch, [
      makeJsonResponse({
        message: {
          content: 'Hi! How can I help?',
        },
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const text = await brainResearcherAPI.chat('hi', { copilot: true })

    expect(mockFetch).toHaveBeenCalledTimes(1)
    const call = mockFetch.mock.calls[0]
    const body = JSON.parse(String(call?.[1]?.body || '{}'))
    expect(body.message).toBe('hi')
    expect(body.copilot).toBe(true)
    expect(body.metadata?.copilot).toBe(true)
    expect(body.metadata?.ui_surface).toBe('studio_copilot')
    expect(Array.isArray(body.messages)).toBe(true)
    expect(body.messages[0]?.role).toBe('system')
    expect(String(body.messages[0]?.content || '').toLowerCase()).toContain(
      'brain researcher copilot',
    )
    expect(body.messages[1]).toEqual({ role: 'user', content: 'hi' })
    expect(text).toBe('Hi! How can I help?')
  })

  it('returns a readable message for auth errors instead of local fallback', async () => {
    queueFetchMock(mockFetch, [
      makeJsonResponse(
        {
          message: {
            content: 'No response (login required).',
          },
        },
        401,
      ),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const text = await brainResearcherAPI.chat('hi')

    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(text).toBe('No response (login required).')
  })

  it('routes active BR-KG search methods through same-origin proxy paths', async () => {
    queueFetchMock(mockFetch, [
      makeJsonResponse({
        results: [{ node_id: 'concept:wm', properties: { name: 'working memory' } }],
      }),
      makeJsonResponse({
        nodes: [{ id: 'concept:wm' }],
        edges: [],
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const nodes = await brainResearcherAPI.searchNodes('working memory', {
      nodeTypes: ['Concept'],
      limit: 10,
    })
    const expanded = await brainResearcherAPI.expandNode('working memory', 'Concept', 2)

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      '/api/neurokg/search?query=working+memory&limit=10&types=Concept',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: 'working memory',
          types: ['Concept'],
          limit: 10,
        }),
      }),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      '/api/neurokg/subgraph?label=Concept&name=working+memory&depth=2',
    )
    expect(nodes).toHaveLength(1)
    expect(expanded).toEqual({ nodes: [{ id: 'concept:wm' }], edges: [] })
  })

  it('routes thread creation through the orchestrator base resolved by shared helpers', async () => {
    queueFetchMock(mockFetch, [
      makeJsonResponse({
        thread_id: 'thread_123',
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const result = await brainResearcherAPI.createThread()

    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://orchestrator.local/threads',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      }),
    )
    expect(result).toEqual({ thread_id: 'thread_123' })
  })

  it('falls back to the shared internal agent proxy for direct tool execution', async () => {
    queueFetchMock(mockFetch, [
      new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
      makeJsonResponse({
        result: { status: 'ok' },
      }),
    ])

    vi.resetModules()
    const { brainResearcherAPI } = await import('@/lib/brain-researcher-api')

    const result = await brainResearcherAPI.runAnalysis('glm_fit', { threshold: 0.001 })

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      'http://orchestrator.local/run',
      expect.objectContaining({
        method: 'POST',
      }),
    )
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      '/internal/agent/api/tools/glm_fit/execute',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters: { threshold: 0.001 } }),
      }),
    )
    expect(result).toEqual({ result: { status: 'ok' } })
  })
})
