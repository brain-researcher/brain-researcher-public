import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ProtectedRoute } from '@/components/auth/protected-route'

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  useAuth: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: mocks.useAuth,
}))

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.routerPush.mockReset()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it('redirects unauthenticated hub visits to /auth/login with callbackUrl', async () => {
    window.history.pushState({}, '', '/hub?session_id=studio_mmX1h3slD')
    mocks.useAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })

    render(
      <ProtectedRoute>
        <div>Protected content</div>
      </ProtectedRoute>,
    )

    expect(screen.getByText('Checking authentication...')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(100)
    })

    await waitFor(() => {
      expect(mocks.routerPush).toHaveBeenCalledWith(
        '/auth/login?callbackUrl=%2Fhub%3Fsession_id%3Dstudio_mmX1h3slD',
      )
    })
  })
})
