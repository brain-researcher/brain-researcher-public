import { beforeEach, describe, expect, it, vi } from 'vitest'

const redirect = vi.fn()

vi.mock('next/navigation', () => ({
  redirect,
}))

describe('StudioPage', () => {
  beforeEach(() => {
    redirect.mockReset()
  })

  it('redirects studio to hub and preserves query params', async () => {
    const { default: StudioPage } = await import('./page')

    await StudioPage({
      searchParams: Promise.resolve({
        prompt: 'test prompt',
        project: 'proj_demo',
      }),
    })

    expect(redirect).toHaveBeenCalledWith('/hub?prompt=test+prompt&project=proj_demo')
  })
})
