import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DatasetDetailResponse } from '@/types/datasets-search'
import { DatasetDetailView, displaySizeHuman } from '../dataset-detail-view'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('displaySizeHuman', () => {
  it('does not surface NaN placeholders as human-readable size values', () => {
    expect(displaySizeHuman('nan')).toBe('N/A')
    expect(displaySizeHuman('NaN GB')).toBe('N/A')
    expect(displaySizeHuman('  n/a  ')).toBe('N/A')
  })

  it('keeps valid human-readable size values', () => {
    expect(displaySizeHuman('12.4 GB')).toBe('12.4 GB')
  })
})

describe('DatasetDetailView', () => {
  const baseDataset: DatasetDetailResponse = {
    id: 'ds:manual:abcd',
    name: 'ABCD Study',
    description: 'Longitudinal cohort dataset',
    category: 'Population',
    modalities: ['MRI', 'fMRI'],
    acquisitions: ['T1w', 'BOLD'],
    subjects_count: 11000,
    sessions_count: 1,
    access_type: 'registration',
    license: 'custom',
    source_repo: 'NIMH Data Archive',
    source_repo_id: 'ds:manual:abcd',
    primary_url: 'https://abcdstudy.org',
    tags: [],
    tasks: ['resting'],
    has_derivatives: false,
    preview_media: [],
    size_human: 'NaN GB',
    species: ['human'],
    disease_flags: [],
    search_blob: '',
  }

  it('renders placeholder size values as unavailable metadata', () => {
    render(<DatasetDetailView dataset={baseDataset} />)
    const accessTab = screen.getByRole('tab', { name: 'Files & Access' })
    fireEvent.mouseDown(accessTab, { button: 0, ctrlKey: false })
    fireEvent.click(accessTab)

    const sizeRow = screen.getByText('Approximate size').closest('div')
    expect(sizeRow).not.toBeNull()
    expect(within(sizeRow as HTMLElement).getByText('N/A')).toBeInTheDocument()
    expect(screen.queryByText('NaN GB')).not.toBeInTheDocument()
  })

  it('renders degraded ds000114 timeout fallback as static source hints', () => {
    render(
      <DatasetDetailView
        dataset={{
          ...baseDataset,
          id: 'ds:openneuro:ds000114',
          name: 'A test-retest fMRI dataset',
          source_repo: 'OpenNeuro',
          source_repo_id: 'ds000114',
          access_type: 'public',
          resource_addresses: {
            dataset_ref: 'ds:openneuro:ds000114',
            source_kind: 'openneuro',
            addresses: {
              openneuro_url: 'https://openneuro.org/datasets/ds000114',
              s3_uri: 's3://openneuro.org/ds000114',
            },
            source_access: {
              provider: 'openneuro',
              bucket_uri: 's3://openneuro.org/ds000114',
              bucket_check: {
                state: 'unreachable',
                message: 'Backend readiness check timed out; using static OpenNeuro address hints.',
              },
              version_check: {
                mode: 'metadata_only',
              },
            },
            readiness: {
              status: 'degraded',
              reason:
                'Backend readiness checks timed out. Static OpenNeuro source addresses are available, but mount and file readiness were not verified.',
            },
            unavailable: false,
            error: 'resource_readiness_timeout_after_5000ms',
          },
        }}
      />,
    )

    expect(screen.getByText(/Resource status:/)).toHaveTextContent('Resource status: Degraded')
    expect(screen.getByText('https://openneuro.org/datasets/ds000114')).toBeInTheDocument()
    expect(screen.getByText('s3://openneuro.org/ds000114')).toBeInTheDocument()
    expect(screen.queryByText(/Address resolution unavailable/)).not.toBeInTheDocument()
    const bucketCheck = screen.getByText('Bucket check:').closest('div')
    expect(bucketCheck).toHaveTextContent('unreachable')
    expect(bucketCheck).toHaveTextContent('static OpenNeuro address hints')
    expect(bucketCheck).not.toHaveTextContent('via none')
  })

  it('uses an explicit placeholder in dataset-level handoff recipe prompts', async () => {
    render(<DatasetDetailView dataset={baseDataset} />)

    fireEvent.click(screen.getByRole('button', { name: /^Hand off$/ }))

    await waitFor(() => {
      expect(screen.getByText('Hand off workflow')).toBeInTheDocument()
    })
    expect(screen.getByText(/tool_id="<workflow_id>"/)).toBeInTheDocument()
    expect(screen.queryByText(/tool_id="workflow_id"/)).not.toBeInTheDocument()
    expect(screen.getByText(/workflow_id: <workflow_id>/)).toBeInTheDocument()
  })

  it('renders ds000114 fMRIPrep as a canonical workflow handoff in the launch modal', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/pipelines') {
        return new Response(JSON.stringify({ pipelines: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url === '/api/plan/checks') {
        return new Response(
          JSON.stringify({
            checks: [
              {
                id: 'runtime_executable',
                label: 'Runtime executable',
                status: 'blocked',
                detail: 'Blocked by allowlist: run_bids_app',
              },
            ],
            launch_decision: {
              status: 'handoff_only',
              code: 'handoff_only',
              can_launch: false,
              primary_action: 'handoff',
              reason: 'Hosted Studio cannot execute fMRIPrep directly.',
            },
            guidance: {
              kind: 'recipe_handoff_required',
              runtime_target: 'container',
              summary: 'Hosted Studio cannot execute fMRIPrep directly.',
              detail: 'Required environment variables: FS_LICENSE.',
              required_env_vars: ['FS_LICENSE'],
              supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
              container_images: {
                fmriprep: 'nipreps/fmriprep:23.2.3',
              },
            },
            handoff_pack: {
              workflow_id: 'workflow_fmriprep_preprocessing',
              plan_id: 'plan_fmriprep_ds000114',
            },
          }),
          {
            status: 200,
            headers: { 'content-type': 'application/json' },
          },
        )
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <DatasetDetailView
        dataset={{
          ...baseDataset,
          id: 'ds:openneuro:ds000114',
          name: 'A test-retest fMRI dataset',
          source_repo: 'OpenNeuro',
          source_repo_id: 'ds000114',
          access_type: 'public',
          subjects_count: 10,
          sessions_count: 2,
        }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Run analysis/i }))
    fireEvent.click(screen.getByRole('button', { name: /Preprocessing & QC/i }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /fMRIPrep/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /fMRIPrep/i }))

    await waitFor(() => {
      expect(screen.getByText('Get MCP recipe for local execution')).toBeInTheDocument()
    })
    const planCheckCall = fetchMock.mock.calls.find(([input]) => String(input) === '/api/plan/checks')
    const planCheckBody = planCheckCall?.[1]?.body
    expect(typeof planCheckBody).toBe('string')
    expect(JSON.parse(planCheckBody as string)).toEqual(
      expect.objectContaining({
        dataset_id: 'ds:openneuro:ds000114',
        analysis_id: 'preprocess',
        pipeline_id: 'fmriprep',
      }),
    )
    expect(screen.getAllByText(/Hosted Studio cannot execute fMRIPrep directly/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Long-running workflows can take tens of minutes to hours/)).toBeInTheDocument()
    expect(screen.getByText(/Runtime: container/)).toBeInTheDocument()
    expect(screen.getByText(/Env: FS_LICENSE/)).toBeInTheDocument()
    expect(screen.getByText(/Targets: neurodesk, container, slurm/)).toBeInTheDocument()
    expect(screen.getByText(/Images: nipreps\/fmriprep:23.2.3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Launch analysis/i })).toBeDisabled()
    const handoffButtons = screen.getAllByRole('button', { name: /^Hand off$/ })
    expect(handoffButtons.length).toBeGreaterThan(0)
    expect(handoffButtons[0]).toBeEnabled()
  })

  it('makes MCP handoff primary when ds000114 hosted launch is blocked by credits', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/pipelines') {
        return new Response(JSON.stringify({ pipelines: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url === '/api/plan/checks') {
        return new Response(
          JSON.stringify({
            checks: [
              {
                id: 'data_validated',
                label: 'Data validated',
                status: 'warning',
                detail:
                  'Backend readiness checks timed out. Static OpenNeuro source addresses are available, but mount and file readiness were not verified.',
              },
              {
                id: 'credits_sufficient',
                label: 'Credits sufficient',
                status: 'blocked',
                detail: 'Need 1 credits; available 0.',
              },
            ],
            launch_decision: {
              status: 'blocked',
              code: 'blocked_credit',
              can_launch: false,
              primary_action: 'handoff',
              reason: 'Need 1 credits; available 0. Hosted launch blocked; MCP recipe available.',
            },
            capability: {
              canonical_workflow_id: 'workflow_rest_connectome_e2e',
              hosted_launch: {
                status: 'blocked',
                code: 'blocked_credit',
                can_launch: false,
                primary_action: 'handoff',
                reason: 'Need 1 credits; available 0. Hosted launch blocked; MCP recipe available.',
              },
              mcp_recipe: {
                status: 'available',
                supported_targets: ['python'],
                preferred_target: 'python',
                handoff_prompt: 'Use get_execution_recipe for workflow_rest_connectome_e2e on ds000114.',
              },
            },
            handoff_pack: {
              workflow_id: 'workflow_rest_connectome_e2e',
              recipe_lookup: {
                params: {
                  dataset_id: 'ds000114',
                  atlas_name: 'Schaefer2018_200',
                },
              },
            },
          }),
          {
            status: 200,
            headers: { 'content-type': 'application/json' },
          },
        )
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <DatasetDetailView
        dataset={{
          ...baseDataset,
          id: 'ds:openneuro:ds000114',
          name: 'A test-retest fMRI dataset',
          source_repo: 'OpenNeuro',
          source_repo_id: 'ds000114',
          access_type: 'public',
          subjects_count: 10,
          sessions_count: 2,
        }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Run analysis/i }))
    fireEvent.click(screen.getByRole('button', { name: /Connectivity & Parcellation/i }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Nilearn Connectivity/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /Nilearn Connectivity/i }))

    await waitFor(() => {
      expect(screen.getByText(/Hosted blocked, MCP recipe still available/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/Need 1 credits; available 0/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /Launch analysis/i })).toBeDisabled()

    const handoffButtons = screen.getAllByRole('button', { name: /^Hand off$/ })
    const modalHandoff = handoffButtons[handoffButtons.length - 1]
    expect(modalHandoff).toBeEnabled()
    fireEvent.click(modalHandoff)

    await waitFor(() => {
      expect(screen.getByText('Hand off workflow')).toBeInTheDocument()
    })
    expect(screen.getByText(/workflow_rest_connectome_e2e/)).toBeInTheDocument()
    expect(screen.getByText(/Use get_execution_recipe for workflow_rest_connectome_e2e on ds000114/)).toBeInTheDocument()
    expect(screen.getByText(/params=\{"dataset_id": "ds000114", "atlas_name": "Schaefer2018_200"\}/)).toBeInTheDocument()
  })
})
