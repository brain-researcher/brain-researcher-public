// @vitest-environment node
import { NextRequest, NextResponse } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/app/api/catalog/datasets/[datasetId]/resources/route', () => ({
  GET: vi.fn(),
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: vi.fn(),
}))

vi.mock('@/lib/server/credits', () => ({
  estimateCreditsFromRuntime: vi.fn(() => null),
  getCreditsBalance: vi.fn(),
  resolveCreditsIdentity: vi.fn(),
}))

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: vi.fn(() => new Headers({ authorization: 'Bearer test-token' })),
  resolveOrchestratorBaseUrl: vi.fn(() => 'http://localhost:3001'),
}))

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn(async () => true),
}))

vi.mock('@/lib/server/workflow-catalog', () => ({
  getWorkflowById: vi.fn(() => ({ workflow: null })),
}))

import { GET as getDatasetResources } from '@/app/api/catalog/datasets/[datasetId]/resources/route'
import { getDataset } from '@/lib/server/dataset-catalog'
import {
  estimateCreditsFromRuntime,
  getCreditsBalance,
  resolveCreditsIdentity,
} from '@/lib/server/credits'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { POST } from '../route'

const DATASET_ID = 'ds000001'
type DatasetResourcesResponse = Awaited<ReturnType<typeof getDatasetResources>>

function jsonResponse(body: unknown, status = 200): DatasetResourcesResponse {
  return NextResponse.json(body, {
    status,
  }) as DatasetResourcesResponse
}

function makeRequest(
  body: Record<string, unknown>,
  extraHeaders?: Record<string, string>,
): NextRequest {
  const headers = new Headers({ 'content-type': 'application/json' })
  for (const [key, value] of Object.entries(extraHeaders ?? {})) {
    headers.set(key, value)
  }
  return new NextRequest('http://localhost/api/plan/checks', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
}

async function postChecks(
  body: Record<string, unknown>,
  authed = true,
  extraHeaders?: Record<string, string>,
) {
  vi.mocked(isRequestAuthenticated).mockResolvedValue(authed)
  const response = await POST(makeRequest(body, extraHeaders))
  expect(response.status).toBe(200)
  return (await response.json()) as {
    checks: Array<{ id: string; status: string; detail?: string }>
    launch_decision?: {
      status?: string
      code?: string
      can_launch?: boolean
      primary_action?: string
      reason?: string
    }
    capability?: {
      canonical_workflow_id?: string | null
      hosted_launch?: {
        primary_action?: string
        reason?: string
      }
      mcp_recipe?: {
        status?: string
        supported_targets?: string[]
        preferred_target?: string | null
        recipe_call?: string | null
      }
    }
  }
}

function pickDataValidated(payload: { checks: Array<{ id: string; status: string; detail?: string }> }) {
  return payload.checks.find((check) => check.id === 'data_validated')
}

describe('/api/plan/checks data_validated readiness mapping', () => {
  beforeEach(() => {
    vi.mocked(getDataset).mockReturnValue({
      id: DATASET_ID,
      modalities: ['fmri'],
      tasks: ['nback'],
    } as any)
    vi.mocked(getDatasetResources).mockResolvedValue(
      jsonResponse({
        readiness: { status: 'ready' },
        required_files: { all_required_passed: true },
        source_access: { bucket_check: { state: 'verified_present' } },
      }),
    )
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('returns passed when readiness is ready', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: { status: 'ready', reason: 'All preflight checks passed' },
        required_files: { all_required_passed: true },
        source_access: { bucket_check: { state: 'verified_present' } },
      }),
    )

    const payload = await postChecks({
      dataset_id: DATASET_ID,
      dataset_version: 'v1.2.3',
    })
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('passed')
    expect(vi.mocked(getDatasetResources)).toHaveBeenCalledTimes(1)
    const [resourcesReq, params] = vi.mocked(getDatasetResources).mock.calls[0] as [
      NextRequest,
      { params: { datasetId: string } },
    ]
    expect(resourcesReq.nextUrl.pathname).toContain(`/api/catalog/datasets/${DATASET_ID}/resources`)
    expect(resourcesReq.nextUrl.searchParams.get('datasetVersion')).toBe('v1.2.3')
    expect(resourcesReq.nextUrl.searchParams.get('checkSourceAccess')).toBe('false')
    expect(params.params.datasetId).toBe(DATASET_ID)
  })

  it('returns warning that distinguishes mounted partial data from source metadata checks', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: {
          status: 'partial',
          reason: 'Resources available with non-blocking dataset notes',
          local_path_available: true,
        },
        required_files: { all_required_passed: true },
        source_access: {
          bucket_check: {
            state: 'skipped',
            message: 'skipped for local-fast dataset asset resolution',
          },
        },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID })
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('warning')
    expect(check?.detail).toContain('Resources available with non-blocking dataset notes')
    expect(check?.detail).toContain('could not confirm underlying file accessibility')
  })

  it('returns blocked when readiness is explicitly blocked', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: {
          status: 'blocked',
          reason: 'BIDS path not available on mounts/cache',
        },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID })
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('blocked')
    expect(check?.detail).toContain('BIDS path not available')
  })

  it('forwards auth-related request headers to the internal readiness route', async () => {
    await postChecks(
      { dataset_id: DATASET_ID },
      true,
      {
        authorization: 'Bearer user-token',
        cookie: 'next-auth.session-token=abc123',
        'x-workspace-id': 'ws-demo',
      },
    )

    expect(vi.mocked(getDatasetResources)).toHaveBeenCalledTimes(1)
    const [resourcesReq] = vi.mocked(getDatasetResources).mock.calls[0] as unknown as [NextRequest]
    expect(resourcesReq.headers.get('authorization')).toBe('Bearer user-token')
    expect(resourcesReq.headers.get('cookie')).toContain('next-auth.session-token=abc123')
    expect(resourcesReq.headers.get('x-workspace-id')).toBe('ws-demo')
  })

  it('returns warning when readiness is unavailable/unknown', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        unavailable: true,
        readiness: { status: 'unknown' },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID })
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('warning')
    expect(check?.detail).toContain('could not confirm underlying file accessibility')
  })

  it('returns warning for auth_required when user is authenticated', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: {
          status: 'auth_required',
          reason: 'Sign in to run backend readiness checks.',
        },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID }, true)
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('warning')
  })

  it('returns blocked for auth_required when user is unauthenticated', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: {
          status: 'auth_required',
          reason: 'Sign in to run backend readiness checks.',
        },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID }, false)
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('blocked')
  })

  it('downgrades conflicting readiness signals to warning', async () => {
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: { status: 'ready', reason: 'Readiness gate passed' },
        required_files: { all_required_passed: true },
        source_access: {
          bucket_check: {
            state: 'permission_denied',
            message: 'Bucket denies listing',
          },
        },
      }),
    )

    const payload = await postChecks({ dataset_id: DATASET_ID })
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('warning')
    expect(check?.detail).toContain('Readiness gate passed')
  })

  it('returns warning when readiness check times out', async () => {
    vi.useFakeTimers()
    vi.mocked(getDatasetResources).mockImplementationOnce(
      () => new Promise<DatasetResourcesResponse>(() => undefined),
    )

    const pending = postChecks({ dataset_id: DATASET_ID })
    await vi.advanceTimersByTimeAsync(2600)
    const payload = await pending
    const check = pickDataValidated(payload)
    expect(check?.status).toBe('warning')
    expect(check?.detail).toContain('timed out after 2500ms')
  })

  it('keeps ds000114 hosted launch blocked while exposing MCP recipe handoff', async () => {
    vi.mocked(getDataset).mockReturnValue({
      id: 'ds:openneuro:ds000114',
      name: 'A test-retest fMRI dataset',
      source_repo: 'OpenNeuro',
      source_repo_id: 'ds000114',
      primary_url: 'https://openneuro.org/datasets/ds000114',
      modalities: ['fmri'],
      tasks: ['covertverbgeneration'],
      tags: [],
      category: 'OpenNeuro',
      access_type: 'public',
      subjects_count: 10,
      sessions_count: 2,
      license: 'CC0',
    } as any)
    vi.mocked(getDatasetResources).mockResolvedValueOnce(
      jsonResponse({
        readiness: {
          status: 'degraded',
          reason:
            'Backend readiness checks timed out. Static OpenNeuro source addresses are available, but mount and file readiness were not verified.',
        },
        source_access: {
          bucket_check: {
            state: 'unreachable',
            message: 'Backend readiness check timed out; using static OpenNeuro address hints.',
          },
        },
      }),
    )
    vi.mocked(getWorkflowById).mockReturnValue({
      version: 'test',
      workflow: {
        id: 'workflow_rest_connectome_e2e',
        stage: 'connectivity',
        cost_tier: 'expensive',
        description: 'Resting-state connectome workflow',
        modalities: ['fmri'],
        supported_recipe_targets: ['python'],
        primary_target: 'python',
        execution_recipe_available: true,
        agent_mode: 'local_recipe',
        launch_status: 'recipe_launchable',
        runtime: { kind: 'declarative_workflow', steps: [] },
      },
    } as any)
    vi.mocked(estimateCreditsFromRuntime).mockReturnValueOnce(1)
    vi.mocked(resolveCreditsIdentity).mockResolvedValueOnce({ subject: 'user:test' } as any)
    vi.mocked(getCreditsBalance).mockResolvedValueOnce({ balance: 0 } as any)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        NextResponse.json({
          executable: true,
          checks: [],
        }),
      ),
    )

    const payload = await postChecks({
      dataset_id: 'ds:openneuro:ds000114',
      analysis_id: 'connectivity',
      pipeline_id: 'nilearn_connectivity',
    })

    expect(pickDataValidated(payload)?.status).toBe('warning')
    expect(payload.launch_decision).toEqual(
      expect.objectContaining({
        status: 'blocked',
        code: 'blocked_credit',
        can_launch: false,
        primary_action: 'handoff',
      }),
    )
    expect(payload.launch_decision?.reason).toContain('Hosted launch blocked; MCP recipe available.')
    expect(payload.capability?.canonical_workflow_id).toBe('workflow_rest_connectome_e2e')
    expect(payload.capability?.mcp_recipe).toEqual(
      expect.objectContaining({
        status: 'available',
        supported_targets: ['python'],
        preferred_target: 'python',
      }),
    )
    expect(payload.capability?.mcp_recipe?.recipe_call).toContain('workflow_rest_connectome_e2e')
    expect(payload.capability?.mcp_recipe?.recipe_call).toContain('"dataset_id": "ds000114"')
    expect(payload.capability?.hosted_launch?.primary_action).toBe('handoff')
  })
})
