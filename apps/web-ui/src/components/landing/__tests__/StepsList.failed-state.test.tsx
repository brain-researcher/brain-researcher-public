import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getJSON, openSSE } from '@/lib/api'
import { StepsList } from '../StepsList'

vi.mock('@/lib/api', () => ({
  getJSON: vi.fn(),
  openSSE: vi.fn(),
}))

describe('StepsList failed terminal state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not render pending/logs-unavailable for a failed placeholder step', async () => {
    vi.mocked(getJSON).mockResolvedValueOnce({
      job_id: 'job_failed_no_logs',
      state: 'failed',
      steps: [
        {
          step_id: 'step_001',
          name: '1. workflow_rest_connectome_e2e',
          state: 'pending',
          error: 'ToolExecutor unavailable for plan execution',
        },
      ],
    })

    render(<StepsList jobId="job_failed_no_logs" enableStreaming={false} />)

    expect(await screen.findByText('Job failed')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('No step logs captured')).toBeInTheDocument()
    expect(screen.queryByText('Pending')).not.toBeInTheDocument()
    expect(screen.queryByText('Logs unavailable')).not.toBeInTheDocument()
    expect(openSSE).not.toHaveBeenCalled()
  })
})
