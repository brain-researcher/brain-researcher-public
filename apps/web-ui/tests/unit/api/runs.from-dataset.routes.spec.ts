import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'
import { makeToolSuccessResponse, makeJsonResponse } from '../helpers/fetch-mocks'

const mockFetch = vi.fn()
global.fetch = mockFetch
const mockGetDataset = vi.fn()

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: () => new Headers(),
  resolveAgentBaseUrl: () => 'http://agent',
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

vi.mock('@/lib/server/dataset-catalog', () => ({
  getDataset: mockGetDataset,
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: runs/from-dataset', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('injects preprocessing defaults when bids_dir/output_dir are missing', async () => {
    mockFetch.mockResolvedValueOnce(
      makeJsonResponse({
        run_id: 'run_001',
        status: 'queued',
      }),
    )

    const { POST } = await import('@/app/api/runs/from-dataset/route')
    const req = createRequest('http://test/api/runs/from-dataset', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'preprocess',
        pipeline_id: 'fmriprep',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toContain('http://orchestrator/run')

    const upstreamBody = JSON.parse(String(mockFetch.mock.calls[0]?.[1]?.body ?? '{}'))
    const args = upstreamBody.parameters?._client_metadata?.plan_envelope?.steps?.[0]?.args ?? {}
    expect(args.bids_dir).toBe('/app/data/openneuro/ds000114')
    expect(String(args.output_dir || '')).toContain('/app/data/shared/runs/ds000114/fmriprep')
  })

  it('injects connectivity workflow defaults and infers img from bids_dir for nilearn_connectivity', async () => {
    const bidsDir = '/data/bids/ds000114'
    const resolvedBoldImg = '/data/bids/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz'
    mockFetch
      .mockResolvedValueOnce(makeToolSuccessResponse({ outputs: { resolved_path: resolvedBoldImg } }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          run_id: 'run_conn_001',
          status: 'queued',
        }),
      )

    const { POST } = await import('@/app/api/runs/from-dataset/route')
    const req = createRequest('http://test/api/runs/from-dataset', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        params: {
          bids_dir: bidsDir,
        },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = JSON.parse(
      String(mockFetch.mock.calls[mockFetch.mock.calls.length - 1]?.[1]?.body ?? '{}'),
    )
    const clientPlan = upstreamBody.parameters?._client_metadata?.plan_envelope ?? {}
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

  it('normalizes connectivity kind aliases for nilearn_connectivity', async () => {
    const bidsDir = '/data/bids/ds000114'
    mockFetch
      .mockResolvedValueOnce(
        makeToolSuccessResponse({
          outputs: { resolved_path: '/data/bids/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz' },
        }),
      )
      .mockResolvedValueOnce(
        makeJsonResponse({
          run_id: 'run_conn_002',
          status: 'queued',
        }),
      )

    const { POST } = await import('@/app/api/runs/from-dataset/route')
    const req = createRequest('http://test/api/runs/from-dataset', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
        params: {
          bids_dir: bidsDir,
          connectivity_kind: 'partial-correlation',
        },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = JSON.parse(
      String(mockFetch.mock.calls[mockFetch.mock.calls.length - 1]?.[1]?.body ?? '{}'),
    )
    const args = upstreamBody.parameters?._client_metadata?.plan_envelope?.steps?.[0]?.args ?? {}
    expect(args.connectivity_kind).toBe('partial correlation')
  })

  it('injects GLM defaults and infers img from bids_dir for nilearn_glm', async () => {
    const resolvedBoldImg = '/app/data/openneuro/ds000114/sub-01/func/sub-01_task-rest_bold.nii.gz'
    mockFetch
      .mockResolvedValueOnce(makeToolSuccessResponse({ outputs: { resolved_path: resolvedBoldImg } }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          run_id: 'run_glm_001',
          status: 'queued',
        }),
      )

    const { POST } = await import('@/app/api/runs/from-dataset/route')
    const req = createRequest('http://test/api/runs/from-dataset', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'glm',
        pipeline_id: 'nilearn_glm',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)

    const upstreamBody = JSON.parse(
      String(mockFetch.mock.calls[mockFetch.mock.calls.length - 1]?.[1]?.body ?? '{}'),
    )
    const clientPlan = upstreamBody.parameters?._client_metadata?.plan_envelope ?? {}
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

  it('does not fail fast when connectivity img cannot be verified by web-ui filesystem', async () => {
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
          run_id: 'run_conn_fallback_001',
          status: 'queued',
        }),
      )

    const { POST } = await import('@/app/api/runs/from-dataset/route')
    const req = createRequest('http://test/api/runs/from-dataset', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'connectivity',
        pipeline_id: 'nilearn_connectivity',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(201)
    const upstreamBody = JSON.parse(
      String(mockFetch.mock.calls[mockFetch.mock.calls.length - 1]?.[1]?.body ?? '{}'),
    )
    const plan = upstreamBody.parameters?._client_metadata?.plan_envelope ?? {}
    const args = plan.steps?.[0]?.args ?? {}
    expect(plan.steps?.[0]?.tool).toBe('workflow_rest_connectome_e2e')
    expect(args.img).toBe(
      '/app/data/openneuro/ds000114/sub-01/ses-test/func/sub-01_ses-test_task-covertverbgeneration_bold.nii.gz',
    )
    expect(args.session_id).toBe('test')
    expect(args.task_id).toBe('covertverbgeneration')
  })
})
