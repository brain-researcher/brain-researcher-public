// @vitest-environment jsdom
import { render } from '@testing-library/react'
import { BranchTimeline } from '../branch-timeline'

describe('BranchTimeline', () => {
  it('matches snapshot with branch events and selected branch', () => {
    const branchEvents = [
      {
        eventType: 'branch_started',
        branchRank: 0,
        branchTool: 'tool.fail',
        branchStepId: 'step-1'
      },
      {
        eventType: 'branch_failed',
        branchRank: 0,
        branchTool: 'tool.fail',
        branchStepId: 'step-1',
        error: 'forced failure'
      },
      {
        eventType: 'branch_succeeded',
        branchRank: 1,
        branchTool: 'tool.success',
        branchStepId: 'step-2'
      }
    ]

    const steps = [
      {
        id: 'step-1',
        name: '',
        tool: 'tool.fail',
        args: {},
        status: 'error' as const,
        branchRank: 0,
        branchGroupId: 'bg:test',
        branchStepId: 'step-1'
      },
      {
        id: 'step-2',
        name: '',
        tool: 'tool.success',
        args: {},
        status: 'success' as const,
        branchRank: 1,
        branchGroupId: 'bg:test',
        branchStepId: 'step-2'
      }
    ]

    const { container } = render(
      <BranchTimeline
        branchEvents={branchEvents}
        plannerState={{ selectedBranchId: 'br:tool.success' }}
        steps={steps}
      />
    )

    expect(container).toMatchSnapshot()
  })

  it('matches snapshot for empty state', () => {
    const { container } = render(<BranchTimeline />)
    expect(container).toMatchSnapshot()
  })

  it('matches snapshot for selected-only with no matching branch', () => {
    const branchEvents = [
      {
        eventType: 'branch_started',
        branchRank: 0,
        branchTool: 'tool.fail',
        branchStepId: 'step-1'
      }
    ]

    const { container } = render(
      <BranchTimeline
        branchEvents={branchEvents}
        plannerState={{ selectedBranchId: 'br:tool.success' }}
        selectedOnly
      />
    )

    expect(container).toMatchSnapshot()
  })
})
