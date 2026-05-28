import { describe, expect, it } from 'vitest'

import { isPublicPath } from '@/lib/auth/public-paths'

describe('isPublicPath', () => {
  it('treats legal pages as public', () => {
    expect(isPublicPath('/terms')).toBe(true)
    expect(isPublicPath('/privacy')).toBe(true)
  })

  it('treats configured nested catalog routes as public', () => {
    expect(isPublicPath('/datasets/ds000001')).toBe(true)
    expect(isPublicPath('/api/auth/session')).toBe(true)
    expect(isPublicPath('/api/orchestrator/auth/reset-password')).toBe(true)
    expect(isPublicPath('/api/orchestrator/auth/reset-password/extra')).toBe(false)
    expect(isPublicPath('/api/chat')).toBe(true)
    expect(isPublicPath('/api/chat/stream')).toBe(true)
    expect(isPublicPath('/api/files/upload')).toBe(true)
    expect(isPublicPath('/api/datasets/search')).toBe(true)
  })

  it('keeps protected app routes gated', () => {
    expect(isPublicPath('/studio')).toBe(false)
    expect(isPublicPath('/profile')).toBe(false)
  })
})
