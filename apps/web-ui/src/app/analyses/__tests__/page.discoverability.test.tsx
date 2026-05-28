import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AnalysesGonePage from '../page'

const authMocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
}))

vi.mock('@/components/navigation/navigation-wrapper', () => ({
  NavigationWrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: authMocks.useAuth,
}))

describe('AnalysesGonePage', () => {
  beforeEach(() => {
    authMocks.useAuth.mockReset()
  })

  it('shows "Open Studio" CTA when the user is authenticated', () => {
    authMocks.useAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
    })

    render(<AnalysesGonePage />)
    expect(
      screen.getByRole('heading', { name: /Runs has moved into Studio/i }),
    ).toBeInTheDocument()
    const open = screen.getByRole('link', { name: /Open Studio/i }) as HTMLAnchorElement
    expect(open.getAttribute('href')).toBe('/hub')
  })

  it('shows sign-in CTA when the user is anonymous', () => {
    authMocks.useAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
    })

    render(<AnalysesGonePage />)
    expect(
      screen.getByText(/Sign in to see your runs in Studio/i),
    ).toBeInTheDocument()
    const signIn = screen.getByRole('link', { name: /Sign in/i }) as HTMLAnchorElement
    expect(signIn.getAttribute('href')).toBe('/auth/login?callbackUrl=/hub')
  })

  it('shows a loading hint while auth state is resolving', () => {
    authMocks.useAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
    })

    render(<AnalysesGonePage />)
    expect(screen.getByText(/Checking your session/i)).toBeInTheDocument()
  })
})
