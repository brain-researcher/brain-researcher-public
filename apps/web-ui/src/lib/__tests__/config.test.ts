import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('config agent public base resolution', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
    delete (window as any).__ENV
  })

  it('defaults browser agent traffic to the same-origin proxy', async () => {
    const { SERVICE_URLS, USE_API_PROXY } = await import('@/lib/config')

    expect(USE_API_PROXY).toBe(true)
    expect(SERVICE_URLS.AGENT).toBe('/internal/agent')
  })

  it('uses NEXT_PUBLIC_AGENT_API when proxy mode is disabled', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_AGENT_API', 'https://brain-researcher.com/internal-agent')

    const { SERVICE_URLS } = await import('@/lib/config')

    expect(SERVICE_URLS.AGENT).toBe('https://brain-researcher.com/internal-agent')
  })

  it('ignores legacy NEXT_PUBLIC_AGENT_URL in browser config resolution', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_AGENT_URL', 'https://legacy-agent.example.com')

    const { SERVICE_URLS } = await import('@/lib/config')

    expect(SERVICE_URLS.AGENT).toBe('http://localhost:8000')
  })
})
