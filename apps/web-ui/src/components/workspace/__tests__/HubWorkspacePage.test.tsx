import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HubWorkspacePage } from '../HubWorkspacePage'

const mocks = vi.hoisted(() => ({
  buildHubWorkspaceHandoff: vi.fn(),
  createOrAttachHubSession: vi.fn(),
  getHubSession: vi.fn(),
  useAuth: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('@/components/auth/protected-route', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/components/navigation/navigation-wrapper', () => ({
  NavigationWrapper: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/api/hub-sessions', () => ({
  buildHubWorkspaceHandoff: mocks.buildHubWorkspaceHandoff,
  createOrAttachHubSession: mocks.createOrAttachHubSession,
  getHubSession: mocks.getHubSession,
}))

describe('HubWorkspacePage', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/hub?session_id=studio_stale123')
    mocks.useAuth.mockReturnValue({
      accessToken: 'test-token',
      isLoading: false,
    })
    mocks.getHubSession.mockReset()
    mocks.buildHubWorkspaceHandoff.mockReset()
    mocks.createOrAttachHubSession.mockReset()
  })

  it('falls back to a fresh hub session when the requested session is missing', async () => {
    const missingError = new Error('Hub session gateway request failed: Hub session not found')
    mocks.getHubSession.mockRejectedValue(missingError)
    mocks.buildHubWorkspaceHandoff.mockRejectedValue(missingError)
    mocks.createOrAttachHubSession.mockResolvedValue({
      session: { id: 'studio_fresh456' },
      runtime: { id: 'rt_fresh456' },
      handoff: {
        workspace_url: '/hub?session_id=studio_fresh456',
        runtime_target_url: 'https://brain-researcher.com/hub/br-marimo-rt-fresh456',
        runtime_target_ready: true,
        runtime_connection_mode: 'iframe',
        runtime_target_reason: 'ready',
      },
    })

    render(<HubWorkspacePage />)

    await waitFor(() => {
      expect(mocks.createOrAttachHubSession).toHaveBeenCalledWith(
        expect.objectContaining({
          project_id: 'proj_workspace',
          display_name: 'Hosted Workspace',
          attach_if_exists: true,
        }),
        { accessToken: 'test-token' },
      )
    })

    expect(await screen.findByText('Session studio_fresh456')).toBeInTheDocument()
    expect(screen.queryByText('Workspace launch failed')).not.toBeInTheDocument()
    expect(window.location.search).toBe('?session_id=studio_fresh456')
  })
})
