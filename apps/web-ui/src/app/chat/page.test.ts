import { beforeEach, describe, expect, it, vi } from 'vitest'

const redirect = vi.fn()

vi.mock('next/navigation', () => ({
  redirect,
}))

describe('ChatPage', () => {
  beforeEach(() => {
    redirect.mockReset()
  })

  it('redirects chat to hub and preserves query params', async () => {
    const { default: ChatPage } = await import('./page')

    await ChatPage({
      searchParams: Promise.resolve({
        prompt: 'test prompt',
        tab: 'plan',
      }),
    })

    expect(redirect).toHaveBeenCalledWith('/hub?prompt=test+prompt&tab=plan')
  })
})
