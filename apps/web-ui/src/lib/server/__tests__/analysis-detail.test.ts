import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockFetch = vi.fn()
global.fetch = mockFetch as any

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: (datasetId: string) =>
    datasetId === 'ds000001'
      ? {
          id: 'ds000001',
          name: 'Mock dataset',
          source_repo: 'openneuro',
          modalities: ['bold'],
        }
      : null,
}))

describe('buildAnalysisDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('hydrates analysis detail from orchestrator job payloads without querying agent runs', async () => {
    const payload = {
      name: 'GLM example',
      prompt: 'Run GLM on ds000001',
      metadata: {
        thread_id: 'thread_abc123',
        client_plan_envelope: {
          dataset_id: 'ds000001',
          analysis_id: 'glm',
          pipeline_id: 'nilearn_glm',
          template_id: 'glm/nilearn_glm',
          parameters: {
            dataset_id: 'ds000001',
            analysis_id: 'glm',
            pipeline_id: 'nilearn_glm',
          },
        },
      },
      plan_of_record: {
        plan_id: 'plan_glm_001',
        handoff: {
          plan_id: 'plan_glm_001',
          workflow_id: 'workflow_glm',
          dataset_ref: 'ds000001',
        },
        dag: {
          steps: [{ id: 'step_glm', tool: 'workflow_glm', name: 'Run GLM' }],
        },
      },
    }

    mockFetch
      .mockResolvedValueOnce(
        Response.json({
          job_id: 'job_analysis_001',
          status: 'running',
          created_at: 1_700_000_000,
          started_at: 1_700_000_030,
          run_id: 'run_001',
          session_id: 'thread_abc123',
          payload_json: JSON.stringify(payload),
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          run_card: {
            methods: { text: 'Observed methods' },
            inputs: {
              parameters: {
                dataset_id: 'ds000001',
                analysis_id: 'glm',
                pipeline_id: 'nilearn_glm',
              },
            },
          },
          artifacts: [{ id: 'artifact_1', name: 'report.html', type: 'report' }],
        }),
      )

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'job_analysis_001',
      headers: new Headers({ authorization: 'Bearer test-token' }),
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.detail.analysis_id).toBe('job_analysis_001')
    expect(result.detail.run_id).toBe('run_001')
    expect(result.detail.thread_id).toBe('thread_abc123')
    expect(result.detail.dataset?.dataset_id).toBe('ds000001')
    expect(result.detail.template?.template_id).toBe('glm/nilearn_glm')
    expect(result.detail.plan?.plan_id).toBe('plan_glm_001')
    expect(result.detail.plan?.dataset_ref).toBe('ds000001')
    expect(result.detail.plan?.steps).toEqual([
      { id: 'step_glm', tool: 'workflow_glm', name: 'Run GLM' },
    ])
    const methods = result.detail.methods
    expect(typeof methods).toBe('object')
    expect(methods && typeof methods !== 'string' ? methods.generated : undefined).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(2)
    expect(mockFetch.mock.calls.every(([url]) => String(url).startsWith('http://orchestrator/'))).toBe(
      true,
    )
  })

  it('returns 404 when orchestrator cannot resolve the analysis', async () => {
    mockFetch
      .mockResolvedValueOnce(new Response('not found', { status: 404 }))
      .mockResolvedValueOnce(new Response('not found', { status: 404 }))
      .mockResolvedValueOnce(new Response('not found', { status: 404 }))
      .mockResolvedValueOnce(new Response('not found', { status: 404 }))

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'missing_analysis',
      headers: new Headers(),
    })

    expect(result).toEqual({
      ok: false,
      status: 404,
      body: {
        detail: 'Run not found.',
        warnings: ['Some job status metadata is temporarily unavailable.'],
      },
    })
  })

  it('preserves plan_id from orchestrator plan payloads when no client plan envelope exists', async () => {
    const payload = {
      prompt: 'Studio handoff test for ds000001 connectivity',
      metadata: {
        thread_id: 'thread_plan_only',
      },
      plan: {
        plan_id: 'plan_connectivity_001',
        version: 1,
        workflow_id: 'workflow_rest_connectome_e2e',
        context: {
          inputs: {
            dataset_ref: 'ds000001',
          },
        },
        handoff: {
          plan_id: 'plan_connectivity_001',
          version: 1,
          workflow_id: 'workflow_rest_connectome_e2e',
          dataset_ref: 'ds000001',
        },
        dag: {
          steps: [{ id: 'step_conn', tool: 'workflow_rest_connectome_e2e', name: 'Run connectivity' }],
        },
      },
      plan_summary: {
        plan_id: 'plan_connectivity_001',
      },
    }

    mockFetch
      .mockResolvedValueOnce(
        Response.json({
          job_id: 'job_analysis_002',
          status: 'queued',
          created_at: 1_700_000_100,
          payload_json: JSON.stringify(payload),
        }),
      )
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'job_analysis_002',
      headers: new Headers({ authorization: 'Bearer test-token' }),
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.detail.plan?.plan_id).toBe('plan_connectivity_001')
    expect(result.detail.plan?.workflow_id).toBe('workflow_rest_connectome_e2e')
    expect(result.detail.plan?.dataset_ref).toBe('ds000001')
    expect(result.detail.plan?.dataset_id).toBe('ds000001')
  })

  it('exposes handoff, preflight, artifact contract, steps, and log summaries when present', async () => {
    const handoffPack = {
      schema_version: 'br-plan-handoff-v1',
      plan_id: 'plan_trace_001',
      workflow_id: 'workflow_rest_connectome_e2e',
      dataset_ref: 'ds000001',
      execution: {
        preflight_route: '/api/preflight/check',
        preflight_status: 'passed',
        preflight_detail: 'Runtime ready',
        artifact_contract: {
          required_outputs: ['connectivity_matrix.npy', 'qc_report.html'],
        },
      },
      checks: [{ id: 'runtime', status: 'passed', detail: 'Neurodesk available' }],
      launch_trace: { preflight_status: 'passed', request_id: 'trace_001' },
    }
    const payload = {
      prompt: 'Run trace viewer test',
      plan: {
        plan_id: 'plan_trace_001',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_id: 'ds000001',
        handoff_pack: handoffPack,
        dag: {
          steps: [{ id: 'step_1', tool: 'workflow_rest_connectome_e2e', name: 'Run workflow' }],
        },
      },
    }

    mockFetch
      .mockResolvedValueOnce(
        Response.json({
          job_id: 'job_trace_001',
          status: 'succeeded',
          created_at: 1_700_000_100,
          completed_at: 1_700_000_200,
          payload_json: JSON.stringify(payload),
          step_progress: [{ id: 'step_1', name: 'Run workflow', status: 'completed' }],
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          run_card: {
            execution: {
              steps: [{ id: 'step_2', name: 'Collect QC', status: 'completed', tool: 'qc' }],
            },
            logs: [{ name: 'stderr.txt', path: 'runs/job_trace_001/stderr.txt' }],
          },
          artifacts: [
            { id: 'report', name: 'qc_report.html', type: 'report' },
            { id: 'stdout', name: 'stdout.txt', type: 'log', url: 'http://files/stdout.txt' },
          ],
        }),
      )

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'job_trace_001',
      headers: new Headers({ authorization: 'Bearer test-token' }),
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.detail.handoff_pack).toEqual(handoffPack)
    expect(result.detail.artifact_contract).toEqual({
      required_outputs: ['connectivity_matrix.npy', 'qc_report.html'],
    })
    expect(result.detail.preflight).toEqual({
      status: 'passed',
      detail: 'Runtime ready',
      route: '/api/preflight/check',
      checks: [{ id: 'runtime', status: 'passed', detail: 'Neurodesk available' }],
    })
    expect(result.detail.launch_trace).toEqual({ preflight_status: 'passed', request_id: 'trace_001' })
    expect(result.detail.steps_summary).toEqual([
      { id: 'step_1', name: 'Run workflow', status: 'completed', tool: 'workflow_rest_connectome_e2e' },
      { id: 'step_2', name: 'Collect QC', status: 'completed', tool: 'qc' },
    ])
    expect(result.detail.logs_summary).toEqual([
      { name: 'stdout.txt', url: 'http://files/stdout.txt', kind: 'log' },
      { name: 'stderr.txt', path: 'runs/job_trace_001/stderr.txt' },
    ])
  })

  it('uses persisted payload steps when provenance files are missing', async () => {
    const payload = {
      prompt: 'Run failed trace test',
      steps: [
        {
          id: 'step_001',
          name: '1. workflow_rest_connectome_e2e',
          tool: 'workflow_rest_connectome_e2e',
          status: 'failed',
          preview: 'ValueError: File not found',
        },
      ],
      plan: {
        plan_id: 'plan_failed_001',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_id: 'ds000001',
      },
    }

    mockFetch
      .mockResolvedValueOnce(
        Response.json({
          job_id: 'job_failed_001',
          status: 'failed',
          created_at: 1_700_000_100,
          finished_at: 1_700_000_130,
          payload_json: JSON.stringify(payload),
          step_progress: [
            {
              id: 'step_001',
              name: '1. workflow_rest_connectome_e2e',
              status: 'failed',
            },
          ],
        }),
      )
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))
      .mockResolvedValueOnce(Response.json({ artifacts: [] }))

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'job_failed_001',
      headers: new Headers({ authorization: 'Bearer test-token' }),
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.detail.status).toBe('failed')
    expect(result.detail.steps_summary).toEqual([
      {
        id: 'step_001',
        name: '1. workflow_rest_connectome_e2e',
        status: 'failed',
        tool: 'workflow_rest_connectome_e2e',
        detail: 'ValueError: File not found',
      },
    ])
  })

  it('does not report pending plan-only steps for a failed run without logs', async () => {
    const payload = {
      prompt: 'Run failed before step trace',
      plan: {
        plan_id: 'plan_failed_before_steps',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_id: 'ds000001',
        dag: {
          steps: [
            {
              id: 'step_001',
              name: '1. workflow_rest_connectome_e2e',
              tool: 'workflow_rest_connectome_e2e',
              status: 'pending',
            },
          ],
        },
      },
    }

    mockFetch
      .mockResolvedValueOnce(
        Response.json({
          job_id: 'job_failed_no_logs',
          status: 'failed',
          created_at: 1_700_000_100,
          finished_at: 1_700_000_130,
          payload_json: JSON.stringify(payload),
          error_message: 'ToolExecutor unavailable for plan execution',
        }),
      )
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))

    const { buildAnalysisDetail } = await import('@/lib/server/analysis-detail')
    const result = await buildAnalysisDetail({
      analysisId: 'job_failed_no_logs',
      headers: new Headers({ authorization: 'Bearer test-token' }),
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.detail.status).toBe('failed')
    expect(result.detail.steps_summary).toEqual([
      {
        id: 'step_001',
        name: '1. workflow_rest_connectome_e2e',
        status: 'failed',
        tool: 'workflow_rest_connectome_e2e',
        detail: 'ToolExecutor unavailable for plan execution',
      },
    ])
    expect(result.detail.logs_summary).toEqual([])
  })
})
