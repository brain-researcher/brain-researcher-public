import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HubWorkspacePage } from '../HubWorkspacePage'

// Real error class + classifier (defined inside vi.hoisted so they are available
// to the hoisted vi.mock factory below) so the component's retry path behaves
// exactly as in production; only the network calls are mocked.
const mocks = vi.hoisted(() => {
  class HubSessionGatewayError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.name = 'HubSessionGatewayError'
      this.status = status
    }
  }
  return {
    HubSessionGatewayError,
    buildHubWorkspaceHandoff: vi.fn(),
    createOrAttachHubSession: vi.fn(),
    getHubSession: vi.fn(),
    useAuth: vi.fn(),
  }
})

const { HubSessionGatewayError } = mocks

// Return a referentially-stable URLSearchParams per `window.location.search` so
// the component's launchState useMemo doesn't recompute on every render (which
// would otherwise re-fire the launch effect in a loop under the test harness).
const searchParamsCache = new Map<string, URLSearchParams>()
vi.mock('next/navigation', () => ({
  useSearchParams: () => {
    const search = window.location.search
    let params = searchParamsCache.get(search)
    if (!params) {
      params = new URLSearchParams(search)
      searchParamsCache.set(search, params)
    }
    return params
  },
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
  HubSessionGatewayError: mocks.HubSessionGatewayError,
  isRetryableHubGatewayError: (err: unknown) =>
    err instanceof mocks.HubSessionGatewayError && (err.status === 0 || err.status >= 500),
}))

const readyEnvelope = (sessionId: string) => ({
  session: { id: sessionId },
  runtime: { id: `rt_${sessionId}` },
  handoff: {
    workspace_url: `/hub?session_id=${sessionId}`,
    runtime_target_url: `https://brain-researcher.com/hub/br-marimo-${sessionId}`,
    runtime_target_ready: true,
    runtime_connection_mode: 'iframe',
    runtime_target_reason: 'ready',
  },
})

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

  afterEach(() => {
    vi.useRealTimers()
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

  it('auto-retries then succeeds on a transient 5xx gateway error', async () => {
    vi.useFakeTimers()
    window.history.pushState({}, '', '/hub')
    mocks.createOrAttachHubSession
      .mockRejectedValueOnce(
        new HubSessionGatewayError(
          'Hub session gateway request failed: 500 Internal Server Error',
          500,
        ),
      )
      .mockResolvedValueOnce(readyEnvelope('studio_retry5xx'))

    render(<HubWorkspacePage />)

    // Transient reassuring copy is shown, NOT the terminal error card.
    expect(await screen.findByText(/Studio is starting up/)).toBeInTheDocument()
    expect(screen.getByText(/attempt 1 of/)).toBeInTheDocument()
    expect(screen.queryByText('Workspace launch failed')).not.toBeInTheDocument()
    expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(1)

    // Drive past the first backoff and let the retry resolve.
    await vi.advanceTimersByTimeAsync(5000)

    await waitFor(() => {
      expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('Session studio_retry5xx')).toBeInTheDocument()
    expect(screen.queryByText('Workspace launch failed')).not.toBeInTheDocument()
  })

  it('auto-retries then succeeds on a network error (status 0)', async () => {
    vi.useFakeTimers()
    window.history.pushState({}, '', '/hub')
    mocks.createOrAttachHubSession
      .mockRejectedValueOnce(
        new HubSessionGatewayError('Hub session gateway request failed: Failed to fetch', 0),
      )
      .mockResolvedValueOnce(readyEnvelope('studio_retrynet'))

    render(<HubWorkspacePage />)

    expect(await screen.findByText(/Studio is starting up/)).toBeInTheDocument()
    expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5000)

    await waitFor(() => {
      expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('Session studio_retrynet')).toBeInTheDocument()
    expect(screen.queryByText('Workspace launch failed')).not.toBeInTheDocument()
  })

  it('does not auto-retry on a 4xx error (terminal immediately)', async () => {
    window.history.pushState({}, '', '/hub')
    mocks.createOrAttachHubSession.mockRejectedValue(
      new HubSessionGatewayError('Hub session gateway request failed: 403 Forbidden', 403),
    )

    render(<HubWorkspacePage />)

    expect(await screen.findByText('Workspace launch failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText(/Studio is starting up/)).not.toBeInTheDocument()
    expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(1)
  })

  it('falls back to the terminal card after retries are exhausted', async () => {
    vi.useFakeTimers()
    window.history.pushState({}, '', '/hub')
    mocks.createOrAttachHubSession.mockRejectedValue(
      new HubSessionGatewayError(
        'Hub session gateway request failed: 500 Internal Server Error',
        500,
      ),
    )

    render(<HubWorkspacePage />)

    expect(await screen.findByText(/Studio is starting up/)).toBeInTheDocument()

    // Advance through every backoff (max 10s each, 6 retries) plus slack.
    for (let i = 0; i < 7; i += 1) {
      await vi.advanceTimersByTimeAsync(11000)
    }

    await vi.waitFor(() => {
      expect(screen.getByText('Workspace launch failed')).toBeInTheDocument()
    })
    // initial attempt + HUB_LAUNCH_MAX_RETRIES (6) = 7 calls.
    expect(mocks.createOrAttachHubSession).toHaveBeenCalledTimes(7)
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
