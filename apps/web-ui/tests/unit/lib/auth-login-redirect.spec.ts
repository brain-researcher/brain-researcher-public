import { describe, expect, it } from 'vitest'

import {
  buildAuthLoginHref,
  sanitizeAuthCallbackUrl,
} from '@/lib/auth/login-redirect'

describe('auth login redirect helpers', () => {
  it('keeps same-origin in-app callback paths', () => {
    expect(sanitizeAuthCallbackUrl('/hub?session_id=studio_mmX1h3slD')).toBe(
      '/hub?session_id=studio_mmX1h3slD',
    )
  })

  it('rejects empty, external, and auth-prefixed callback paths', () => {
    expect(sanitizeAuthCallbackUrl()).toBe('/')
    expect(sanitizeAuthCallbackUrl('https://example.com')).toBe('/')
    expect(sanitizeAuthCallbackUrl('/auth/login?callbackUrl=%2Fhub')).toBe('/')
  })

  it('builds /auth/login URLs with encoded callbackUrl', () => {
    expect(buildAuthLoginHref('/hub?session_id=studio_mmX1h3slD')).toBe(
      '/auth/login?callbackUrl=%2Fhub%3Fsession_id%3Dstudio_mmX1h3slD',
    )
  })
})
