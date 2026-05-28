import { fireEvent, render, screen } from '@testing-library/react'
import { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ExplorerDetailsPanel } from '../ExplorerDetailsPanel'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

const baseConcept = {
  id: 'tf_paradigm:tf-preference-affective__sf-affective-bias__affective-spatial-cueing',
  label: 'Affective Spatial Cueing',
}

const renderPanel = (overrides?: Partial<ComponentProps<typeof ExplorerDetailsPanel>>) =>
  render(
    <ExplorerDetailsPanel
      lens="task"
      concept={baseConcept}
      evidence={{ counts: {}, groups: {} }}
      showUnverifiedEvidence
      onShowUnverifiedEvidenceChange={vi.fn()}
      showTaskNeighbors={false}
      onShowTaskNeighborsChange={vi.fn()}
      isLoadingEvidence={false}
      {...overrides}
    />,
  )

describe('ExplorerDetailsPanel sparse layout', () => {
  it('shows an empty state without reading a null selected concept', () => {
    renderPanel({ concept: null })

    expect(screen.getByText('No task selected')).toBeInTheDocument()
    expect(
      screen.getByText('Select a task from the list on the left to view linked datasets and evidence.'),
    ).toBeInTheDocument()
  })

  it('shows overview-only sparse layout when no evidence exists', () => {
    renderPanel()

    expect(screen.getByText('No linked evidence for this entity yet.')).toBeInTheDocument()
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(screen.getByText('Overview')).toBeInTheDocument()
  })

  it('shows only non-empty sections under overview in sparse mode', () => {
    renderPanel({
      evidence: {
        counts: { papers: 1 },
        groups: {
          papers: [{ title: 'Example paper', pmid: '12345', authors: 'A. Author', year: 2024 }],
        },
      },
    })

    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(screen.getByText('Papers')).toBeInTheDocument()
    expect(screen.getByText('Example paper')).toBeInTheDocument()
    expect(screen.queryByText('Datasets')).not.toBeInTheDocument()
  })

  it('uses tabs layout when multiple sections have data', () => {
    renderPanel({
      evidence: {
        counts: { papers: 1, datasets: 1, statmaps: 1 },
        groups: {
          papers: [{ title: 'Dense paper', pmid: '1' }],
          datasets: [{ id: 'ds000001', name: 'Dense dataset' }],
          statmaps: [{ map_id: 'map-1', contrast: 'Dense contrast' }],
        },
      },
    })

    expect(screen.getByRole('tab', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Papers/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Datasets/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Maps/i })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Tools/i })).not.toBeInTheDocument()
  })

  it('supports manual override to tabs layout', () => {
    renderPanel()

    const autoLayoutSwitch = screen.getByLabelText('Auto layout')
    fireEvent.click(autoLayoutSwitch)

    expect(screen.getByRole('tab', { name: 'Overview' })).toBeInTheDocument()
  })
})
