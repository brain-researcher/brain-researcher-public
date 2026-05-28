import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const ENV_KEYS = ['NEXTAUTH_DEBUG', 'BR_AUTH_DEBUG'] as const

let envBackup: Partial<Record<(typeof ENV_KEYS)[number], string | undefined>>

describe('next-auth debug flag', () => {
  beforeEach(() => {
    vi.resetModules()
    envBackup = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]))
    for (const key of ENV_KEYS) {
      delete process.env[key]
    }
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'log').mockImplementation(() => {})
  })

  afterEach(() => {
    for (const key of ENV_KEYS) {
      const value = envBackup[key]
      if (value === undefined) {
        delete process.env[key]
      } else {
        process.env[key] = value
      }
    }
    vi.restoreAllMocks()
  })

  it('defaults to debug disabled when no auth debug env is set', async () => {
    const { authOptions } = await import('@/lib/next-auth-config')
    expect(authOptions.debug).toBe(false)
  })

  it('enables debug when NEXTAUTH_DEBUG is explicitly enabled', async () => {
    process.env.NEXTAUTH_DEBUG = '1'
    vi.resetModules()

    const { authOptions } = await import('@/lib/next-auth-config')
    expect(authOptions.debug).toBe(true)
  })
})

