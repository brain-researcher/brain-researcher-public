import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { jsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch
const mockGetDataset = vi.fn()
const mockGetWorkflowById = vi.fn()
const mockGetDatasetResources = vi.fn()

vi.mock('@/lib/server/request-auth', () => ({
  getRequestAuthToken: vi.fn().mockResolvedValue({ sub: 'test-user', tenant_id: 'test-tenant' }),
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: mockGetDataset,
}))

vi.mock('@/lib/server/workflow-catalog', () => ({
  getWorkflowById: mockGetWorkflowById,
}))

vi.mock('@/app/api/catalog/datasets/[datasetId]/resources/route', () => ({
  GET: mockGetDatasetResources,
}))

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
  forwardAuthHeaders: () => new Headers(),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)
const MULTIVERSE_PIPELINE_ID = 'fmri_glm_multiverse_openneuro'

describe('API Routes: Plan checks contract', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    mockGetDataset.mockImplementation((id: string) => ({
      id,
      name: 'ABIDE (I & II)',
      modalities: ['fmri'],
      tasks: ['resting-state'],
    }))
    mockGetWorkflowById.mockReturnValue({
      workflow: {
        id: 'workflow_preprocessing_qc',
        stage: 'preprocessing',
        cost_tier: 'expensive',
        description: 'Preprocessing workflow',
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
    mockGetDatasetResources.mockResolvedValue(
      jsonResponse({
        readiness: { status: 'ready' },
        required_files: { all_required_passed: true },
        source_access: { bucket_check: { state: 'verified_present' } },
      }),
    )
    mockFetch.mockResolvedValue(
      jsonResponse({
        executable: true,
        checks: [
          { tool_id: 'validate_bids_structure', status: 'available', available: true },
          { tool_id: 'run_mriqc_workflow', status: 'available', available: true },
        ],
        warnings: [],
      }),
    )
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('POST /api/plan/checks passes dynamic workflow from catalog', async () => {
    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        dataset_version: 'v1.0.2',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'workflow_compatible',
          status: 'passed',
        }),
        expect.objectContaining({
          id: 'runtime_executable',
          status: 'passed',
        }),
      ]),
    )
    expect(data.estimate?.runtime).toBe('~2-4h per subject')
    expect(data.context?.dataset_version).toBe('v1.0.2')
    expect(data.effective_config?.analysis_id).toBe('dynamic_workflow')
    expect(data.effective_config?.pipeline_id).toBe('workflow_preprocessing_qc')
    expect(data.handoff_pack).toEqual(
      expect.objectContaining({
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_preprocessing_qc',
        chosen_tool: 'workflow_preprocessing_qc',
        dataset_ref: 'ds:manual:abide',
        run_mode_hint: 'recipe_required',
      }),
    )
    expect(data.handoff_pack?.execution).toEqual(
      expect.objectContaining({
        kind: 'brain_researcher_orchestrator',
        submit_route: '/run',
        preflight_route: '/api/preflight/check',
        workflow_id: 'workflow_preprocessing_qc',
        preflight_status: 'passed',
      }),
    )
    expect(data.handoff_pack?.recipe_lookup).toEqual(
      expect.objectContaining({
        tool_name: 'get_execution_recipe',
        tool_id: 'workflow_preprocessing_qc',
      }),
    )
    expect(
      data.effective_config?.parameters?.some(
        (entry: { key?: string; origin?: string }) =>
          entry.key === 'bids_dir' && entry.origin === 'inferred',
      ),
    ).toBe(true)
    const dataCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'data_validated',
    )
    expect(dataCheck?.detail).toContain('Requested version: v1.0.2')
  })

  it('POST /api/plan/checks uses dataset-aware BIDS defaults for ds000114', async () => {
    mockGetDataset.mockReturnValueOnce({
      id: 'ds:openneuro:ds000114',
      name: 'A test-retest fMRI dataset',
      source_repo: 'OpenNeuro',
      source_repo_id: 'ds000114',
      primary_url: 'https://openneuro.org/datasets/ds000114',
      modalities: ['fmri'],
      tasks: ['covert_verb_generation', 'finger_foot_lips', 'line_bisection'],
      tags: [],
      category: 'OpenNeuro',
      access_type: 'public',
      subjects_count: 10,
      sessions_count: 2,
      license: 'CC0',
    })
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_rest_connectome_e2e',
        stage: 'connectivity',
        cost_tier: 'expensive',
        description: 'Atlas-based resting-state connectome workflow',
        modalities: ['fmri'],
        est_runtime: 'minutes',
        supported_recipe_targets: ['python'],
        primary_target: 'python',
        execution_recipe_available: true,
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'connectome', tool: 'connectivity_matrix', params: {} }],
        },
      },
      version: 'vFinal',
    })

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.effective_config?.parameter_values).toEqual(
      expect.objectContaining({
        subject_id: '01',
        session_id: 'test',
        task_id: 'covertverbgeneration',
        img: '/app/data/openneuro/ds000114/sub-01/ses-test/func/sub-01_ses-test_task-covertverbgeneration_bold.nii.gz',
      }),
    )
    expect(data.handoff_pack?.inputs?.img).toBe(
      '/app/data/openneuro/ds000114/sub-01/ses-test/func/sub-01_ses-test_task-covertverbgeneration_bold.nii.gz',
    )
    expect(data.capability).toEqual(
      expect.objectContaining({
        schema_version: 'br-workflow-capability-v1',
        canonical_workflow_id: 'workflow_rest_connectome_e2e',
        mcp_recipe: expect.objectContaining({
          status: 'available',
          supported_targets: ['python'],
          preferred_target: 'python',
        }),
      }),
    )
    expect(data.capability.mcp_recipe.recipe_call).toContain(
      'tool_id="workflow_rest_connectome_e2e"',
    )
    expect(data.capability.mcp_recipe.recipe_call).toContain('target_runtime="python"')
    expect(data.capability.mcp_recipe.recipe_call).toContain('"dataset_id": "ds000114"')
  })

  it('POST /api/plan/checks blocks when dataset modality mismatches dynamic workflow', async () => {
    mockGetDataset.mockImplementation((id: string) => ({
      id,
      name: 'EEG-only dataset',
      modalities: ['eeg'],
      tasks: [],
    }))

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:eeg:demo',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'workflow_compatible',
          status: 'blocked',
        }),
      ]),
    )
    const workflowCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'workflow_compatible',
    )
    expect(workflowCheck?.detail).toContain('Pipeline requires modalities: fmri')
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('/api/credits/balance')
  })

  it('POST /api/plan/checks warns when runtime preflight is unavailable', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network down'))

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'runtime_executable',
          status: 'warning',
        }),
      ]),
    )
  })

  it('POST /api/plan/checks blocks only when runtime preflight confirms missing tools', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [{ tool_id: 'connectivity_matrix', status: 'missing', available: false }],
        warnings: [],
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const runtimeCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'runtime_executable',
    )
    expect(runtimeCheck?.status).toBe('blocked')
    expect(runtimeCheck?.detail).toContain('Missing runtime tools')
  })

  it('POST /api/plan/checks surfaces runtime guidance from preflight', async () => {
    const guidancePayload = {
      summary: 'Requires Neurodesk modules to run',
      runtime_target: 'Neurodesk',
      required_modules: ['fmriprep/23.2.1', 'mriqc/24.0.2'],
      required_env_vars: ['FREESURFER_HOME'],
      next_action_url: 'https://play.neurodesk.org/',
      actions: [
        {
          id: 'neurodesk-play',
          label: 'Try Neurodesk Play',
          href: 'https://play.neurodesk.org/',
        },
      ],
    }

    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [{ tool_id: 'fmriprep', status: 'missing', available: false }],
        warnings: [],
        guidance: guidancePayload,
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.guidance).toEqual(guidancePayload)
  })

  it('POST /api/plan/checks uses handoff-only decision for recipe handoff guidance', async () => {
    const guidancePayload = {
      kind: 'recipe_handoff_required',
      runtime_target: 'container',
      summary: 'Hosted Studio cannot execute this container workflow directly.',
      detail: 'Unavailable runtime steps: run_fastsurfer',
      required_env_vars: ['FS_LICENSE'],
      supported_recipe_targets: ['container'],
      container_images: { fastsurfer: 'deepmi/fastsurfer:latest' },
    }

    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_preprocessing_qc',
        stage: 'preprocessing',
        cost_tier: 'expensive',
        description: 'Container workflow',
        modalities: ['fmri'],
        supported_recipe_targets: ['container'],
        execution_recipe_available: true,
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'fastsurfer', tool: 'run_fastsurfer', params: {} }],
        },
      },
      version: 'vFinal',
    })
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [
          {
            requested_tool_id: 'run_fastsurfer',
            tool_id: 'run_fastsurfer',
            status: 'blocked',
            code: 'RUNTIME_TOOL_NOT_ALLOWED',
            available: false,
          },
        ],
        warnings: [],
        guidance: guidancePayload,
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.guidance).toEqual(guidancePayload)
    expect(data.launch_decision).toEqual(
      expect.objectContaining({
        status: 'handoff_only',
        code: 'handoff_only',
        can_launch: false,
        primary_action: 'handoff',
        reason: 'Hosted Studio cannot execute this container workflow directly.',
      }),
    )
    const creditCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'credits_sufficient',
    )
    expect(creditCheck?.status).toBe('warning')
    expect(creditCheck?.detail).toContain('handoff')
  })

  it('POST /api/plan/checks maps static fMRIPrep preset to workflow handoff', async () => {
    const guidancePayload = {
      kind: 'neurodesk_setup_required',
      runtime_target: 'neurodesk',
      summary: 'This workflow depends on a Neurodesk-backed runtime.',
      supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
      required_env_vars: ['FS_LICENSE'],
    }

    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_fmriprep_preprocessing',
        stage: 'preprocessing',
        cost_tier: 'expensive',
        description: 'fMRIPrep workflow',
        modalities: ['fmri'],
        supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
        execution_recipe_available: true,
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'fmriprep', tool: 'run_bids_app', params: { app: 'fmriprep' } }],
        },
      },
      version: 'vFinal',
    })
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [{ tool_id: 'run_bids_app', status: 'blocked', code: 'RUNTIME_TOOL_NOT_ALLOWED' }],
        warnings: [],
        guidance: guidancePayload,
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'preprocess',
        pipeline_id: 'fmriprep',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.launch_decision).toEqual(
      expect.objectContaining({
        status: 'handoff_only',
        code: 'handoff_only',
        can_launch: false,
        primary_action: 'handoff',
        reason: 'This workflow depends on a Neurodesk-backed runtime.',
      }),
    )
    expect(data.handoff_pack?.workflow_id).toBe('workflow_fmriprep_preprocessing')
    expect(data.capability).toEqual(
      expect.objectContaining({
        schema_version: 'br-workflow-capability-v1',
        canonical_workflow_id: 'workflow_fmriprep_preprocessing',
        hosted_launch: expect.objectContaining({
          status: 'handoff_only',
          primary_action: 'handoff',
        }),
        mcp_recipe: expect.objectContaining({
          status: 'available',
          supported_targets: ['neurodesk', 'container', 'slurm'],
        }),
      }),
    )
    expect(data.execution_status).toEqual(
      expect.objectContaining({
        recipe_generated: true,
        runtime_available: false,
        hosted_executed: false,
        artifact_verified: false,
        runtime_scope: 'hosted_preflight',
        recommended_backend: 'local_backend',
      }),
    )
    expect(data.execution_status.message).toContain('Heavy workflow should run on a local backend')
    expect(data.capability.execution_status).toEqual(data.execution_status)
    expect(data.capability.unsupported_reasons).toEqual(
      expect.arrayContaining([
        expect.stringContaining('Neurodesk-backed runtime'),
        expect.stringContaining('FS_LICENSE'),
      ]),
    )
    expect(data.handoff_pack?.launch_trace).toEqual(
      expect.objectContaining({
        requested_analysis_id: 'preprocess',
        requested_pipeline_id: 'fmriprep',
        canonical_analysis_id: 'dynamic_workflow',
        canonical_pipeline_id: 'workflow_fmriprep_preprocessing',
        canonicalized: true,
        canonicalization_reason: 'legacy_pipeline_alias',
      }),
    )
    const creditCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'credits_sufficient',
    )
    expect(creditCheck?.status).toBe('warning')
  })

  it.each([
    {
      preset: 'mriqc',
      workflowId: 'workflow_mriqc',
      modality: 'smri',
      toolParams: { app: 'mriqc' },
    },
    {
      preset: 'qsiprep',
      workflowId: 'workflow_qsiprep',
      modality: 'dmri',
      toolParams: { app: 'qsiprep' },
    },
  ])(
    'POST /api/plan/checks maps static $preset preset to canonical handoff workflow',
    async ({ preset, workflowId, modality, toolParams }) => {
      mockGetDataset.mockReturnValueOnce({
        id: `ds:${modality}:demo`,
        name: `${preset} demo dataset`,
        modalities: [modality],
        tasks: [],
      })
      mockGetWorkflowById.mockReturnValueOnce({
        workflow: {
          id: workflowId,
          stage: 'preprocessing',
          cost_tier: 'expensive',
          description: `${preset} workflow`,
          modalities: [modality],
          supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
          execution_recipe_available: true,
          runtime: {
            kind: 'declarative_workflow',
            steps: [{ id: preset, tool: 'run_bids_app', params: toolParams }],
          },
        },
        version: 'vFinal',
      })
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          executable: false,
          checks: [
            { tool_id: 'run_bids_app', status: 'blocked', code: 'RUNTIME_TOOL_NOT_ALLOWED' },
          ],
          warnings: [],
          guidance: {
            kind: 'recipe_handoff_required',
            runtime_target: 'neurodesk',
            summary: `Hosted Studio cannot execute ${preset} directly.`,
            supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
          },
        }),
      )

      const { POST } = await import('@/app/api/plan/checks/route')
      const req = createRequest('http://test/api/plan/checks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          dataset_id: `ds:${modality}:demo`,
          analysis_id: 'preprocess',
          pipeline_id: preset,
          parameters: {},
        }),
      })

      const res = await POST(req)
      expect(res.status).toBe(200)
      const data = await res.json()
      expect(data.launch_decision).toEqual(
        expect.objectContaining({
          status: 'handoff_only',
          code: 'handoff_only',
          can_launch: false,
          primary_action: 'handoff',
        }),
      )
      expect(data.handoff_pack?.workflow_id).toBe(workflowId)
      expect(data.handoff_pack?.execution?.workflow_id).toBe(workflowId)
      expect(data.handoff_pack?.recipe_lookup?.tool_id).toBe(workflowId)
      expect(data.execution_status).toEqual(
        expect.objectContaining({
          recipe_generated: true,
          runtime_available: false,
          hosted_executed: false,
          artifact_verified: false,
          recommended_backend: 'local_backend',
        }),
      )
      expect(data.execution_status.message).toContain('local backend')
      expect(data.handoff_pack?.launch_trace).toEqual(
        expect.objectContaining({
          requested_analysis_id: 'preprocess',
          requested_pipeline_id: preset,
          canonical_analysis_id: 'dynamic_workflow',
          canonical_pipeline_id: workflowId,
          canonicalized: true,
          canonicalization_reason: 'legacy_pipeline_alias',
        }),
      )
    },
  )

  it('POST /api/plan/checks blocks launchable workflows with unknown credit estimate', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_unknown_runtime',
        stage: 'connectivity',
        cost_tier: 'moderate',
        description: 'Workflow without a usable estimate',
        modalities: ['fmri'],
        supported_recipe_targets: ['python'],
        execution_recipe_available: true,
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'step', tool: 'unknown_runtime_tool', params: {} }],
        },
      },
      version: 'vFinal',
    })
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: true,
        checks: [{ tool_id: 'unknown_runtime_tool', status: 'available', available: true }],
        warnings: [],
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_unknown_runtime',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const creditCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'credits_sufficient',
    )
    expect(creditCheck?.status).toBe('blocked')
    expect(creditCheck?.detail).toContain('Credit estimate unavailable')
    expect(data.launch_decision).toEqual(
      expect.objectContaining({
        can_launch: false,
        status: 'blocked',
        code: 'blocked_credit',
        primary_action: 'handoff',
      }),
    )
    expect(data.launch_decision.reason).toContain('Hosted launch blocked; MCP recipe available.')
  })

  it('POST /api/plan/checks reports manual/admin-only workflows as non-launchable decisions', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        id: 'workflow_manual_only',
        stage: 'connectivity',
        cost_tier: 'moderate',
        description: 'Manual launch workflow',
        modalities: ['fmri'],
        supported_recipe_targets: [],
        execution_recipe_available: false,
        agent_mode: 'manual_admin_only',
        launch_status: 'manual_admin_only',
        est_runtime: 'minutes',
        runtime: {
          kind: 'declarative_workflow',
          steps: [{ id: 'step', tool: 'manual_runtime_tool', params: {} }],
        },
      },
      version: 'vFinal',
    })
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: true,
        checks: [{ tool_id: 'manual_runtime_tool', status: 'available', available: true }],
        warnings: [],
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_manual_only',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const creditCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'credits_sufficient',
    )
    expect(creditCheck?.status).toBe('warning')
    expect(creditCheck?.detail).toContain('manual/admin-only workflow')
    expect(data.launch_decision).toEqual(
      expect.objectContaining({
        can_launch: false,
        status: 'manual_admin_only',
        code: 'manual_admin_only',
        primary_action: 'handoff',
      }),
    )
  })

  it('POST /api/plan/checks downgrades transient runtime unavailability to warning', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [{ tool_id: 'connectivity_matrix', status: 'timeout', available: false }],
        warnings: ['preflight timeout'],
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const runtimeCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'runtime_executable',
    )
    expect(runtimeCheck?.status).toBe('warning')
    expect(runtimeCheck?.detail).toContain('Unavailable runtime tools')
    expect(runtimeCheck?.detail).toContain('preflight timeout')
  })

  it('POST /api/plan/checks blocks when runtime preflight reports allowlist denial', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        executable: false,
        checks: [
          {
            requested_tool_id: 'connectivity_matrix',
            tool_id: 'connectivity_matrix',
            status: 'blocked',
            code: 'RUNTIME_TOOL_NOT_ALLOWED',
            available: false,
          },
        ],
        warnings: [],
      }),
    )

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'dynamic_workflow',
        pipeline_id: 'workflow_preprocessing_qc',
        parameters: {},
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const runtimeCheck = data.checks.find(
      (check: { id?: string }) => check.id === 'runtime_executable',
    )
    expect(runtimeCheck?.status).toBe('blocked')
    expect(runtimeCheck?.detail).toContain('Blocked by allowlist')
  })

  it('POST /api/plan/checks blocks multiverse runs when task metadata is missing and no task is provided', async () => {
    mockGetDataset.mockImplementation((id: string) => ({
      id,
      name: 'Task-less dataset',
      modalities: ['fmri'],
      tasks: [],
    }))

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:taskless:demo',
        analysis_id: 'multiverse_glm',
        pipeline_id: MULTIVERSE_PIPELINE_ID,
        parameters: { max_models: 3 },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const taskCheck = data.checks.find((check: { id?: string }) => check.id === 'task')
    expect(taskCheck?.status).toBe('blocked')
    expect(taskCheck?.detail).toContain('Dataset metadata does not list tasks')
  })

  it('POST /api/plan/checks downgrades to warning when multiverse task is provided but metadata has no task list', async () => {
    mockGetDataset.mockImplementation((id: string) => ({
      id,
      name: 'Task-less dataset',
      modalities: ['fmri'],
      tasks: [],
    }))

    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:taskless:demo',
        analysis_id: 'multiverse_glm',
        pipeline_id: MULTIVERSE_PIPELINE_ID,
        parameters: { task: 'nback', max_models: 3 },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    const taskCheck = data.checks.find((check: { id?: string }) => check.id === 'task')
    expect(taskCheck?.status).toBe('warning')
    expect(taskCheck?.detail).toContain('Proceeding with manually specified task')
    expect(data.effective_config?.analysis_id).toBe('multiverse_glm')
    expect(
      data.effective_config?.parameters?.some(
        (entry: { key?: string; origin?: string }) =>
          entry.key === 'task' && entry.origin === 'user',
      ),
    ).toBe(true)
  })

  it('POST /api/plan/checks keeps alias-derived origins and redacts sensitive fields in effective config', async () => {
    const { POST } = await import('@/app/api/plan/checks/route')
    const req = createRequest('http://test/api/plan/checks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:manual:abide',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        parameters: {
          connectivity_metric: 'partial correlation',
          api_key: 'super-secret-value',
          session_id: '01',
          metadata: {
            authorization: 'Bearer abc',
            nested: {
              api_key: 'nested-secret',
            },
          },
        },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(
      data.effective_config?.parameters?.some(
        (entry: { key?: string; origin?: string; value?: unknown }) =>
          entry.key === 'connectivity_kind' && entry.origin === 'user',
      ),
    ).toBe(true)
    expect(data.effective_config?.parameter_values?.api_key).toBe('[redacted]')
    expect(data.effective_config?.parameter_values?.session_id).toBe('01')
    expect(data.effective_config?.parameter_values?.metadata?.authorization).toBe('[redacted]')
    expect(data.effective_config?.parameter_values?.metadata?.nested?.api_key).toBe('[redacted]')
    expect(data.handoff_pack?.inputs?.api_key).toBe('[redacted]')
    expect(data.handoff_pack?.inputs?.metadata?.authorization).toBe('[redacted]')
    expect(
      data.effective_config?.parameters?.find(
        (entry: { key?: string }) => entry.key === 'api_key',
      )?.value,
    ).toBe('[redacted]')
  })
})
