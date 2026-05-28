import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MessageList } from '../message-list'
import { Message } from '@/types/chat'

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    type: 'assistant',
    content: 'done',
    timestamp: new Date(),
    ...overrides,
  }
}

describe('MessageList resume checkpoint', () => {
  it('renders resume button and calls handler with checkpoint id', () => {
    const handler = vi.fn()
    const msg = makeMessage({ lastCheckpointId: 'ck-123' })

    render(
      <MessageList
        messages={[msg]}
        onResumeFromCheckpoint={handler}
      />
    )

    const button = screen.getByTestId('resume-from-checkpoint')
    fireEvent.click(button)
    expect(handler).toHaveBeenCalledWith('ck-123')
  })
})

describe('MessageList kg_multihop_qa rendering', () => {
  it('renders multihop tool card when tool_calls include kg_multihop_qa', () => {
    const msg = makeMessage({
      metadata: {
        tool_calls: [
          {
            name: 'kg_multihop_qa',
            arguments: { question: 'How is memory linked to attention?', max_hops: 3 },
            result_preview: {
              summary: 'Found plausible bridges.',
              summary_stats: { n_paths: 2, max_hops: 3, hops_used: 2, n_seed_entities: 3 },
              top_paths: [
                'Memory -> Frontoparietal -> Attention',
                'Memory -> DLPFC -> Attention',
              ],
              warnings: ['One seed was low confidence'],
              expand_args: {
                question: 'How is memory linked to attention?',
                max_hops: 3,
                return_subgraph: true,
              },
            },
            result: {
              outputs: {
                answer: 'Found plausible bridges.',
              },
            },
          },
        ],
      },
    })

    render(<MessageList messages={[msg]} />)

    expect(screen.getByText('Tool result: kg_multihop_qa')).toBeInTheDocument()
    expect(screen.getByText('Found plausible bridges.')).toBeInTheDocument()
    expect(screen.getByText('Memory -> Frontoparietal -> Attention')).toBeInTheDocument()
    expect(screen.getByText('One seed was low confidence')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand evidence' })).toBeInTheDocument()
  })

  it('prefers top-level payload fields over outputs', () => {
    const msg = makeMessage({
      metadata: {
        tool_calls: [
          {
            name: 'kg_multihop_qa',
            arguments: { question: 'memory attention', max_hops: 3 },
            result: {
              summary: { n_paths: 1, max_hops: 3, hops_used: 2, n_seed_entities: 4 },
              answer: 'Top-level answer',
              paths: [{ nodes: [{ label: 'Top A' }, { label: 'Top B' }] }],
              warnings: ['Top-level warning'],
              subgraph: { nodes: [{ id: 'n1' }], edges: [] },
              outputs: {
                summary: { n_paths: 8, max_hops: 8, hops_used: 8, n_seed_entities: 8 },
                answer: 'Output answer',
                paths: [{ nodes: [{ label: 'Output A' }, { label: 'Output B' }] }],
                warnings: ['Output warning'],
                subgraph: { nodes: [], edges: [] },
              },
            },
          },
        ],
      },
    })

    render(<MessageList messages={[msg]} />)

    expect(screen.getByText('Top-level answer')).toBeInTheDocument()
    expect(screen.queryByText('Output answer')).not.toBeInTheDocument()
    expect(screen.getByText('Top A -> Top B')).toBeInTheDocument()
    expect(screen.queryByText('Output A -> Output B')).not.toBeInTheDocument()
    expect(screen.getByText('Top-level warning')).toBeInTheDocument()
    expect(screen.queryByText('Output warning')).not.toBeInTheDocument()
    expect(screen.getByText('Paths: 1')).toBeInTheDocument()
  })

  it('falls back to outputs when top-level payload fields are absent', () => {
    const msg = makeMessage({
      metadata: {
        tool_calls: [
          {
            name: 'kg_multihop_qa',
            result: {
              outputs: {
                answer: 'Output fallback answer',
                paths: [{ nodes: [{ label: 'Output A' }, { label: 'Output B' }] }],
                warnings: ['Output fallback warning'],
              },
            },
          },
        ],
      },
    })

    render(<MessageList messages={[msg]} />)

    expect(screen.getByText('Output fallback answer')).toBeInTheDocument()
    expect(screen.getByText('Output A -> Output B')).toBeInTheDocument()
    expect(screen.getByText('Output fallback warning')).toBeInTheDocument()
  })

  it('expands evidence via /api/tools/run', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        result: {
          summary: { n_paths: 1, max_hops: 2 },
          subgraph: {
            nodes: [{ id: 'n1' }, { id: 'n2' }],
            edges: [{ source: 'n1', target: 'n2' }],
          },
          warnings: [],
        },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const msg = makeMessage({
      metadata: {
        tool_calls: [
          {
            name: 'kg_multihop_qa',
            arguments: { question: 'memory attention', max_hops: 2 },
            result_preview: {
              summary_stats: { n_paths: 1, max_hops: 2 },
              top_paths: ['Memory -> Attention'],
              expand_args: { question: 'memory attention', max_hops: 2, return_subgraph: true },
            },
            result: {
              outputs: {
                answer: 'Done',
              },
            },
          },
        ],
      },
    })

    render(<MessageList messages={[msg]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Expand evidence' }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/tools/run',
        expect.objectContaining({
          method: 'POST',
        }),
      )
    })

    expect(await screen.findByText('Expanded subgraph')).toBeInTheDocument()
    expect(screen.getByText('Nodes: 2 | Edges: 1')).toBeInTheDocument()

    vi.unstubAllGlobals()
  })
})

describe('MessageList repair proposal rendering', () => {
  it('renders a RepairCard for valid repair json and wires actions', () => {
    const onApplyRepair = vi.fn()
    const onRevalidateRepair = vi.fn()
    const onHandOffRepair = vi.fn()

    const msg = makeMessage({
      content: [
        'The validation run failed because the smoothing kernel is too high for this dataset.',
        'Apply a smaller kernel and retry on the same sample.',
        '```json',
        JSON.stringify(
          {
            plan_patch: {
              parameter_overrides: {
                smoothing_fwhm: 4,
              },
            },
            recipe_patch_preview: 'Set smoothing_fwhm=4 in the GLM step before retrying.',
            validation_intent: 'Re-run validation with the smaller smoothing kernel.',
            handoff: {
              required: true,
              reason: 'Escalate if the reduced setting still fails in validation.',
            },
          },
          null,
          2,
        ),
        '```',
      ].join('\n'),
      metadata: {
        repair_request: true,
        repair_context: {
          repair_attempt_count: 2,
        },
      },
    })

    render(
      <MessageList
        messages={[msg]}
        onApplyRepair={onApplyRepair}
        onRevalidateRepair={onRevalidateRepair}
        onHandOffRepair={onHandOffRepair}
      />,
    )

    expect(screen.getByTestId('repair-card')).toBeInTheDocument()
    expect(screen.getAllByText(/smoothing kernel is too high/i).length).toBeGreaterThan(0)
    expect(screen.getByText('Plan/config changes')).toBeInTheDocument()
    expect(screen.queryByText(/plan_patch/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Apply fix' }))
    expect(onApplyRepair).toHaveBeenCalledWith(
      expect.objectContaining({
        validationIntent: 'Re-run validation with the smaller smoothing kernel.',
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Re-validate' }))
    expect(onRevalidateRepair).toHaveBeenCalledWith(
      expect.objectContaining({
        handoff: expect.objectContaining({ required: true }),
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Hand off to IDE' }))
    expect(onHandOffRepair).toHaveBeenCalled()
  })

  it('falls back to plain assistant content when repair json is invalid', () => {
    const msg = makeMessage({
      content: 'Try reducing smoothing.\n```json\n{ invalid json }\n```',
      metadata: {
        repair_request: true,
      },
    })

    render(<MessageList messages={[msg]} />)

    expect(screen.queryByTestId('repair-card')).not.toBeInTheDocument()
    expect(screen.getByText(/Try reducing smoothing/i)).toBeInTheDocument()
  })
})

describe('MessageList coding progress rendering', () => {
  it('renders terminal coding events as compact summaries instead of raw json', () => {
    const msg = makeMessage({
      metadata: {
        coding_events: [
          {
            type: 'done',
            data: {
              thread_id: 'thread-1',
              total_length: 128,
            },
          },
          {
            type: 'stream_end',
            data: {},
          },
        ],
      },
    })

    render(<MessageList messages={[msg]} />)

    expect(screen.getByText('Completed (128 chars)')).toBeInTheDocument()
    expect(screen.getByText('Stream ended')).toBeInTheDocument()
    expect(screen.queryByText(/thread_id/)).not.toBeInTheDocument()
  })
})
