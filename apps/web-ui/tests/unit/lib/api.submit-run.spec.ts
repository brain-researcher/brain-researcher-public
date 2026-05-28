import { beforeEach, describe, expect, it, vi } from 'vitest'

import { submitRun } from '@/lib/api'

const fetchMock = vi.fn()
global.fetch = fetchMock as typeof fetch

describe('submitRun', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('posts chat/coprocess runs through /api/analyses with canonical checkpoint_id', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: 'analysis-123', analysis_id: 'analysis-123' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const response = await submitRun('Continue this analysis', {
      pipeline: 'chat',
      copilot: true,
      scenarioId: 'study_design',
      checkpointId: 'ckpt-123',
      attachments: [{ file_id: 'file-123', name: 'design.pdf' }],
      parameters: { scenario_id: 'study_design' },
    })

    expect(response).toEqual({ job_id: 'analysis-123' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0]?.[0] || '')).toContain('/api/analyses')

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body ?? '{}'))
    expect(body.checkpoint_id).toBe('ckpt-123')
    expect(body.thread).toEqual({ mode: 'none' })
    expect(body.plan).toMatchObject({
      prompt: 'Continue this analysis',
      pipeline: 'chat',
      copilot: true,
      scenario_id: 'study_design',
      attachments: [{ file_id: 'file-123', name: 'design.pdf' }],
      parameters: { scenario_id: 'study_design' },
    })
  })

  it('accepts analysis_id when the analyses facade returns it as the canonical id', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ analysis_id: 'analysis-456' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const response = await submitRun('Run a dataset analysis', {
      pipeline: 'glm',
      datasetId: 'ds000001',
    })

    expect(response).toEqual({ job_id: 'analysis-456' })
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body ?? '{}'))
    expect(body.plan).toMatchObject({
      prompt: 'Run a dataset analysis',
      pipeline: 'glm',
      dataset_id: 'ds000001',
    })
  })
})
