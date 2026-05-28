import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const ENV_KEYS = [
  'NODE_ENV',
  'BR_AUTH_DEBUG',
  'NEXTAUTH_DEBUG',
  'JWT_SECRET_KEY',
  'NEXTAUTH_SECRET',
] as const

let envBackup: Partial<Record<(typeof ENV_KEYS)[number], string | undefined>>
const tempDirs: string[] = []

const createRepoRoot = (repoSecret: string): string => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'br-shared-jwt-'))
  tempDirs.push(dir)
  fs.mkdirSync(path.join(dir, '.git'))
  fs.writeFileSync(path.join(dir, '.env.local'), `JWT_SECRET_KEY=${repoSecret}\n`, 'utf-8')
  return dir
}

const setEnv = (key: (typeof ENV_KEYS)[number], value: string): void => {
  ;(process.env as Record<string, string | undefined>)[key] = value
}

describe('resolveSharedJwtSecret warnings', () => {
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
    vi.restoreAllMocks()
    for (const dir of tempDirs.splice(0)) {
      fs.rmSync(dir, { recursive: true, force: true })
    }
    for (const key of ENV_KEYS) {
      const value = envBackup[key]
      if (value === undefined) {
        delete process.env[key]
      } else {
        setEnv(key, value)
      }
    }
  })

  it('does not warn on mismatch in non-debug test/dev mode', async () => {
    const repoRoot = createRepoRoot('repo-secret')
    vi.spyOn(process, 'cwd').mockReturnValue(repoRoot)

    setEnv('NODE_ENV', 'test')
    setEnv('JWT_SECRET_KEY', 'env-secret')

    const { resolveSharedJwtSecret } = await import('@/lib/server/shared-jwt-secret')
    const resolved = resolveSharedJwtSecret()

    expect(resolved).toBe('repo-secret')
    expect(console.warn).not.toHaveBeenCalled()
  })

  it('keeps mismatch warning when explicit auth debug is enabled', async () => {
    const repoRoot = createRepoRoot('repo-secret')
    vi.spyOn(process, 'cwd').mockReturnValue(repoRoot)

    setEnv('NODE_ENV', 'test')
    setEnv('JWT_SECRET_KEY', 'env-secret')
    setEnv('NEXTAUTH_DEBUG', '1')

    const { resolveSharedJwtSecret } = await import('@/lib/server/shared-jwt-secret')
    const resolved = resolveSharedJwtSecret()

    expect(resolved).toBe('repo-secret')
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('JWT_SECRET_KEY differs from repo-root JWT_SECRET_KEY'),
    )
  })
})
