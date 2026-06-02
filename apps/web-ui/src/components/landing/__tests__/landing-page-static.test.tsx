// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LandingPageStatic from '../landing-page-static'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useSession: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('next-auth/react', () => ({
  useSession: () => mocks.useSession(),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => mocks.useAuth(),
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mocks.toast }),
}))

// The landing renders the full site navigation (search, notifications, user menu,
// connection status). That tree is exercised by its own tests; here we stub it so
// these tests stay focused on the landing's own hero/CTA content.
vi.mock('@/components/authenticated-navigation', () => ({
  AuthenticatedNavigation: () => null,
}))
vi.mock('@/components/navigation/navigation-header', () => ({
  NavigationHeader: () => null,
}))

describe('LandingPageStatic', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.useAuth.mockReturnValue({ isAuthenticated: false, isLoading: false })
    mocks.useSession.mockReturnValue({ data: null, status: 'unauthenticated' })
  })

  it('renders the BR product banner and a coming-soon code placeholder', () => {
    render(<LandingPageStatic />)

    expect(screen.getByRole('heading', { level: 1, name: 'Brain Researcher' })).toBeVisible()
    expect(screen.getAllByText(/AI-assisted research infrastructure/i)[0]).toBeVisible()
    expect(screen.getAllByText(/for neuroimaging/i)[0]).toBeVisible()
    expect(screen.getByText('1,600+')).toBeVisible()
    expect(screen.getByText('datasets')).toBeVisible()
    expect(screen.getByText('2,000+')).toBeVisible()
    expect(screen.getByText('tool specs')).toBeVisible()

    // Code repo is a placeholder until the OSS release: no live GitHub link yet.
    expect(screen.queryByRole('link', { name: /Open on GitHub/i })).toBeNull()
    expect(screen.getByText(/Open-source release coming soon/i)).toBeVisible()
  })

  it('gates the Studio entry point behind signup for unauthenticated users', () => {
    render(<LandingPageStatic />)

    const openStudio = screen.getByRole('link', { name: 'Open Studio' })
    expect(openStudio).toHaveAttribute('href', '/auth/signup?callbackUrl=%2Fstudio')
  })

  it('links the Studio entry point directly for authenticated users', () => {
    mocks.useAuth.mockReturnValue({ isAuthenticated: true, isLoading: false })
    mocks.useSession.mockReturnValue({
      data: { user: { email: 'user@example.com' } },
      status: 'authenticated',
    })

    render(<LandingPageStatic />)

    const openStudio = screen.getByRole('link', { name: 'Open Studio' })
    expect(openStudio).toHaveAttribute('href', '/studio')
  })
})
