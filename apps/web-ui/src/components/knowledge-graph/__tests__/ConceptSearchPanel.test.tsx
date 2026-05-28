// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConceptSearchPanel } from '../ConceptSearchPanel'

const baseTree = [{ id: 'concept:working_memory', label: 'Working memory', depth: 0 }]

describe('ConceptSearchPanel no-result guidance', () => {
  it('shows seed suggestions and can hand a broad query to MCP', () => {
    const onSearchChange = vi.fn()
    const onUseSearchInMcp = vi.fn()

    render(
      <ConceptSearchPanel
        searchQuery="default mode network fMRI"
        onSearchChange={onSearchChange}
        filteredTree={[]}
        conceptTree={baseTree}
        selectedConceptId={null}
        expandedNodes={new Set()}
        loadingNodes={new Set()}
        onToggleNode={vi.fn()}
        onSelectConcept={vi.fn()}
        searchSuggestions={[
          { label: 'resting-state fMRI' },
          { label: 'atlas extraction', query: 'atlas-based signal extraction' },
        ]}
        onUseSearchInMcp={onUseSearchInMcp}
      />,
    )

    expect(screen.getByText('Try seed terms')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'atlas extraction' }))
    expect(onSearchChange).toHaveBeenCalledWith('atlas-based signal extraction')

    fireEvent.click(screen.getByRole('button', { name: 'Use this query in MCP' }))
    expect(onUseSearchInMcp).toHaveBeenCalledWith('default mode network fMRI')
  })
})
