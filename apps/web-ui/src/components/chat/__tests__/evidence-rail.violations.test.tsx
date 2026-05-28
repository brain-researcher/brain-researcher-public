import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { EvidenceRail } from '../evidence-rail'

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() })
}))

vi.mock('@/hooks/use-advanced-mode', () => ({
  useAdvancedMode: () => ({ enabled: false })
}))

// Let the real hook run, but stub fetch to return observation with violations.
const mockObservation = {
  run_card: {},
  steps: [],
  artifacts: [],
  diagnostics_summary: null,
  violations: [
    {
      schema_version: 'violation-v1',
      code: 'QC_MISSING_T1W',
      message: 'No T1w image found',
      severity: 'critical',
      blocking: true,
      where: { stage: 'preflight', step_id: 'step_1' }
    }
  ]
}

describe('EvidenceRail violations card', () => {
  beforeEach(() => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockObservation,
    })) as any
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders violations with severity badges', async () => {
    render(<EvidenceRail jobId="job123" />)

    await waitFor(() => {
      expect(screen.getByText('Violations')).toBeInTheDocument()
    })
    expect(screen.getByText('QC_MISSING_T1W')).toBeInTheDocument()
    expect(screen.getAllByText(/blocking/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/preflight/i).length).toBeGreaterThan(0)
  })
})
