import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import { makeJsonResponse } from '../helpers/fetch-mocks'

describe('buildAnalysisDetail artifacts fallback', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('falls back to /api/jobs/{id}/artifacts when observation artifacts are empty', async () => {
    const analysisId = 'job_test_artifacts'
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith(`/api/jobs/${analysisId}`)) {
          return makeJsonResponse({
            job_id: analysisId,
            run_id: analysisId,
            status: 'succeeded',
            created_at: 1772000000,
            started_at: 1772000010,
            finished_at: 1772000020,
            payload_json: JSON.stringify({
              parameters: {
                dataset_id: 'ds000001',
                analysis_id: 'connectivity',
                pipeline_id: 'test',
              },
            }),
          })
        }
        if (url.endsWith(`/api/jobs/${analysisId}/observation`)) {
          return makeJsonResponse({
            artifacts: [],
            run_card: {
              inputs: {
                parameters: {},
              },
            },
          })
        }
        if (url.endsWith(`/api/jobs/${analysisId}/artifacts`)) {
          return makeJsonResponse({
            artifacts: [
              {
                id: 'artifact_0001',
                name: 'connectivity_matrix.npy',
                path: 'outputs/nilearn_connectivity/connectivity_matrix.npy',
              },
            ],
          })
        }
        if (url.endsWith(`/api/jobs/${analysisId}/runcard`)) {
          return makeJsonResponse(
            {
              detail: 'not found',
            },
            404,
          )
        }
        return makeJsonResponse({ detail: `unexpected url: ${url}` }, 404)
      })

    const headers = new Headers()
    const result = await buildAnalysisDetail({ analysisId, headers })

    expect(fetchMock).toHaveBeenCalled()
    expect(result.ok).toBe(true)
    if (!result.ok) {
      throw new Error('expected successful detail build')
    }
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/api/runs/'))).toBe(false)
    expect(Array.isArray(result.detail.artifacts)).toBe(true)
    expect(result.detail.artifacts).toHaveLength(1)
    expect((result.detail.artifacts as Array<Record<string, unknown>>)[0]?.name).toBe(
      'connectivity_matrix.npy',
    )
  })
})
