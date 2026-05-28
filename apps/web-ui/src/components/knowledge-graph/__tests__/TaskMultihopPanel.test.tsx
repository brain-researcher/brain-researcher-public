import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TaskMultihopPanel } from '../TaskMultihopPanel'

const buildToolResponse = (overrides?: Record<string, unknown>) => ({
  tool: 'kg_multihop_qa',
  result: {
    status: 'success',
    data: {
      answer: 'Found 1 path.',
      summary: {
        n_paths: 1,
        n_seed_entities: 1,
        hops_used: 1,
        max_hops: 2,
      },
      paths: [
        {
          nodes: [{ label: 'Approach Avoidance Task (AAT)' }, { label: 'Emotion' }],
        },
      ],
      warnings: [],
      subgraph: {
        nodes: [],
        edges: [],
      },
      ...overrides,
    },
    error: null,
    metadata: null,
  },
})

describe('TaskMultihopPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('runs kg_multihop_qa and renders summary + paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => buildToolResponse(),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<TaskMultihopPanel taskId="neurostore_task:6avgwnBS3Gut:fmri:0" taskLabel="Approach Avoidance Task (AAT)" />)

    fireEvent.click(screen.getByRole('button', { name: 'Run reasoning' }))

    await screen.findByText('Paths: 1')
    expect(screen.getByText('Found 1 path.')).toBeInTheDocument()
    expect(screen.getByText('Approach Avoidance Task (AAT) -> Emotion')).toBeInTheDocument()

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/tools/run')
    const body = JSON.parse(String(init.body))
    expect(body.tool).toBe('kg_multihop_qa')
    expect(body.arguments.return_subgraph).toBe(false)
    expect(body.arguments.question).toBe('neurostore_task:6avgwnBS3Gut:fmri:0')
  })

  it('expands evidence with return_subgraph=true', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildToolResponse(),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () =>
          buildToolResponse({
            subgraph: {
              nodes: [{ id: 'n1' }, { id: 'n2' }],
              edges: [{ id: 'e1' }],
            },
          }),
      })
    vi.stubGlobal('fetch', fetchMock)

    render(<TaskMultihopPanel taskId="neurostore_task:6avgwnBS3Gut:fmri:0" taskLabel="Approach Avoidance Task (AAT)" />)

    fireEvent.click(screen.getByRole('button', { name: 'Run reasoning' }))
    await screen.findByText('Paths: 1')

    fireEvent.click(screen.getByRole('button', { name: 'Expand evidence' }))
    await screen.findByText('Expanded subgraph: 2 nodes, 1 edges.')

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit]
    const secondBody = JSON.parse(String(secondInit.body))
    expect(secondBody.arguments.return_subgraph).toBe(true)
  })
})

