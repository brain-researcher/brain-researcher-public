import { afterEach, beforeEach, describe, expect, it } from 'vitest'

const loadRoutes = async () => {
  const baseMod = await import('@/app/api/viz/demo/base/route')
  const overlayMod = await import('@/app/api/viz/demo/overlay/route')
  return { base: baseMod.GET, overlay: overlayMod.GET }
}

describe('api/viz/demo routes', () => {
  beforeEach(() => {
    // no-op
  })

  afterEach(() => {
    // no-op
  })

  it('base route returns demo_disabled', async () => {
    const { base } = await loadRoutes()
    const res = await base()
    expect(res.status).toBe(410)
    const payload = await res.json()
    expect(payload).toMatchObject({ error: 'demo_disabled' })
  })

  it('overlay route returns demo_disabled', async () => {
    const { overlay } = await loadRoutes()
    const res = await overlay()
    expect(res.status).toBe(410)
    const payload = await res.json()
    expect(payload).toMatchObject({ error: 'demo_disabled' })
  })
})
