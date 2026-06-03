import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('serviceEndpoints BR-KG proxy defaults', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
    window.history.replaceState({}, '', 'http://localhost:3000/')
  })

  it('defaults browser BR-KG requests to same-origin proxy when no override is set', async () => {
    vi.stubEnv('NEXT_PUBLIC_BR_KG_API', 'http://localhost:5000')

    const { serviceEndpoints, resolveKgLensTaskTreeUrl } = await import('@/lib/service-endpoints')
    const params = new URLSearchParams({
      limit: '2000',
      include_unmapped: 'true',
    })

    expect(serviceEndpoints.useProxy).toBe(true)
    expect(resolveKgLensTaskTreeUrl(params)).toBe(
      '/api/kg/lens/task/tree?limit=2000&include_unmapped=true',
    )
  })

  it('still respects an explicit proxy disable override', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_BR_KG_API', 'http://localhost:5000')

    const {
      serviceEndpoints,
      resolveKgApiUrl,
      resolveKgLensTaskTreeUrl,
      resolveKgRootUrl,
    } = await import('@/lib/service-endpoints')
    const params = new URLSearchParams({
      limit: '2000',
    })

    expect(serviceEndpoints.useProxy).toBe(false)
    expect(resolveKgLensTaskTreeUrl(params)).toBe(
      'http://localhost:5000/api/kg/lens/task/tree?limit=2000',
    )
    expect(resolveKgApiUrl('statistics')).toBe('http://localhost:5000/api/statistics')
    expect(resolveKgRootUrl('subgraph', params)).toBe(
      'http://localhost:5000/subgraph?limit=2000',
    )
  })

  it('routes browser BR-KG api and root paths through same-origin helpers', async () => {
    vi.stubEnv('NEXT_PUBLIC_BR_KG_API', 'http://localhost:5000')

    const { resolveKgApiUrl, resolveKgRootUrl } = await import('@/lib/service-endpoints')
    const params = new URLSearchParams({
      label: 'Concept',
      name: 'working memory',
    })

    expect(resolveKgApiUrl('statistics')).toBe('/api/br-kg/statistics')
    expect(resolveKgApiUrl('openneuro/datasets')).toBe('/api/br-kg/openneuro/datasets')
    expect(resolveKgRootUrl('subgraph', params)).toBe(
      '/api/br-kg/subgraph?label=Concept&name=working+memory',
    )
  })

  it('keeps browser HTTP traffic proxied but bypasses Next dev for local websocket traffic', async () => {
    const {
      serviceEndpoints,
      resolveDashboardWsUrl,
      resolveRealtimeWsBaseUrl,
    } = await import('@/lib/service-endpoints')

    expect(serviceEndpoints.useProxy).toBe(true)
    expect(serviceEndpoints.agentBase).toBe('/internal/agent')
    expect(serviceEndpoints.orchestratorBase).toBe('')
    expect(resolveRealtimeWsBaseUrl()).toBe('ws://localhost:3001/ws')
    expect(resolveDashboardWsUrl()).toBe('ws://localhost:3001/ws/dashboard')
  })

  it('respects an explicit websocket override even in local browser proxy mode', async () => {
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'wss://${PUBLIC_HOSTNAME}/ws')

    const { resolveDashboardWsUrl, resolveRealtimeWsBaseUrl } = await import('@/lib/service-endpoints')

    expect(resolveRealtimeWsBaseUrl()).toBe('wss://${PUBLIC_HOSTNAME}/ws')
    expect(resolveDashboardWsUrl()).toBe('wss://${PUBLIC_HOSTNAME}/ws/dashboard')
  })
})
