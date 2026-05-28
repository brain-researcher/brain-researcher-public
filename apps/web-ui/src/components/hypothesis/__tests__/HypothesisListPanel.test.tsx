import { fireEvent, render, screen } from '@testing-library/react'

import type { HypothesisCandidate } from '@/types/hypothesis'
import { HypothesisListPanel } from '../HypothesisListPanel'

const candidate = (id: string, score: number): HypothesisCandidate => ({
  id,
  title: `Hypothesis ${id}`,
  statement: `Statement for ${id}`,
  status: 'provisional',
  tags: ['bridge'],
  open_question_id: 'q1',
  rationale: null,
  score: {
    total_score: score,
    novelty: score,
    coherence: score,
    leverage: score,
    feasibility: score,
    risk: 1 - score,
  },
  traces: [],
  mde: null,
  evidence: [],
  created_at: null,
  updated_at: null,
})

describe('HypothesisListPanel', () => {
  it('renders empty message when no hypotheses exist', () => {
    render(
      <HypothesisListPanel
        candidates={[]}
        selectedId={null}
        selectedForBatch={new Set()}
        onSelect={vi.fn()}
        onToggleBatch={vi.fn()}
      />,
    )

    expect(screen.getByText('No hypotheses available for this selection.')).toBeInTheDocument()
  })

  it('calls callbacks on selection and batch toggle', () => {
    const onSelect = vi.fn()
    const onToggleBatch = vi.fn()

    render(
      <HypothesisListPanel
        candidates={[candidate('h1', 0.9)]}
        selectedId={null}
        selectedForBatch={new Set()}
        onSelect={onSelect}
        onToggleBatch={onToggleBatch}
      />,
    )

    fireEvent.click(screen.getByText('Hypothesis h1'))
    expect(onSelect).toHaveBeenCalledWith('h1')

    fireEvent.click(screen.getByRole('checkbox', { name: /Select Hypothesis h1 for batch run/i }))
    expect(onToggleBatch).toHaveBeenCalledWith('h1', true)
  })
})
