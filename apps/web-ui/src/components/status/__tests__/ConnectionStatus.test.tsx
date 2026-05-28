// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { ConnectionStatus } from '../ConnectionStatus'

vi.mock('@/lib/service-endpoints', () => ({
  serviceEndpoints: {
    agent: (path: string) => `/api/agent${path}`,
    kg: (path: string) => `/api/kg${path}`,
    orchestrator: (path: string) => `/api${path}`,
  },
  resolveAgentHealthUrl: () => '/api/health',
  resolveKgHealthUrl: () => '/api/kg/health',
}))

describe('ConnectionStatus', () => {
  it('shows healthy when agent + BR-KG healthy', async () => {
    if (!(AbortSignal as any).timeout) {
      ;(AbortSignal as any).timeout = (_ms: number) => new AbortController().signal
    }

    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ status: 'healthy' }),
    }))

    vi.stubGlobal('fetch', fetchMock as any)

    const { unmount } = render(<ConnectionStatus />)

    expect(await screen.findByText('All systems operational')).toBeInTheDocument()
    expect(screen.queryByText('Service issues detected')).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/kg/health',
      expect.objectContaining({ method: 'GET' }),
    )

    unmount()
  })
})
