import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { makeJsonResponse, makeToolSuccessResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch
const mockGetDataset = vi.fn()
const mockGetWorkflowById = vi.fn()

vi.mock('@/lib/server/request-auth', () => ({
  getRequestAuthToken: vi.fn().mockResolvedValue({ sub: 'test-user', tenant_id: 'test-tenant' }),
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveAgentBaseUrl: () => 'http://agent',
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: mockGetDataset,
}))

vi.mock('@/lib/server/workflow-catalog', () => ({
  getWorkflowById: mockGetWorkflowById,
}))

const createRequest = (url: string, options: RequestInit = {}) => new NextRequest(new URL(url), options)
const getUpstreamBody = (callIndex = -1) =>
  JSON.parse(
    String(
      mockFetch.mock.calls[
        callIndex >= 0 ? callIndex : mockFetch.mock.calls.length + callIndex
      ]?.[1]?.body ?? '{}',
    ),
  )
const getClientPlan = (body: any) => body?.parameters?._client_metadata?.plan_envelope ?? {}
const getCanonicalPlan = (body: any) => body?.parameters?._client_metadata?.canonical_plan ?? {}

describe('API Routes: Analyses contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    mockGetDataset.mockImplementation((id: string) => ({
      id,
      name: 'Demo Dataset',
      source_repo: 'OpenNeuro',
      modalities: ['fmri'],
      tasks: [],
      tags: [],
      category: 'task',
      access_type: 'open',
      license: 'CC0',
      primary_url: `https://example.org/datasets/${id}`,
      subjects_count: 10,
      sessions_count: 1,
      acquisitions: ['BOLD'],
      has_derivatives: false,
      preview_media: [],
      species: ['human'],
      disease_flags: [],
      search_blob: '',
    }))
    mockGetWorkflowById.mockReturnValue({ workflow: null, version: 'vFinal' })
  })

  afterEach(() => {
    vi.resetAllMocks()
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('GET /api/analyses normalizes status/timestamps and templates', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        items: [
          {
            analysis_id: 'analysis_123',
            job_id: 'analysis_123',
            state: 'succeeded',
            created_at: 1700000000,
            project_id: 'default',
            title: 'GLM on motor task',
            dataset_id: 'ds000001',
            template_id: 'glm/nilearn_glm',
            analysis_preset_id: 'glm',
            pipeline_preset_id: 'nilearn_glm',
          },
        ],
        count: 1,
      }),
    )

    const { GET } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses?limit=50')
    const res = await GET(req)

    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.items).toHaveLength(1)

    const item = data.items[0]
    expect(item.status).toBe('completed')
    expect(item.created_at).toBe(1700000000)
    expect(item.template.template_id).toBe('glm/nilearn_glm')
    expect(item.template.name).toBe('Task GLM · Nilearn GLM')
    expect(item.dataset.dataset_id).toBe('ds000001')
  })

  it('GET /api/analyses forwards project_id filter upstream', async () => {
    mockFetch.mockResolvedValueOnce(makeJsonResponse({ items: [], count: 0 }))

    const { GET } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses?limit=20&project_id=proj_alpha')
    const res = await GET(req)

    expect(res.status).toBe(200)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain(
      '/api/analyses?limit=20&project_id=proj_alpha',
    )
  })

  it('GET /api/analyses/:id generates draft methods when missing', async () => {
    mockFetch
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_456',
          run_id: 'analysis_456',
          status: 'succeeded',
          created_at: 1700000000000,
          payload_json: JSON.stringify({
            prompt: 'Connectivity analysis',
            parameters: {
              dataset_id: 'ds000002',
              analysis_id: 'connectivity',
              pipeline_id: 'nilearn_connectivity',
              smoothing_fwhm: 6,
            },
          }),
        }),
      )
      .mockResolvedValueOnce(makeJsonResponse({ detail: 'not found' }, 404))
      .mockResolvedValueOnce(
        makeJsonResponse({
          detail: 'not found',
        }, 404),
      )
      .mockResolvedValueOnce(makeJsonResponse({ detail: 'not found' }, 404))
      .mockResolvedValueOnce(makeJsonResponse({ artifacts: [] }))

    const { GET } = await import('@/app/api/analyses/[analysisId]/route')
    const req = createRequest('http://test/api/analyses/analysis_456')
    const res = await GET(req, { params: { analysisId: 'analysis_456' } })

    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.analysis_id).toBe('analysis_456')
    expect(data.status).toBe('completed')
    expect(data.methods?.generated).toBe(true)
    expect(String(data.methods?.text || '')).toMatch(/Draft Methods/i)
    expect(data.parameters.smoothing_fwhm).toBe(6)
  })

  it('POST /api/analyses appends concept context to prompt', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_789',
        analysis_id: 'analysis_789',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Base prompt',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds000003',
          steps: [],
        },
        concept_ids: ['DMN', 'PCC'],
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('http://orchestrator/run')

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    expect(String(upstreamBody.prompt || '')).toContain('Base prompt')
    expect(clientPlan.prompt).toContain('Base prompt')
    expect(clientPlan.prompt).toContain('Concept context:')
    expect(clientPlan.prompt).toContain('- DMN')
    expect(clientPlan.prompt).toContain('- PCC')
  })

  it('POST /api/analyses attaches project_id to upstream run payload', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_project_001',
        analysis_id: 'analysis_project_001',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Project-scoped run',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds000003',
          steps: [],
        },
        project_id: 'proj_alpha',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    expect(upstreamBody.project_id).toBe('proj_alpha')
    expect(clientPlan.project_id).toBe('proj_alpha')
  })

  it('POST /api/analyses forwards canonical checkpoint_id upstream', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_checkpoint_001',
        analysis_id: 'analysis_checkpoint_001',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Resume analysis',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds000003',
          steps: [],
        },
        checkpoint_id: 'ck-analysis-001',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    expect(upstreamBody.checkpoint_id).toBe('ck-analysis-001')
  })

  it('POST /api/analyses normalizes legacy resume_checkpoint_id to checkpoint_id', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_checkpoint_legacy_001',
        analysis_id: 'analysis_checkpoint_legacy_001',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Resume legacy analysis',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds000003',
          parameters: {
            resume_checkpoint_id: 'ck-analysis-legacy-001',
          },
          steps: [],
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    expect(upstreamBody.checkpoint_id).toBe('ck-analysis-legacy-001')
    expect(upstreamBody).not.toHaveProperty('resume_checkpoint_id')
  })

  it('POST /api/analyses preserves copilot attachments and scenario_id for explicit plans', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_chat_001',
        analysis_id: 'analysis_chat_001',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Continue the chat analysis',
          pipeline: 'chat',
          copilot: true,
          scenario_id: 'study_design',
          attachments: [{ file_id: 'file-123', name: 'design.pdf' }],
          parameters: {
            scenario_id: 'study_design',
          },
          steps: [],
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    expect(upstreamBody.copilot).toBe(true)
    expect(upstreamBody.scenario_id).toBe('study_design')
    expect(upstreamBody.attachments).toEqual([{ file_id: 'file-123', name: 'design.pdf' }])
  })

  it('POST /api/analyses supports dynamic workflows from workflow catalog', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_preprocessing_qc',
        stage: 'preprocessing',
        cost_tier: 'expensive',
        origin: 'core32',
        description: 'Preprocessing with QC',
        modalities: ['fmri'],
        est_runtime: '~2-4h per subject',
        impl: 'workflow: validate -> mriqc',
        runtime: {
          kind: 'declarative_workflow',
          steps: [
            { id: 'validate', tool: 'validate_bids_structure', params: {} },
            { id: 'qc', tool: 'run_mriqc_workflow', params: {} },
          ],
        },
      },
      version: 'vFinal',
    })
    mockFetch
      .mockResolvedValueOnce(makeJsonResponse({ executable: true, checks: [] }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_dynamic_001',
          analysis_id: 'analysis_dynamic_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {
          bids_dir: '/data/bids',
          output_dir: '/tmp/out',
          qc_tsv: '/tmp/qc.tsv',
          outlier_metric: 'fd_mean',
          outlier_z: 2.5,
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    const canonicalPlan = getCanonicalPlan(upstreamBody)
    expect(upstreamBody.parameters._client_metadata.launch_trace).toEqual(
      expect.objectContaining({
        canonical_analysis_id: 'dynamic_workflow',
        canonical_pipeline_id: 'workflow_preprocessing_qc',
        preflight_status: 'passed',
      }),
    )
    expect(clientPlan.template_id).toBe('dynamic_workflow/workflow_preprocessing_qc')
    expect(clientPlan.steps?.[0]?.tool).toBe('workflow_preprocessing_qc')
    expect(clientPlan.steps?.[0]?.args?.analysis_id).toBe('dynamic_workflow')
    expect(clientPlan.steps?.[0]?.args?.pipeline_id).toBe('workflow_preprocessing_qc')
    expect(clientPlan.steps?.[0]?.args?.bids_dir).toBe('/data/bids')
    expect(canonicalPlan.dag?.steps?.[0]?.tool).toBe('workflow_preprocessing_qc')
  })

  it('POST /api/analyses blocks launchable template creation when credit estimate is unknown', async () => {
    vi.resetModules()
    vi.stubEnv('NODE_ENV', 'production')
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_unknown_runtime',
        stage: 'connectivity',
        cost_tier: 'moderate',
        origin: 'core32',
        description: 'Workflow without a usable estimate',
        modalities: ['fmri'],
        supported_recipe_targets: ['python'],
        execution_recipe_available: true,
        impl: 'workflow',
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'step', tool: 'unknown_runtime_tool', params: {} }],
        },
      },
      version: 'vFinal',
    })
    mockFetch.mockResolvedValueOnce(makeJsonResponse({ executable: true, checks: [] }))

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_unknown_runtime',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-CREDIT-ESTIMATE-UNAVAILABLE')
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        canonical_pipeline_id: 'workflow_unknown_runtime',
        preflight_status: 'passed',
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        workflow_id: 'workflow_unknown_runtime',
        dataset_ref: 'ds:manual:abide',
      }),
    )
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('/api/preflight/check')
  })

  it('POST /api/analyses blocks manual/admin-only workflows before launch preflight', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_manual_only',
        stage: 'connectivity',
        cost_tier: 'moderate',
        origin: 'core32',
        description: 'Workflow requiring manual admin launch',
        modalities: ['fmri'],
        supported_recipe_targets: [],
        execution_recipe_available: false,
        agent_mode: 'manual_admin_only',
        launch_status: 'manual_admin_only',
        est_runtime: '30 min',
        impl: 'workflow',
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'step', tool: 'manual_runtime_tool', params: {} }],
        },
      },
      version: 'vFinal',
    })

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_manual_only',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-WORKFLOW-MANUAL-ADMIN-ONLY')
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        canonical_pipeline_id: 'workflow_manual_only',
        launch_status: 'manual_admin_only',
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        workflow_id: 'workflow_manual_only',
        dataset_ref: 'ds:manual:abide',
      }),
    )
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/analyses blocks explicit plans for manual/admin-only workflow tools', async () => {
    mockGetWorkflowById.mockImplementation((workflowId: string) => ({
      workflow:
        workflowId === 'workflow_manual_only'
          ? {
              id: 'workflow_manual_only',
              stage: 'connectivity',
              cost_tier: 'moderate',
              origin: 'core32',
              description: 'Workflow requiring manual admin launch',
              modalities: ['fmri'],
              supported_recipe_targets: [],
              execution_recipe_available: false,
              agent_mode: 'manual_admin_only',
              launch_status: 'manual_admin_only',
              est_runtime: '30 min',
              impl: 'workflow',
              runtime: {
                kind: 'declarative_workflow',
                steps: [{ id: 'step', tool: 'manual_runtime_tool', params: {} }],
              },
            }
          : null,
      version: 'vFinal',
    }))

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Manual-only workflow handoff',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds:manual:abide',
          steps: [
            {
              tool: 'workflow_manual_only',
              args: { dataset_id: 'ds:manual:abide' },
            },
          ],
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-WORKFLOW-MANUAL-ADMIN-ONLY')
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        template_source: 'workflow_catalog',
        workflow_found: true,
        canonical_pipeline_id: 'workflow_manual_only',
        launch_status: 'manual_admin_only',
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        workflow_id: 'workflow_manual_only',
        dataset_ref: 'ds:manual:abide',
      }),
    )
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/analyses blocks explicit launchable workflow plans when credit estimate is unknown', async () => {
    vi.resetModules()
    vi.stubEnv('NODE_ENV', 'production')
    mockGetWorkflowById.mockImplementation((workflowId: string) => ({
      workflow:
        workflowId === 'workflow_unknown_runtime'
          ? {
              id: 'workflow_unknown_runtime',
              stage: 'connectivity',
              cost_tier: 'moderate',
              origin: 'core32',
              description: 'Workflow without a usable estimate',
              modalities: ['fmri'],
              supported_recipe_targets: ['python'],
              execution_recipe_available: true,
              impl: 'workflow',
              runtime: {
                kind: 'declarative_workflow',
                steps: [{ id: 'step', tool: 'unknown_runtime_tool', params: {} }],
              },
            }
          : null,
      version: 'vFinal',
    }))

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        plan: {
          prompt: 'Unknown-cost workflow launch',
          pipeline: 'dataset_analysis',
          dataset_id: 'ds:manual:abide',
          steps: [
            {
              tool: 'workflow_unknown_runtime',
              args: { dataset_id: 'ds:manual:abide' },
            },
          ],
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-CREDIT-ESTIMATE-UNAVAILABLE')
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        template_source: 'workflow_catalog',
        workflow_found: true,
        canonical_pipeline_id: 'workflow_unknown_runtime',
        launch_status: 'launchable',
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        workflow_id: 'workflow_unknown_runtime',
        dataset_ref: 'ds:manual:abide',
      }),
    )
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/analyses returns local-backend handoff for preprocess/fmriprep templates', async () => {
    mockGetWorkflowById.mockImplementation((workflowId: string) => ({
      workflow:
        workflowId === 'workflow_fmriprep_preprocessing'
          ? {
              id: 'workflow_fmriprep_preprocessing',
              stage: 'preprocessing',
              cost_tier: 'expensive',
              origin: 'core32',
              description: 'fMRIPrep preprocessing',
              modalities: ['fmri'],
              est_runtime: '~2-4h per subject',
              supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
              primary_target: 'neurodesk',
              execution_recipe_available: true,
              impl: 'workflow: run_bids_app(fmriprep)',
              runtime: {
                kind: 'declarative_workflow',
                steps: [{ id: 'fmriprep', tool: 'run_bids_app', params: { app: 'fmriprep' } }],
              },
            }
          : null,
      version: 'vFinal',
    }))

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'preprocess',
        pipeline_id: 'fmriprep',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-WORKFLOW-LOCAL-BACKEND-REQUIRED')
    expect(data.execution_status).toEqual(
      expect.objectContaining({
        recipe_generated: true,
        runtime_available: false,
        hosted_executed: false,
        artifact_verified: false,
        recommended_backend: 'local_backend',
      }),
    )
    expect(data.execution_status.message).toContain('Heavy workflow should run on a local backend')
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        requested_analysis_id: 'preprocess',
        requested_pipeline_id: 'fmriprep',
        canonical_analysis_id: 'dynamic_workflow',
        canonical_pipeline_id: 'workflow_fmriprep_preprocessing',
        canonicalized: true,
        canonicalization_reason: 'legacy_pipeline_alias',
        hosted_launch_status: 'local_backend_required',
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        workflow_id: 'workflow_fmriprep_preprocessing',
        dataset_ref: 'ds:openneuro:ds000114',
        run_mode_hint: 'recipe_required',
      }),
    )
    expect(data.handoff_pack?.execution_status).toEqual(data.execution_status)
    const args = data.handoff_pack?.inputs ?? {}
    expect(args.bids_dir).toBe('/app/data/openneuro/ds000114')
    expect(String(args.output_dir || '')).toContain(
      '/app/data/shared/runs/ds000114/workflow_fmriprep_preprocessing',
    )
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('POST /api/analyses canonicalizes legacy parcellation pipeline to workflow launch', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_rest_connectome_e2e',
        stage: 'connectivity',
        cost_tier: 'expensive',
        origin: 'core32',
        description: 'Rest connectome',
        modalities: ['fmri'],
        est_runtime: 'minutes',
        supported_recipe_targets: ['python'],
        primary_target: 'python',
        execution_recipe_available: true,
        impl: 'workflow: fetch_atlas -> extract_timeseries -> compute_connectivity',
        runtime: {
          kind: 'declarative_workflow',
          steps: [
            { id: 'atlas', tool: 'fetch_atlas', params: {} },
            { id: 'timeseries', tool: 'extract_timeseries', params: {} },
          ],
        },
      },
      version: 'vFinal',
    })
    mockFetch
      .mockResolvedValueOnce(
        makeToolSuccessResponse({
          outputs: { resolved_path: '/app/data/openneuro/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz' },
        }),
      )
      .mockResolvedValueOnce(makeJsonResponse({ executable: true, checks: [] }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_parcellation_001',
          analysis_id: 'analysis_parcellation_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'parcellation_analysis',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)
    const data = await res.json()
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toContain('/api/preflight/check')
    expect(getUpstreamBody(1)).toEqual({ workflow_id: 'workflow_rest_connectome_e2e' })

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    const clientMetadata = upstreamBody.parameters._client_metadata
    const trace = upstreamBody.parameters._client_metadata.launch_trace
    expect(data.execution_status).toEqual(
      expect.objectContaining({
        recipe_generated: true,
        runtime_available: true,
        hosted_executed: false,
        artifact_verified: false,
        recommended_backend: 'hosted',
      }),
    )
    expect(clientPlan.template_id).toBe('dynamic_workflow/workflow_rest_connectome_e2e')
    expect(clientPlan.steps?.[0]?.tool).toBe('workflow_rest_connectome_e2e')
    expect(clientPlan.execution_status).toEqual(data.execution_status)
    expect(clientMetadata.execution_status).toEqual(data.execution_status)
    expect(clientMetadata.handoff_pack).toEqual(
      expect.objectContaining({
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_rest_connectome_e2e',
        chosen_tool: 'workflow_rest_connectome_e2e',
        dataset_ref: 'ds:openneuro:ds000114',
        run_mode_hint: 'recipe_required',
      }),
    )
    expect(clientMetadata.handoff_pack?.execution).toEqual(
      expect.objectContaining({
        kind: 'brain_researcher_orchestrator',
        submit_route: '/run',
        preflight_route: '/api/preflight/check',
        workflow_id: 'workflow_rest_connectome_e2e',
        preflight_status: 'passed',
      }),
    )
    expect(trace).toEqual(
      expect.objectContaining({
        requested_analysis_id: 'connectivity',
        requested_pipeline_id: 'parcellation_analysis',
        canonical_analysis_id: 'dynamic_workflow',
        canonical_pipeline_id: 'workflow_rest_connectome_e2e',
        canonicalized: true,
        canonicalization_reason: 'legacy_pipeline_alias',
        workflow_found: true,
        preflight_status: 'passed',
      }),
    )
  })

  it('POST /api/analyses returns launch trace and handoff when backend rejects run creation', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_rest_connectome_e2e',
        stage: 'connectivity',
        cost_tier: 'expensive',
        origin: 'core32',
        description: 'Rest connectome',
        modalities: ['fmri'],
        est_runtime: 'minutes',
        impl: 'workflow',
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'timeseries', tool: 'extract_timeseries', params: {} }],
        },
      },
      version: 'vFinal',
    })
    mockFetch
      .mockResolvedValueOnce(
        makeToolSuccessResponse({
          outputs: {
            resolved_path:
              '/app/data/openneuro/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz',
          },
        }),
      )
      .mockResolvedValueOnce(makeJsonResponse({ executable: true, checks: [] }))
      .mockResolvedValueOnce(
        makeJsonResponse(
          {
            detail: [
              {
                type: 'string_pattern_mismatch',
                loc: ['body', 'dataset_id'],
                msg: 'String should match pattern',
              },
            ],
          },
          422,
        ),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'parcellation_analysis',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(422)
    const data = await res.json()
    expect(data.launch_trace).toEqual(
      expect.objectContaining({
        canonical_pipeline_id: 'workflow_rest_connectome_e2e',
        preflight_status: 'passed',
        upstream_status: 422,
        upstream_rejected: true,
      }),
    )
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_ref: 'ds:openneuro:ds000114',
      }),
    )
    expect(data.handoff_pack?.execution).toEqual(
      expect.objectContaining({
        submit_route: '/run',
        preflight_status: 'passed',
      }),
    )
  })

  it('POST /api/analyses blocks legacy workflow launch when preflight confirms missing runtime', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_rest_connectome_e2e',
        stage: 'connectivity',
        cost_tier: 'expensive',
        description: 'Rest connectome',
        modalities: ['fmri'],
        est_runtime: 'minutes',
        impl: 'workflow',
        runtime: { kind: 'declarative_workflow', steps: [] },
      },
      version: 'vFinal',
    })
    mockFetch
      .mockResolvedValueOnce(
        makeJsonResponse({
          result: {
            status: 'error',
            error: 'No matching BIDS files found',
            data: {},
          },
        }),
      )
      .mockResolvedValueOnce(
        makeJsonResponse({
          executable: false,
          checks: [{ tool_id: 'extract_timeseries', status: 'missing', available: false }],
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'parcellation_analysis',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error).toBe('E-LAUNCH-PREFLIGHT-BLOCKED')
    expect(data.detail).toContain('extract_timeseries')
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_rest_connectome_e2e',
        chosen_tool: 'workflow_rest_connectome_e2e',
        dataset_ref: 'ds:openneuro:ds000114',
      }),
    )
    expect(data.handoff_pack?.execution).toEqual(
      expect.objectContaining({
        kind: 'brain_researcher_orchestrator',
        workflow_id: 'workflow_rest_connectome_e2e',
        preflight_status: 'blocked',
      }),
    )
    expect(mockFetch).toHaveBeenCalledTimes(2)
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toContain('/api/preflight/check')
  })

  it('POST /api/analyses injects connectivity defaults and infers img from bids_dir', async () => {
    const bidsDir = '/data/bids/ds000114'
    const resolvedBoldImg = '/data/bids/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz'
    mockFetch
      .mockResolvedValueOnce(makeToolSuccessResponse({ outputs: { resolved_path: resolvedBoldImg } }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_conn_001',
          analysis_id: 'analysis_conn_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        parameters: {
          bids_dir: bidsDir,
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    const step = clientPlan.steps?.[0] ?? {}
    const args = step.args ?? {}
    const params = clientPlan.parameters ?? {}

    expect(step.tool).toBe('workflow_rest_connectome_e2e')
    expect(args.bids_dir).toBe(bidsDir)
    expect(String(args.output_dir || '')).toBe('outputs/nilearn_connectivity')
    expect(args.atlas_name).toBe('Schaefer2018_200')
    expect(args.connectivity_kind).toBe('correlation')
    expect(args.img).toBe(resolvedBoldImg)
    expect(params.img).toBe(resolvedBoldImg)
    expect(params.bold_img).toBe(resolvedBoldImg)
  })

  it('POST /api/analyses maps legacy connectivity params to workflow_rest_connectome_e2e args', async () => {
    const boldImg = '/tmp/input/sub-01/ses-test/func/sub-01_ses-test_task-rest_bold.nii.gz'
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        job_id: 'analysis_conn_legacy_001',
        analysis_id: 'analysis_conn_legacy_001',
      }),
    )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        parameters: {
          atlas: 'Schaefer2018_100',
          connectivity_metric: 'partial correlation',
          bold_img: boldImg,
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    const args = clientPlan.steps?.[0]?.args ?? {}
    const params = clientPlan.parameters ?? {}
    expect(args.atlas_name).toBe('Schaefer2018_100')
    expect(args.connectivity_kind).toBe('partial correlation')
    expect(args.img).toBe(boldImg)
    expect(args.bold_img).toBe(boldImg)
    expect(args.subject_id).toBe('01')
    expect(args.session_id).toBe('test')
    expect(args.task_id).toBe('rest')
    expect(params.subject_id).toBe('01')
    expect(params.session_id).toBe('test')
    expect(params.task_id).toBe('rest')
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('http://orchestrator/run')
  })

  it('POST /api/analyses accepts connectivity template_id and keeps workflow_rest_connectome_e2e', async () => {
    const bidsDir = '/data/bids/ds000114'
    mockFetch
      .mockResolvedValueOnce(
        makeToolSuccessResponse({
          outputs: { resolved_path: '/data/bids/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz' },
        }),
      )
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_conn_template_001',
          analysis_id: 'analysis_conn_template_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        template_id: 'connectivity/nilearn_connectivity',
        parameters: {
          bids_dir: bidsDir,
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const step = getClientPlan(upstreamBody).steps?.[0] ?? {}
    expect(step.tool).toBe('workflow_rest_connectome_e2e')
  })

  it('POST /api/analyses normalizes connectivity_kind aliases for workflow_rest_connectome_e2e', async () => {
    const bidsDir = '/data/bids/ds000114'
    mockFetch
      .mockResolvedValueOnce(
        makeToolSuccessResponse({
          outputs: { resolved_path: '/data/bids/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz' },
        }),
      )
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_conn_kind_001',
          analysis_id: 'analysis_conn_kind_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        parameters: {
          bids_dir: bidsDir,
          connectivity_kind: 'partial_correlation',
        },
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const args = getClientPlan(upstreamBody).steps?.[0]?.args ?? {}
    expect(args.connectivity_kind).toBe('partial correlation')
  })

  it('POST /api/analyses injects GLM defaults and infers img from bids_dir', async () => {
    const resolvedBoldImg = '/app/data/openneuro/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz'
    mockFetch
      .mockResolvedValueOnce(makeToolSuccessResponse({ outputs: { resolved_path: resolvedBoldImg } }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_glm_001',
          analysis_id: 'analysis_glm_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'glm',
        pipeline_id: 'nilearn_glm',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const clientPlan = getClientPlan(upstreamBody)
    const step = clientPlan.steps?.[0] ?? {}
    const args = step.args ?? {}
    const params = clientPlan.parameters ?? {}
    expect(step.tool).toBe('glm_first_level')
    expect(args.bids_dir).toBe('/app/data/openneuro/ds000114')
    expect(String(args.output_dir || '')).toBe('outputs/nilearn_glm')
    expect(args.img).toBe(resolvedBoldImg)
    expect(args.smoothing_fwhm).toBe(6)
    expect(params.img).toBe(resolvedBoldImg)
    expect(params.bold_img).toBe(resolvedBoldImg)
    expect(params.smoothing_fwhm).toBe(6)
  })

  it('POST /api/analyses does not block connectivity runs on web-ui local file checks', async () => {
    mockGetDataset.mockReturnValueOnce({
      id: 'ds:openneuro:ds000114',
      name: 'A test-retest fMRI dataset',
      source_repo: 'OpenNeuro',
      source_repo_id: 'ds000114',
      modalities: ['fmri'],
      tasks: ['covert_verb_generation', 'finger_foot_lips', 'line_bisection'],
      tags: [],
      category: 'OpenNeuro',
      access_type: 'public',
      license: 'CC0',
      primary_url: 'https://openneuro.org/datasets/ds000114',
      subjects_count: 10,
      sessions_count: 2,
      acquisitions: ['BOLD'],
      has_derivatives: false,
      preview_media: [],
      species: ['human'],
      disease_flags: [],
      search_blob: '',
    })
    mockFetch
      .mockResolvedValueOnce(
        makeJsonResponse({
          result: {
            status: 'error',
            error: 'No matching BIDS files found',
            data: {},
          },
        }),
      )
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_conn_fallback_001',
          analysis_id: 'analysis_conn_fallback_001',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)
    expect(getUpstreamBody(0).args).toEqual(
      expect.objectContaining({
        bids_root: '/app/data/openneuro/ds000114',
        subject_id: '01',
        session_id: 'test',
        task_id: 'covertverbgeneration',
        datatype: 'func',
        suffix: 'bold',
      }),
    )
    const upstreamBody = getUpstreamBody()
    const plan = getClientPlan(upstreamBody)
    const args = plan.steps?.[0]?.args ?? {}
    expect(plan.steps?.[0]?.tool).toBe('workflow_rest_connectome_e2e')
    expect(args.img).toBe(
      '/app/data/openneuro/ds000114/sub-01/ses-test/func/sub-01_ses-test_task-covertverbgeneration_bold.nii.gz',
    )
    expect(args.session_id).toBe('test')
    expect(args.task_id).toBe('covertverbgeneration')
  })

  it('POST /api/analyses injects workflow_preprocessing_qc defaults when params are missing', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_preprocessing_qc',
        stage: 'preprocessing',
        cost_tier: 'expensive',
        origin: 'core32',
        description: 'Preprocessing with QC',
        modalities: ['fmri'],
        est_runtime: '~2-4h per subject',
        impl: 'workflow: validate -> mriqc',
        runtime: {
          kind: 'declarative_workflow',
          steps: [
            { id: 'validate', tool: 'validate_bids_structure', params: {} },
            { id: 'qc', tool: 'run_mriqc_workflow', params: {} },
          ],
        },
      },
      version: 'vFinal',
    })
    mockFetch
      .mockResolvedValueOnce(makeJsonResponse({ executable: true, checks: [] }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          job_id: 'analysis_dynamic_002',
          analysis_id: 'analysis_dynamic_002',
        }),
      )

    const { POST } = await import('@/app/api/analyses/route')
    const req = createRequest('http://test/api/analyses', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        thread: { mode: 'none' },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = getUpstreamBody()
    const args = getClientPlan(upstreamBody).steps?.[0]?.args ?? {}
    expect(args.bids_dir).toBe('/app/data/openneuro/ds000114')
    expect(String(args.output_dir || '')).toContain('/app/data/shared/runs/ds000114/workflow_preprocessing_qc')
    expect(String(args.qc_tsv || '')).toContain('/mriqc/group_bold.tsv')
    expect(args.outlier_metric).toBe('fd_mean')
    expect(args.outlier_z).toBe(2.5)
  })

})
