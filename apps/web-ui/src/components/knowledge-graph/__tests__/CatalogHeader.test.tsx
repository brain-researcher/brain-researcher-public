import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { CatalogHeader } from '../CatalogHeader'

describe('CatalogHeader', () => {
  const baseSummary = {
    id: 'ONVOC_0000001',
    label: 'Behaviors',
    status: 'online' as const,
    features: {
      statmaps: 2,
      coords: 1,
      timeseries: 0,
      datasets: 0,
      papers: 0,
    },
    spaces: [],
    atlases: [],
    origin: 'neo4j',
  }

  it('renders ontology metrics when present', () => {
    render(
      <CatalogHeader
        summary={{
          ...baseSummary,
          ontology: { parents: 1, children: 3, classified_neighbors: 4 },
        }}
        onToggle={() => {}}
      />
    )

    expect(screen.getByText('Ontology')).toBeInTheDocument()
    expect(screen.getByText('parents (1)')).toBeInTheDocument()
    expect(screen.getByText('children (3)')).toBeInTheDocument()
    expect(screen.getByText('neighbors (4)')).toBeInTheDocument()
  })

  it('does not render ontology metrics when absent or zero', () => {
    render(<CatalogHeader summary={baseSummary} onToggle={() => {}} />)
    expect(screen.queryByText('Ontology')).not.toBeInTheDocument()
  })

  it('defaults status badge to unknown when summary status is missing', () => {
    const { status: _status, ...summaryWithoutStatus } = baseSummary
    render(<CatalogHeader summary={summaryWithoutStatus} onToggle={() => {}} />)
    expect(screen.getByText(/^unknown$/i)).toBeInTheDocument()
  })

  it('exposes KG-local search as the primary search action', () => {
    const onSearchData = vi.fn()
    render(
      <CatalogHeader
        summary={baseSummary}
        onToggle={() => {}}
        onPrimary={{ onSearchData }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Search KG' }))
    expect(onSearchData).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Search Data' })).not.toBeInTheDocument()
  })
})
