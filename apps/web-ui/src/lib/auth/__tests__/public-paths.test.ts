import { afterEach, describe, expect, it, vi } from 'vitest'

describe('isPublicPath', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('treats /studio as public in local development', async () => {
    vi.stubEnv('NODE_ENV', 'development')

    const { isPublicPath } = await import('../public-paths')

    expect(isPublicPath('/studio')).toBe(true)
    expect(isPublicPath('/studio/plan-preview')).toBe(true)
  })

  it('keeps /studio protected in production by default', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_STUDIO_PUBLIC_DEV', '')

    const { isPublicPath } = await import('../public-paths')

    expect(isPublicPath('/studio')).toBe(false)
  })

  it('allows an explicit env override for public studio access', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_STUDIO_PUBLIC_DEV', 'true')

    const { isPublicPath } = await import('../public-paths')

    expect(isPublicPath('/studio')).toBe(true)
  })

  it('keeps SEO and auth recovery routes public', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_STUDIO_PUBLIC_DEV', '')

    const { isPublicPath } = await import('../public-paths')

    expect(isPublicPath('/robots.txt')).toBe(true)
    expect(isPublicPath('/sitemap.xml')).toBe(true)
    expect(isPublicPath('/auth/forgot')).toBe(true)
    expect(isPublicPath('/understand-br')).toBe(true)
    expect(isPublicPath('/understand-br/extra')).toBe(false)
    expect(isPublicPath('/api/orchestrator/auth/reset-password')).toBe(true)
    expect(isPublicPath('/api/orchestrator/auth/reset-password/extra')).toBe(false)
    expect(isPublicPath('/api/chat')).toBe(true)
    expect(isPublicPath('/api/chat/stream')).toBe(true)
    expect(isPublicPath('/api/files/upload')).toBe(true)
    expect(isPublicPath('/api/datasets/search')).toBe(true)
    expect(isPublicPath('/vault/datasets')).toBe(true)
    expect(isPublicPath('/vault/datasets/extra')).toBe(false)
    expect(isPublicPath('/studio/plan-preview')).toBe(true)
    expect(isPublicPath('/mcp/setup')).toBe(true)
    expect(isPublicPath('/mcp/setup/codex')).toBe(true)
    expect(isPublicPath('/mcp')).toBe(false)
  })
})
