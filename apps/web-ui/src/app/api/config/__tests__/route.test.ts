// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from '../route'

describe('/api/config route', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  it('returns browser-safe same-origin defaults for agent/orchestrator/websocket', async () => {
    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.agent).toBe('/internal/agent')
    expect(data.services.orchestrator).toBe('')
    expect(data.services.websocket).toBe('/ws')
    expect(data.health.agent).toBe('/api/health')
    expect(data.health.orchestrator).toBe('/health')
  })

  it('preserves explicit public overrides when configured', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_ORCHESTRATOR_URL', 'https://brain-researcher.com')
    vi.stubEnv('NEXT_PUBLIC_AGENT_API', 'https://brain-researcher.com/internal-agent')
    vi.stubEnv('NEXT_PUBLIC_WS_URL', 'wss://brain-researcher.com/ws')

    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.agent).toBe('https://brain-researcher.com/internal-agent')
    expect(data.services.orchestrator).toBe('https://brain-researcher.com')
    expect(data.services.websocket).toBe('wss://brain-researcher.com/ws')
    expect(data.health.orchestrator).toBe('https://brain-researcher.com/health')
  })

  it('keeps browser-safe defaults when proxy mode is enabled even if legacy public vars exist', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'true')
    vi.stubEnv('NEXT_PUBLIC_AGENT_URL', 'https://legacy-agent.example.com')
    vi.stubEnv('NEXT_PUBLIC_ORCHESTRATOR_URL', 'https://legacy-orchestrator.example.com')

    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.agent).toBe('/internal/agent')
    expect(data.services.orchestrator).toBe('')
    expect(data.health.orchestrator).toBe('/health')
  })

  it('ignores legacy NEXT_PUBLIC_AGENT_URL when proxy mode is disabled', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_AGENT_URL', 'https://legacy-agent.example.com')

    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.agent).toBe('/internal/agent')
  })

  it('ignores legacy NEXT_PUBLIC_API_URL when proxy mode is disabled', async () => {
    vi.stubEnv('NEXT_PUBLIC_USE_API_PROXY', 'false')
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://legacy-api.example.com')

    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.orchestrator).toBe('')
    expect(data.health.orchestrator).toBe('/health')
  })

  it('derives NICLIP health from the configured public NICLIP base', async () => {
    vi.stubEnv('NEXT_PUBLIC_NICLIP_API', 'https://niclip.example.com/api')

    const response = await GET()
    expect(response.status).toBe(200)

    const data = await response.json()
    expect(data.services.niclip).toBe('https://niclip.example.com/api')
    expect(data.health.niclip).toBe('https://niclip.example.com/api/health')
  })
})
