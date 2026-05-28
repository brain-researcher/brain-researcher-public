import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LinearKnowledgeGraph } from '../LinearKnowledgeGraph'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
  }),
}))

vi.mock('../CytoscapeGraph', () => ({
  CytoscapeGraph: () => <div data-testid="cytoscape-graph" />,
}))

vi.mock('../KnowledgeGraphChatModal', () => ({
  KnowledgeGraphChatModal: () => null,
}))

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('LinearKnowledgeGraph task tree payloads', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    window.sessionStorage.clear()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/health')) {
          return jsonResponse({ status: 'ok' })
        }
        if (url.includes('/api/kg/lens/task/tree')) {
          return jsonResponse({
            families: [
              null,
              {
                id: null,
                label: null,
                task_count: 1,
                children: [
                  null,
                  {
                    id: null,
                    label: null,
                    task_count: 1,
                    children: [
                      null,
                      {
                        id: null,
                        label: null,
                        display_label: null,
                        collapsed_count: 1,
                      },
                    ],
                  },
                ],
              },
            ],
          })
        }
        return jsonResponse({})
      }),
    )
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('sanitizes null task tree entries instead of crashing on labels', async () => {
    render(<LinearKnowledgeGraph lens="task" />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })

    expect(screen.getByText('Task Families')).toBeInTheDocument()
    expect(screen.getByText('family-0')).toBeInTheDocument()
    expect(screen.getByText('family-0:subfamily-0')).toBeInTheDocument()
  })
})
