// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LandingPageStatic from '../landing-page-static'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  fetchWorkflowCatalog: vi.fn(),
  useAuth: vi.fn(),
  useSession: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
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

vi.mock('@/lib/brain-researcher-api', () => ({
  brainResearcherAPI: {
    fetchWorkflowCatalog: (...args: unknown[]) => mocks.fetchWorkflowCatalog(...args),
  },
}))

describe('LandingPageStatic', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.fetchWorkflowCatalog.mockResolvedValue({ workflows: [] })
    mocks.useAuth.mockReturnValue({ isAuthenticated: false, isLoading: false })
    mocks.useSession.mockReturnValue({ data: null, status: 'unauthenticated' })
  })

  it('routes Try with your own question through signup for public unauthenticated users', async () => {
    render(<LandingPageStatic />)

    const link = screen.getByRole('link', { name: 'Try with your own question' })
    expect(link).toHaveAttribute(
      'href',
      '/auth/signup?callbackUrl=%2Fstudio%2Fplan-preview',
    )
    await waitFor(() => expect(mocks.fetchWorkflowCatalog).toHaveBeenCalled())
  })

  it('links Try with your own question to the preview directly for authenticated users', async () => {
    mocks.useAuth.mockReturnValue({ isAuthenticated: true, isLoading: false })
    mocks.useSession.mockReturnValue({
      data: { user: { email: 'user@example.com' } },
      status: 'authenticated',
    })

    render(<LandingPageStatic />)

    const link = screen.getByRole('link', { name: 'Try with your own question' })
    expect(link).toHaveAttribute('href', '/studio/plan-preview')
    await waitFor(() => expect(mocks.fetchWorkflowCatalog).toHaveBeenCalled())
  })
})
