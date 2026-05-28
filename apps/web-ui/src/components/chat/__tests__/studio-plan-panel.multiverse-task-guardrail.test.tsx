// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StudioPlanPanel } from '../studio-plan-panel'

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'u1' } }, status: 'authenticated' }),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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
const SECOND_DATASET_ID = 'ds000002'
const MULTIVERSE_PIPELINE_ID = 'fmri_glm_multiverse_openneuro'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function installFetchMock(options?: {
  tasks?: string[]
  datasetTasksById?: Record<string, string[]>
}) {
  const tasks = options?.tasks ?? []
  const datasetTasksById = options?.datasetTasksById ?? { [DATASET_ID]: tasks }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()

    if (url === '/api/plan/checks') {
      const payload =
        typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, any>) : {}
      const payloadDatasetId =
        typeof payload?.dataset_id === 'string' ? payload.dataset_id : DATASET_ID
      const tasksForDataset = datasetTasksById[payloadDatasetId] ?? []
      const taskRaw = payload?.parameters?.task
      const task = typeof taskRaw === 'string' ? taskRaw.trim() : ''
      const normalizedTask = task.toLowerCase().replace(/[^a-z0-9]+/g, '')
      const normalizedTasks = tasksForDataset.map((entry) =>
        entry.toLowerCase().replace(/[^a-z0-9]+/g, ''),
      )
      const hasTaskMetadata = normalizedTasks.length > 0

      const taskCheck = !task
        ? {
            id: 'task',
            label: 'Task selected',
            status: 'blocked',
            detail: hasTaskMetadata
              ? 'Select a task for multiverse analysis.'
              : 'Dataset metadata does not list tasks. Enter a task explicitly to run multiverse analysis.',
          }
        : hasTaskMetadata
          ? {
              id: 'task',
              label: 'Task selected',
              status: normalizedTasks.includes(normalizedTask) ? 'passed' : 'warning',
              detail: normalizedTasks.includes(normalizedTask)
                ? undefined
                : 'Selected task was not found in the dataset metadata. Proceed with caution.',
            }
          : {
              id: 'task',
              label: 'Task selected',
              status: 'warning',
              detail:
                'Dataset metadata does not list tasks. Proceeding with manually specified task; verify task context carefully.',
            }

      return jsonResponse({
        checks: [
          { id: 'data_validated', label: 'Data validated', status: 'passed' },
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
          taskCheck,
          { id: 'runtime_executable', label: 'Runtime executable', status: 'passed' },
          {
            id: 'credits_sufficient',
            label: 'Credits sufficient',
            status: 'warning',
            detail: 'Credits estimate may vary.',
          },
        ],
        estimate: { runtime: '~1h', credits: 12 },
      })
    }

    if (url === '/api/pipelines') {
      return jsonResponse({ pipelines: [] })
    }

    const resourcesMatch = url.match(/^\/api\/catalog\/datasets\/([^/]+)\/resources(?:\?.*)?$/)
    if (resourcesMatch) {
      const datasetRef = decodeURIComponent(resourcesMatch[1] || '')
      return jsonResponse({
        dataset_ref: datasetRef,
        source_kind: 'openneuro',
        versions: [{ id: '1.0.0', label: '1.0.0', source: 'default', availability: 'available' }],
        default_version: '1.0.0',
        selected_version: '1.0.0',
        addresses: {},
      })
    }

    const datasetMatch = url.match(/^\/api\/catalog\/datasets\/([^/]+)$/)
    if (datasetMatch) {
      const datasetRef = decodeURIComponent(datasetMatch[1] || '')
      const tasksForDataset = datasetTasksById[datasetRef] ?? []
      return jsonResponse({
        id: datasetRef,
        name: 'Mock Dataset',
        description: 'Test dataset',
        category: 'fmri',
        modalities: ['fmri'],
        acquisitions: [],
        access_type: 'public',
        license: 'cc0',
        source_repo: 'openneuro',
        primary_url: `https://openneuro.org/datasets/${datasetRef}`,
        tags: [],
        tasks: tasksForDataset,
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

describe('StudioPlanPanel multiverse task guardrail', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  function openAdvanced() {
    const trigger = screen.getByTestId('plan-advanced-toggle')
    if (trigger.getAttribute('aria-expanded') === 'true') return
    act(() => {
      fireEvent.click(trigger)
    })
  }

  it('requires explicit task entry when dataset metadata has no task context', async () => {
    installFetchMock({ tasks: [] })

    render(
      <StudioPlanPanel datasetId={DATASET_ID} initialPipelineId={MULTIVERSE_PIPELINE_ID} />,
    )

    const runButton = await screen.findByRole('button', { name: /^Run$/i }, { timeout: 3000 })
    openAdvanced()
    const taskInput = await screen.findByPlaceholderText(/Enter task label/i, undefined, {
      timeout: 3000,
    })

    expect(
      await screen.findAllByText(
        'Dataset metadata does not list tasks. Enter a task explicitly to run multiverse analysis.',
        undefined,
        { timeout: 5000 },
      ),
    ).toHaveLength(2)
    expect(runButton).toBeDisabled()

    act(() => {
      fireEvent.change(taskInput, { target: { value: 'nback' } })
    })

    expect(
      await screen.findAllByText(
        'Dataset metadata does not list tasks. Proceeding with manually specified task; verify task context carefully.',
        undefined,
        { timeout: 5000 },
      ),
    ).toHaveLength(2)
    const warningRunButton = await screen.findByRole('button', { name: /Run with warnings/i }, { timeout: 5000 })
    expect(warningRunButton).toBeEnabled()
  })

  it('shows task selector when dataset metadata includes tasks', async () => {
    installFetchMock({ tasks: ['nback'] })

    render(
      <StudioPlanPanel datasetId={DATASET_ID} initialPipelineId={MULTIVERSE_PIPELINE_ID} />,
    )

    openAdvanced()
    expect(
      await screen.findByRole('combobox', { name: 'Task' }, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Enter task label/i)).toBeNull()
    expect(screen.queryByText(/Dataset metadata does not list tasks/i)).toBeNull()
  })

  it('clears stale task selection when switching to a taskless dataset', async () => {
    installFetchMock({
      datasetTasksById: {
        [DATASET_ID]: ['nback'],
        [SECOND_DATASET_ID]: [],
      },
    })

    const { rerender } = render(
      <StudioPlanPanel datasetId={DATASET_ID} initialPipelineId={MULTIVERSE_PIPELINE_ID} />,
    )

    openAdvanced()
    const taskSelect = await screen.findByRole('combobox', { name: 'Task' }, { timeout: 4000 })
    act(() => {
      fireEvent.change(taskSelect, { target: { value: 'nback' } })
    })
    await waitFor(() => expect((taskSelect as HTMLSelectElement).value).toBe('nback'))

    act(() => {
      rerender(
        <StudioPlanPanel
          datasetId={SECOND_DATASET_ID}
          initialPipelineId={MULTIVERSE_PIPELINE_ID}
        />,
      )
    })

    openAdvanced()
    const taskInput = await screen.findByPlaceholderText(/Enter task label/i, undefined, {
      timeout: 5000,
    })
    expect((taskInput as HTMLInputElement).value).toBe('')
    expect(
      await screen.findAllByText(
        'Dataset metadata does not list tasks. Enter a task explicitly to run multiverse analysis.',
        undefined,
        { timeout: 5000 },
      ),
    ).toHaveLength(2)
  })

  it('keeps restored task draft for the same dataset on mount', async () => {
    installFetchMock({ tasks: ['nback'] })
    window.localStorage.setItem(
      'br:plan:default',
      JSON.stringify({
        version: 1,
        updated_at: Date.now(),
        dataset_id: DATASET_ID,
        analysis_id: 'multiverse_glm',
        pipeline_id: MULTIVERSE_PIPELINE_ID,
        task: 'nback',
      }),
    )

    render(
      <StudioPlanPanel datasetId={DATASET_ID} initialPipelineId={MULTIVERSE_PIPELINE_ID} />,
    )

    openAdvanced()
    const taskSelect = await screen.findByRole('combobox', { name: 'Task' }, { timeout: 4000 })
    await waitFor(() => expect((taskSelect as HTMLSelectElement).value).toBe('nback'))
  })

  it('clears restored task when moving from no dataset to a different selected dataset', async () => {
    installFetchMock({
      datasetTasksById: {
        [DATASET_ID]: ['nback'],
        [SECOND_DATASET_ID]: [],
      },
    })
    window.localStorage.setItem(
      'br:plan:default',
      JSON.stringify({
        version: 1,
        updated_at: Date.now(),
        dataset_id: DATASET_ID,
        analysis_id: 'multiverse_glm',
        pipeline_id: MULTIVERSE_PIPELINE_ID,
        task: 'nback',
      }),
    )

    const { rerender } = render(<StudioPlanPanel initialPipelineId={MULTIVERSE_PIPELINE_ID} />)

    act(() => {
      rerender(
        <StudioPlanPanel
          datasetId={SECOND_DATASET_ID}
          initialPipelineId={MULTIVERSE_PIPELINE_ID}
        />,
      )
    })

    openAdvanced()
    const taskInput = await screen.findByPlaceholderText(/Enter task label/i, undefined, {
      timeout: 5000,
    })
    expect((taskInput as HTMLInputElement).value).toBe('')
  })
})
