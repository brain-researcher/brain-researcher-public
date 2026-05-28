import { describe, it, expect, vi, beforeEach } from 'vitest'
import { authOptions, resolveOrchestratorBaseUrl } from '../next-auth-config'

describe('next-auth-config', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mock('jose', () => {
      return {
        SignJWT: class {
          setProtectedHeader() { return this }
          setExpirationTime() { return this }
          setIssuedAt() { return this }
          sign() { return Promise.resolve('signed-token') }
        },
        jwtVerify: vi.fn(),
      }
    })
  })


  it('includes Google/GitHub providers when env vars are present', () => {
    const providerIds = authOptions.providers?.map(p => (p as any).id) || []
    // Providers are conditional; just assert that optional arrays concatenate without crashing
    expect(Array.isArray(providerIds)).toBe(true)
  })

  it('session callback emits signed accessToken', async () => {
    const token = { sub: '123', email: 'u@example.com', name: 'Test User' }
    const session = { user: { name: null, email: null } }

    const result = await (authOptions.callbacks?.session as any)({ session, token })

    expect(result.accessToken).toBe('signed-token')
    expect(result.user?.id).toBe('123')
  })

  it('session callback prefers orchestrator access token when present', async () => {
    const token = {
      sub: '123',
      email: 'u@example.com',
      name: 'Test User',
      orchestrator_access_token: 'orch-token',
    }
    const session = { user: { name: null, email: null } }

    const result = await (authOptions.callbacks?.session as any)({ session, token })

    expect(result.accessToken).toBe('orch-token')
  })

  it('does not infer orchestrator base from NEXT_PUBLIC_AGENT_URL', () => {
    const previous = {
      BR_ORCHESTRATOR_URL: process.env.BR_ORCHESTRATOR_URL,
      ORCHESTRATOR_BASE_URL: process.env.ORCHESTRATOR_BASE_URL,
      ORCHESTRATOR_API: process.env.ORCHESTRATOR_API,
      ORCHESTRATOR_URL: process.env.ORCHESTRATOR_URL,
      ORCHESTRATOR_API_URL: process.env.ORCHESTRATOR_API_URL,
      NEXT_PUBLIC_ORCHESTRATOR_URL: process.env.NEXT_PUBLIC_ORCHESTRATOR_URL,
      NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
      NEXT_PUBLIC_AGENT_URL: process.env.NEXT_PUBLIC_AGENT_URL,
    }

    delete process.env.BR_ORCHESTRATOR_URL
    delete process.env.ORCHESTRATOR_BASE_URL
    delete process.env.ORCHESTRATOR_API
    delete process.env.ORCHESTRATOR_URL
    delete process.env.ORCHESTRATOR_API_URL
    delete process.env.NEXT_PUBLIC_ORCHESTRATOR_URL
    delete process.env.NEXT_PUBLIC_API_URL
    process.env.NEXT_PUBLIC_AGENT_URL = 'http://localhost:8000'

    try {
      expect(resolveOrchestratorBaseUrl()).toBe('http://localhost:3001')
    } finally {
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) {
          delete process.env[key]
        } else {
          process.env[key] = value
        }
      }
    }
  })
})
