// @vitest-environment jsdom
import { render } from '@testing-library/react'
import { ExecutionBlock } from '../execution-block'

describe('ExecutionBlock', () => {
  it('matches snapshot for completed execution', () => {
    const executionBlock = {
      id: 'job_123',
      status: 'completed' as const,
      steps: [
        {
          id: 'step_1',
          name: 'Load data',
          tool: 'tool.load',
          args: { dataset: 'ds001' },
          status: 'completed' as const,
          preview: 'Loaded dataset',
          timing: {
            startTime: new Date('2024-01-01T00:00:00Z'),
            endTime: new Date('2024-01-01T00:00:30Z'),
            duration: 30000
          }
        }
      ],
      artifacts: [],
      startTime: new Date('2024-01-01T00:00:00Z'),
      endTime: new Date('2024-01-01T00:01:30Z'),
      metadata: { pipeline: 'test' }
    }

    const { container } = render(<ExecutionBlock executionBlock={executionBlock} />)
    expect(container).toMatchSnapshot()
  })
})
