import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  resolveAgentBaseUrl,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

const MANAGED_ENV_KEYS = [
  'BR_AGENT_URL',
  'AGENT_BASE_URL',
  'AGENT_URL',
  'AGENT_HOST',
  'AGENT_PORT',
  'NEXT_PUBLIC_AGENT_URL',
  'NEXT_PUBLIC_AGENT_API',
  'BR_ORCHESTRATOR_URL',
  'ORCHESTRATOR_BASE_URL',
  'ORCHESTRATOR_API',
  'ORCHESTRATOR_URL',
  'ORCHESTRATOR_API_URL',
  'ORCHESTRATOR_HOST',
  'ORCHESTRATOR_PORT',
  'NEXT_PUBLIC_ORCHESTRATOR_URL',
  'ORCHESTRATOR_MOUNT_PATH',
  'NEXT_PUBLIC_ORCHESTRATOR_MOUNT_PATH',
  'BR_KG_URL',
  'BR_NEUROKG_URL',
  'KG_BASE_URL',
  'NEUROKG_BASE_URL',
  'KG_URL',
  'NEUROKG_URL',
  'KG_API',
  'NEUROKG_API',
  'KG_HOST',
  'NEUROKG_HOST',
  'KG_PORT',
  'NEUROKG_PORT',
  'NEXT_PUBLIC_BR_KG_API',
  'NEXT_PUBLIC_NEUROKG_API',
  'NEXT_PUBLIC_BR_KG_URL',
  'NEXT_PUBLIC_NEUROKG_URL',
]

const restoreEnv = new Map<string, string | undefined>(
  MANAGED_ENV_KEYS.map((key) => [key, process.env[key]]),
)

afterEach(() => {
  vi.restoreAllMocks()
  for (const key of MANAGED_ENV_KEYS) {
    const value = restoreEnv.get(key)
    if (value == null) {
      delete process.env[key]
    } else {
      process.env[key] = value
    }
  }
})

describe('server downstream resolvers', () => {
  it('prefers internal agent host over NEXT_PUBLIC agent url', () => {
    process.env.AGENT_HOST = 'brain-researcher-agent'
    process.env.AGENT_PORT = '8000'
    process.env.NEXT_PUBLIC_AGENT_URL = 'https://brain-researcher.com'

    expect(resolveAgentBaseUrl()).toBe('http://brain-researcher-agent:8000')
  })

  it('ignores NEXT_PUBLIC agent urls on the server', () => {
    process.env.NEXT_PUBLIC_AGENT_URL = 'https://brain-researcher.com'
    process.env.NEXT_PUBLIC_AGENT_API = 'https://brain-researcher.com/internal-agent'

    expect(resolveAgentBaseUrl()).toBe('http://localhost:8000')
  })

  it('prefers internal orchestrator host over NEXT_PUBLIC orchestrator url', () => {
    process.env.ORCHESTRATOR_HOST = 'brain-researcher-orchestrator'
    process.env.ORCHESTRATOR_PORT = '3001'
    process.env.NEXT_PUBLIC_ORCHESTRATOR_URL = 'https://brain-researcher.com'

    expect(resolveOrchestratorBaseUrl()).toBe('http://brain-researcher-orchestrator:3001')
  })

  it('ignores NEXT_PUBLIC orchestrator mount path on the server', () => {
    process.env.NEXT_PUBLIC_ORCHESTRATOR_MOUNT_PATH = '/legacy-mount'

    expect(resolveOrchestratorBaseUrl()).toBe('http://localhost:3001')
  })

  it('prefers explicit internal BR-KG base over public BR-KG url', () => {
    process.env.BR_KG_URL = 'http://brain-researcher-kg:5000'
    process.env.NEXT_PUBLIC_BR_KG_API = 'https://brain-researcher.com/kg'

    expect(resolveKgBaseUrl()).toBe('http://brain-researcher-kg:5000')
  })

  it('ignores public BR-KG urls on the server', () => {
    process.env.NEXT_PUBLIC_BR_KG_API = 'https://brain-researcher.com/kg'
    process.env.NEXT_PUBLIC_BR_KG_URL = 'https://brain-researcher.com/kg'

    expect(resolveKgBaseUrl()).toBe('http://localhost:5000')
  })
})
