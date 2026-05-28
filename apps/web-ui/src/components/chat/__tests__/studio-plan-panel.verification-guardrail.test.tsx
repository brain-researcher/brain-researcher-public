// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StudioPlanPanel } from '../studio-plan-panel'

const navigationMock = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}))

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'u1' } }, status: 'authenticated' }),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => navigationMock.searchParams,
}))

vi.mock('@/lib/brain-researcher-api', () => ({
  brainResearcherAPI: {
    fetchWorkflowById: vi.fn(),
  },
}))

vi.mock('@/lib/service-endpoints', () => ({
  resolveKgConceptSummaryUrl: (id: string) => `/api/kg/concept/${id}/summary`,
}))

vi.mock('@/components/chat/use-dag-step-status', () => ({
  useDagStepStatusByOrder: () => ({}),
}))

const DATASET_ID = 'ds000001'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type FetchMode = 'checks_error' | 'checks_ok' | 'checks_guidance' | 'checks_handoff_only'

function installFetchMock(mode: FetchMode) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()

    if (url === '/api/plan/checks') {
      if (mode === 'checks_error') {
        throw new Error('verification service unavailable')
      }
      if (mode === 'checks_guidance') {
        return jsonResponse({
          checks: [
            { id: 'data_validated', label: 'Data validated', status: 'passed' },
            { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
            { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
            {
              id: 'runtime_executable',
              label: 'Runtime executable',
              status: 'blocked',
              detail: 'Missing runtime tools: fmriprep',
            },
            {
              id: 'credits_sufficient',
              label: 'Credits sufficient',
              status: 'warning',
              detail: 'Credits estimate may vary.',
            },
          ],
          estimate: { runtime: '~1h', credits: 12 },
          execution_status: {
            recipe_generated: true,
            runtime_available: false,
            hosted_executed: false,
            artifact_verified: false,
            runtime_scope: 'hosted_preflight',
            recommended_backend: 'local_backend',
            message: 'Heavy workflow should run on a local backend using the generated MCP recipe.',
          },
          effective_config: {
            analysis_id: 'preprocess',
            pipeline_id: 'fmriprep',
            pipeline_label: 'fMRIPrep',
            pipeline_type: 'preprocessing',
            tool_id: 'run_bids_app',
            dataset_id: DATASET_ID,
            dataset_version: '1.0.0',
            parameters: [
              { key: 'dataset_id', origin: 'base', value: DATASET_ID },
              { key: 'bids_dir', origin: 'inferred', value: '/app/data/openneuro/ds000001' },
            ],
            parameter_values: {
              dataset_id: DATASET_ID,
              bids_dir: '/app/data/openneuro/ds000001',
            },
          },
          guidance: {
            kind: 'neurodesk_setup_required',
            runtime_target: 'neurodesk',
            install_path: 'app',
            summary: 'Requires Neurodesk modules to run',
            detail: 'Install Neurodesk App locally or use Neurodesk Play in the browser.',
            required_modules: ['fmriprep/23.2.1', 'mriqc/24.0.2'],
            required_env_vars: ['FREESURFER_HOME'],
            next_action_url: 'https://neurodesk.org/getting-started/local/neurodeskapp/',
            actions: [
              {
                id: 'neurodesk-play',
                label: 'Try Neurodesk Play',
                href: 'https://play.neurodesk.org/',
              },
              {
                id: 'neurodesk-app',
                label: 'Install Neurodesk App',
                href: 'https://neurodesk.org/getting-started/local/neurodeskapp/',
              },
            ],
          },
        })
      }
      if (mode === 'checks_handoff_only') {
        return jsonResponse({
          checks: [
            { id: 'data_validated', label: 'Data validated', status: 'passed' },
            { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
            { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
            { id: 'runtime_executable', label: 'Runtime executable', status: 'passed' },
            {
              id: 'credits_sufficient',
              label: 'Credits sufficient',
              status: 'warning',
              detail: 'Credit checks are skipped for handoff-only workflows.',
            },
          ],
          estimate: { runtime: '~1h', credits: null },
          launch_decision: {
            status: 'handoff_only',
            code: 'handoff_only',
            can_launch: false,
            primary_action: 'handoff',
            reason: 'This workflow does not advertise a launchable recipe in the current environment.',
          },
          effective_config: {
            analysis_id: 'preprocess',
            pipeline_id: 'fmriprep',
            pipeline_label: 'fMRIPrep',
            pipeline_type: 'preprocessing',
            tool_id: 'run_bids_app',
            dataset_id: DATASET_ID,
            dataset_version: '1.0.0',
            parameters: [
              { key: 'dataset_id', origin: 'base', value: DATASET_ID },
              { key: 'bids_dir', origin: 'inferred', value: '/app/data/openneuro/ds000001' },
            ],
            parameter_values: {
              dataset_id: DATASET_ID,
              bids_dir: '/app/data/openneuro/ds000001',
            },
          },
        })
      }
      return jsonResponse({
        checks: [
          { id: 'data_validated', label: 'Data validated', status: 'passed' },
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
          { id: 'runtime_executable', label: 'Runtime executable', status: 'passed' },
          {
            id: 'credits_sufficient',
            label: 'Credits sufficient',
            status: 'warning',
            detail: 'Credits estimate may vary.',
          },
        ],
        estimate: { runtime: '~1h', credits: 12 },
        effective_config: {
          analysis_id: 'preprocess',
          pipeline_id: 'fmriprep',
          pipeline_label: 'fMRIPrep',
          pipeline_type: 'preprocessing',
          tool_id: 'run_bids_app',
          dataset_id: DATASET_ID,
          dataset_version: '1.0.0',
          parameters: [
            { key: 'dataset_id', origin: 'base', value: DATASET_ID },
            { key: 'bids_dir', origin: 'inferred', value: '/app/data/openneuro/ds000001' },
          ],
          parameter_values: {
            dataset_id: DATASET_ID,
            bids_dir: '/app/data/openneuro/ds000001',
          },
        },
      })
    }

    if (url === '/api/pipelines') {
      return jsonResponse({ pipelines: [] })
    }

    if (url.startsWith(`/api/catalog/datasets/${DATASET_ID}/resources`)) {
      return jsonResponse({
        dataset_ref: DATASET_ID,
        source_kind: 'openneuro',
        versions: [{ id: '1.0.0', label: '1.0.0', source: 'default', availability: 'available' }],
        default_version: '1.0.0',
        selected_version: '1.0.0',
        addresses: {},
      })
    }

    if (url === `/api/catalog/datasets/${DATASET_ID}`) {
      return jsonResponse({
        id: DATASET_ID,
        name: 'Mock Dataset',
        description: 'Test dataset',
        category: 'fmri',
        modalities: ['fmri'],
        acquisitions: [],
        access_type: 'public',
        license: 'cc0',
        source_repo: 'openneuro',
        primary_url: `https://openneuro.org/datasets/${DATASET_ID}`,
        tags: [],
        tasks: ['nback'],
        has_derivatives: false,
        preview_media: [],
        species: ['human'],
        disease_flags: [],
        search_blob: '',
      })
    }

    return jsonResponse({}, 404)
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function countPlanChecksCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([input]) => {
    const url = typeof input === 'string' ? input : input.toString()
    return url === '/api/plan/checks'
  }).length
}

describe('StudioPlanPanel verification guardrail', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    navigationMock.searchParams = new URLSearchParams()
  })

  it('blocks run when /api/plan/checks is unavailable', async () => {
    const fetchMock = installFetchMock('checks_error')

    render(<StudioPlanPanel datasetId={DATASET_ID} initialPipelineId="fmriprep" />)

    const runButton = await screen.findByRole('button', { name: /^Run$/i }, { timeout: 3000 })
    expect(runButton).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))

    expect(
      await screen.findByText(/Verification unavailable:/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect((await screen.findAllByText('Verification service available')).length).toBeGreaterThan(0)
    expect(fetchMock).not.toHaveBeenCalledWith('/api/analyses', expect.anything())
  })

  it('keeps run enabled when checks succeed and hides manual editing behind Advanced', async () => {
    installFetchMock('checks_ok')

    render(<StudioPlanPanel datasetId={DATASET_ID} initialPipelineId="fmriprep" />)

    expect(screen.queryByText(/Verification unavailable:/i)).toBeNull()
    expect(screen.queryByText(/credits/i)).toBeNull()
    expect(screen.queryByText('Effective Run Config')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Configure' })).toBeNull()

    const runButton = await screen.findByRole('button', { name: /^Run$/i }, { timeout: 3000 })
    await waitFor(() => expect(runButton).toBeEnabled(), { timeout: 3000 })

    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))

    expect(
      await screen.findByText('Effective Run Config', undefined, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Configure' })).toBeInTheDocument()
  })

  it('shows Neurodesk setup guidance and supports re-checking blocked runtime setup', async () => {
    const fetchMock = installFetchMock('checks_guidance')

    render(<StudioPlanPanel datasetId={DATASET_ID} initialPipelineId="fmriprep" />)

    expect(await screen.findByText('Neurodesk setup', undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('Requires Neurodesk modules to run')).toBeInTheDocument()
    expect(screen.getByText('Install Neurodesk App locally or use Neurodesk Play in the browser.')).toBeInTheDocument()
    expect(
      screen.getByText('Heavy workflow should run on a local backend using the generated MCP recipe.'),
    ).toBeInTheDocument()
    expect(screen.getByText('recipe_generated')).toBeInTheDocument()
    expect(screen.getByText('hosted_executed')).toBeInTheDocument()
    expect(screen.getByText('fmriprep/23.2.1, mriqc/24.0.2')).toBeInTheDocument()
    expect(screen.getByText('FREESURFER_HOME')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in Neurodesk Play' })).toHaveAttribute(
      'href',
      'https://play.neurodesk.org/',
    )
    expect(screen.getByRole('link', { name: 'Install Neurodesk App' })).toHaveAttribute(
      'href',
      'https://neurodesk.org/getting-started/local/neurodeskapp/',
    )

    const initialChecksCalls = countPlanChecksCalls(fetchMock)
    fireEvent.click(screen.getByRole('button', { name: 'Re-check environment' }))

    await waitFor(() => {
      expect(countPlanChecksCalls(fetchMock)).toBeGreaterThan(initialChecksCalls)
    })
  })

  it('hides fix-review controls from normal Studio runtime', async () => {
    installFetchMock('checks_guidance')

    render(
      <StudioPlanPanel
        datasetId={DATASET_ID}
        initialPipelineId="fmriprep"
        onAskAgent={vi.fn()}
      />,
    )

    expect(await screen.findByText('Neurodesk setup', undefined, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))
    await waitFor(() => {
      expect(screen.getAllByText('Runtime executable').length).toBeGreaterThan(0)
    })
    expect(screen.queryByRole('button', { name: 'Ask Agent to fix' })).toBeNull()
    expect(screen.queryByText('Showing fix')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
  })

  it('opens a recipe-aware handoff modal for handoff-only launch decisions', async () => {
    installFetchMock('checks_handoff_only')

    render(
      <StudioPlanPanel
        datasetId={DATASET_ID}
        initialPipelineId="fmriprep"
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /advanced/i }, { timeout: 3000 }))
    const handoffButton = await screen.findByRole(
      'button',
      { name: /Hand off to Codex\/Cursor/i },
      { timeout: 3000 },
    )
    await waitFor(() => expect(handoffButton).toBeEnabled(), { timeout: 3000 })
    await screen.findByText('Handoff only', undefined, { timeout: 3000 })

    fireEvent.click(handoffButton)

    expect(await screen.findByText('Hand off Studio plan')).toBeInTheDocument()
    expect(screen.getByText(/get_execution_recipe/)).toBeInTheDocument()
    expect(screen.getByText(/workflow_fmriprep_preprocessing/)).toBeInTheDocument()
    expect(screen.getAllByText(/"dataset_id": "ds000001"/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Hosted launch status:/)).toBeInTheDocument()
  })

  it('shows fix-review controls when Studio review debug mode is enabled', async () => {
    navigationMock.searchParams = new URLSearchParams('studioReviewDebug=1')
    installFetchMock('checks_guidance')

    render(
      <StudioPlanPanel
        datasetId={DATASET_ID}
        initialPipelineId="fmriprep"
        onAskAgent={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /advanced/i }, { timeout: 3000 }))
    expect(
      await screen.findByRole('button', { name: 'Ask Agent to fix' }, { timeout: 3000 }),
    ).toBeInTheDocument()
  })
})
