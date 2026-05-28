import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { isRequestAuthenticated } from '@/lib/server/request-auth'

const mockGetWorkflowById = vi.fn()
const mockFetchWorkflowRuntimePreflight = vi.fn()
const mockRunWorkflowTool = vi.fn()

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/lib/server/workflow-catalog', () => ({
  getWorkflowById: mockGetWorkflowById,
}))

vi.mock('@/lib/server/workflow-execution', () => ({
  fetchWorkflowRuntimePreflight: mockFetchWorkflowRuntimePreflight,
  runWorkflowTool: mockRunWorkflowTool,
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

const SPATIAL_CORRELATION_WORKFLOW = {
  id: 'workflow_spatial_correlation',
  stage: 'interpretation',
  cost_tier: 'moderate',
  lifecycle: 'active',
  origin: 'trend_addition',
  description: 'Spatial correlation workflow',
  modalities: [],
  est_runtime: '10 min',
  supported_recipe_targets: ['python'],
  execution_recipe_available: true,
  agent_mode: 'local_recipe',
  launch_status: 'recipe_launchable' as const,
  impl: 'workflow: query_neuromaps -> compare_surface_maps',
  params: {
    schema: {
      type: 'object' as const,
      required: ['reference_term', 'map_file'],
      properties: {
        reference_term: { type: 'string' as const },
        map_file: { type: 'string' as const },
        n_perm: { type: 'integer' as const, default: 1000 },
        output_dir: { type: 'string' as const, default: '/tmp/out' },
      },
    },
    defaults: {
      output_dir: '/tmp/brain-researcher/workflow_spatial_correlation',
    },
  },
  runtime: {
    kind: 'declarative_workflow',
    steps: [
      {
        id: 'fetch_reference',
        tool: 'query_neuromaps',
        params: {
          term: '${inputs.reference_term}',
          output_file: '${inputs.output_dir}/query.json',
        },
      },
      {
        id: 'spatial_corr',
        tool: 'compare_surface_maps',
        params: {
          map1: '${inputs.map_file}',
          map2: '${steps.fetch_reference.data.outputs.map_path}',
          null_permutations: '${inputs.n_perm}',
          output_file: '${inputs.output_dir}/spatial.json',
        },
      },
    ],
  },
}

const SEED_BASED_CONNECTIVITY_WORKFLOW = {
  ...SPATIAL_CORRELATION_WORKFLOW,
  id: 'workflow_seed_based_connectivity',
}

const DEPRECATED_SPATIAL_CORRELATION_WORKFLOW = {
  ...SPATIAL_CORRELATION_WORKFLOW,
  lifecycle: 'deprecated' as const,
}

describe('Workflow single-run routes', () => {
  const authMock = vi.mocked(isRequestAuthenticated)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(true)
    mockGetWorkflowById.mockReturnValue({
      workflow: SPATIAL_CORRELATION_WORKFLOW,
      version: 'vFinal',
    })
    mockFetchWorkflowRuntimePreflight.mockResolvedValue({
      ok: true,
      status: 200,
      payload: {
        executable: true,
        checks: [{ tool_id: 'query_neuromaps', status: 'available', available: true }],
        warnings: [],
      },
    })
    mockRunWorkflowTool.mockResolvedValue({
      ok: true,
      status: 200,
      payload: {
        tool: 'workflow_spatial_correlation',
        result: {
          status: 'success',
          data: { output_file: '/tmp/spatial.json' },
        },
      },
    })
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('GET /api/workflows/:id/schema returns resolved defaults', async () => {
    const { GET } = await import('@/app/api/workflows/[workflowId]/schema/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/schema')
    const res = await GET(req, {
      params: { workflowId: 'workflow_spatial_correlation' },
    })
    expect(res.status).toBe(200)

    const data = await res.json()
    expect(data.workflow_id).toBe('workflow_spatial_correlation')
    expect(data.direct_run_enabled).toBe(true)
    expect(data.defaults.merged.n_perm).toBe(1000)
    expect(data.defaults.merged.output_dir).toBe('/tmp/brain-researcher/workflow_spatial_correlation')
    expect(data.schema.required).toEqual(['reference_term', 'map_file'])
  })

  it('POST /api/workflows/:id/preflight blocks missing required params', async () => {
    const { POST } = await import('@/app/api/workflows/[workflowId]/preflight/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/preflight', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(422)
    const data = await res.json()
    expect(data.error.code).toBe('WF_PARAMS_INVALID')
    expect(mockFetchWorkflowRuntimePreflight).not.toHaveBeenCalled()
  })

  it('POST /api/workflows/:id/preflight returns resolved params and runtime checks', async () => {
    const { POST } = await import('@/app/api/workflows/[workflowId]/preflight/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/preflight', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.ok).toBe(true)
    expect(data.resolved_params.n_perm).toBe(1000)
    expect(data.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tool_id: 'query_neuromaps', status: 'available' }),
      ]),
    )
  })

  it('POST /api/workflows/:id/preflight forwards runtime setup guidance on conflict', async () => {
    mockFetchWorkflowRuntimePreflight.mockResolvedValueOnce({
      ok: true,
      status: 200,
      payload: {
        executable: false,
        checks: [{ tool_id: 'run_bids_app', status: 'missing', available: false }],
        warnings: ['Runtime tool inventory unavailable: timeout'],
        guidance: {
          kind: 'neurodesk_setup_required',
          access_mode: 'self_setup_required',
          runtime_target: 'neurodesk',
          install_path: 'app',
          summary: 'This workflow depends on a Neurodesk-backed runtime.',
          next_action_url: 'https://neurodesk.org/getting-started/local/neurodeskapp/',
          actions: [
            { id: 'neurodesk-play', label: 'Try Neurodesk Play', href: 'https://play.neurodesk.org/' },
          ],
        },
      },
    })

    const { POST } = await import('@/app/api/workflows/[workflowId]/preflight/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/preflight', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error.code).toBe('WF_PREFLIGHT_FAILED')
    expect(data.guidance.kind).toBe('neurodesk_setup_required')
    expect(data.error.details.guidance.runtime_target).toBe('neurodesk')
    expect(data.error.details.guidance.actions[0].href).toBe('https://play.neurodesk.org/')
  })

  it('POST /api/workflows/:id/execute runs the workflow tool', async () => {
    const { POST } = await import('@/app/api/workflows/[workflowId]/execute/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/execute', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
        preflight_required: false,
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.status).toBe('success')
    expect(data.workflow_id).toBe('workflow_spatial_correlation')
    expect(mockRunWorkflowTool).toHaveBeenCalledWith(
      expect.anything(),
      'workflow_spatial_correlation',
      expect.objectContaining({
        reference_term: 'default mode network',
        map_file: '/tmp/map.func.gii',
        n_perm: 1000,
      }),
    )
    expect(mockFetchWorkflowRuntimePreflight).toHaveBeenCalledWith(
      expect.anything(),
      'workflow_spatial_correlation',
    )
  })

  it('POST /api/workflows/:id/execute blocks production direct run when credit estimate is unknown', async () => {
    vi.resetModules()
    vi.stubEnv('NODE_ENV', 'production')
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        ...SPATIAL_CORRELATION_WORKFLOW,
        est_runtime: 'minutes',
      },
      version: 'vFinal',
    })

    const { POST } = await import('@/app/api/workflows/[workflowId]/execute/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/execute', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error.code).toBe('WF_CREDIT_ESTIMATE_UNAVAILABLE')
    expect(mockFetchWorkflowRuntimePreflight).not.toHaveBeenCalled()
    expect(mockRunWorkflowTool).not.toHaveBeenCalled()
  })

  it('POST /api/workflows/:id/execute blocks manual/admin-only workflows before runtime preflight', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: {
        ...SPATIAL_CORRELATION_WORKFLOW,
        supported_recipe_targets: [],
        execution_recipe_available: false,
        agent_mode: 'manual_admin_only',
        launch_status: 'manual_admin_only' as const,
      },
      version: 'vFinal',
    })

    const { POST } = await import('@/app/api/workflows/[workflowId]/execute/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/execute', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(409)
    const data = await res.json()
    expect(data.error.code).toBe('WF_MANUAL_ADMIN_ONLY')
    expect(data.launch_status).toBe('manual_admin_only')
    expect(mockFetchWorkflowRuntimePreflight).not.toHaveBeenCalled()
    expect(mockRunWorkflowTool).not.toHaveBeenCalled()
  })

  it('POST /api/workflows/:id/execute allows seed-based workflow in principle', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: SEED_BASED_CONNECTIVITY_WORKFLOW,
      version: 'vFinal',
    })
    const { POST } = await import('@/app/api/workflows/[workflowId]/execute/route')
    const req = createRequest('http://test/api/workflows/workflow_seed_based_connectivity/execute', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {},
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_seed_based_connectivity' } })
    expect(res.status).toBe(422)
    const data = await res.json()
    expect(data.error.code).toBe('WF_PARAMS_INVALID')
  })

  it('POST /api/workflows/:id/execute rejects deprecated workflows for direct run', async () => {
    mockGetWorkflowById.mockReturnValueOnce({
      workflow: DEPRECATED_SPATIAL_CORRELATION_WORKFLOW,
      version: 'vFinal',
    })
    const { POST } = await import('@/app/api/workflows/[workflowId]/execute/route')
    const req = createRequest('http://test/api/workflows/workflow_spatial_correlation/execute', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        params: {
          reference_term: 'default mode network',
          map_file: '/tmp/map.func.gii',
        },
      }),
    })

    const res = await POST(req, { params: { workflowId: 'workflow_spatial_correlation' } })
    expect(res.status).toBe(400)
    const data = await res.json()
    expect(data.error.code).toBe('WF_NOT_ENABLED')
    expect(mockFetchWorkflowRuntimePreflight).not.toHaveBeenCalled()
    expect(mockRunWorkflowTool).not.toHaveBeenCalled()
  })
})
