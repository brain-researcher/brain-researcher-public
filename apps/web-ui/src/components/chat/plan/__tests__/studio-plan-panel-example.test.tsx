// @vitest-environment jsdom
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StudioPlanPanelExample } from '../studio-plan-panel-example'

describe('StudioPlanPanelExample', () => {
  it('renders a notebook-style execution preview without picker/configure controls or credits UI', () => {
    render(<StudioPlanPanelExample />)

    expect(screen.getByText('Notebook-style Studio preview')).toBeInTheDocument()
    expect(screen.getByText('Natural-language intent drives the run')).toBeInTheDocument()
    expect(screen.getByText('The agent translates chat into an executable workflow')).toBeInTheDocument()
    expect(screen.getByText('Plan stays a compact approval cell')).toBeInTheDocument()
    expect(screen.getByText('Focused inspector')).toBeInTheDocument()
    expect(screen.getByText('ds000114 · v1.0.1')).toBeInTheDocument()
    expect(screen.getByText('Rest connectome')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Motion QC overview' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /change dataset/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /configure/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/credits/i)).not.toBeInTheDocument()
  })

  it('updates the right inspector when a different artifact is selected from the notebook stream', () => {
    render(<StudioPlanPanelExample />)

    expect(screen.getByRole('heading', { name: 'Motion QC overview' })).toBeInTheDocument()
    expect(
      screen.queryByText('Posterior cingulate to insula coupling is the highest-ranked effect.'),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Top network effects/i }))

    expect(screen.getByRole('heading', { name: 'Top network effects' })).toBeInTheDocument()
    expect(screen.getByText('Posterior cingulate to insula coupling is the highest-ranked effect.')).toBeInTheDocument()
  })
})
