import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunsSidebar } from '../RunsSidebar'

const mocks = vi.hoisted(() => ({
  appendHubSessionCell: vi.fn(),
  fetchSidebarRuns: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/lib/api/hub-sessions', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/hub-sessions')>(
      '@/lib/api/hub-sessions',
    )
  return {
    ...actual,
    appendHubSessionCell: mocks.appendHubSessionCell,
  }
})

vi.mock('@/lib/api/runs', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/runs')>('@/lib/api/runs')
  return {
    ...actual,
    fetchSidebarRuns: mocks.fetchSidebarRuns,
  }
})

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mocks.toast }),
}))

const SAMPLE_RUNS = [
  {
    run_id: 'run_active_1',
    status: 'running' as const,
    source: 'external' as const,
    project_id: 'proj_demo',
    workflow_id: 'glm_v1',
    dataset_id: 'ds:openneuro:ds000001',
    thread_id: null,
    intent: null,
    title: 'Within-DMN connectivity',
    task: 'rest',
    dataset_label: 'OpenNeuro ds000001',
    workflow_label: 'Nilearn first-level',
    artifact_count: null,
    step_count: null,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    updated_at: new Date(Date.now() - 30_000).toISOString(),
    finished_at: null,
    error_message: null,
  },
  {
    run_id: 'run_done_1',
    status: 'completed' as const,
    source: 'internal' as const,
    project_id: 'proj_demo',
    workflow_id: 'connectivity_v2',
    dataset_id: 'ds:openneuro:ds000002',
    thread_id: null,
    intent: null,
    title: null,
    task: null,
    dataset_label: null,
    workflow_label: null,
    artifact_count: null,
    step_count: null,
    created_at: new Date(Date.now() - 600_000).toISOString(),
    updated_at: new Date(Date.now() - 500_000).toISOString(),
    finished_at: new Date(Date.now() - 500_000).toISOString(),
    error_message: null,
  },
  {
    run_id: 'run_unknown_1',
    status: 'completed' as const,
    source: 'unknown' as const,
    project_id: 'proj_demo',
    workflow_id: null,
    dataset_id: null,
    thread_id: null,
    intent: null,
    title: null,
    task: null,
    dataset_label: null,
    workflow_label: null,
    artifact_count: null,
    step_count: null,
    created_at: new Date(Date.now() - 900_000).toISOString(),
    updated_at: new Date(Date.now() - 900_000).toISOString(),
    finished_at: new Date(Date.now() - 900_000).toISOString(),
    error_message: null,
  },
]

describe('RunsSidebar', () => {
  beforeEach(() => {
    mocks.fetchSidebarRuns.mockReset()
    mocks.appendHubSessionCell.mockReset()
    mocks.toast.mockReset()
    mocks.fetchSidebarRuns.mockResolvedValue(SAMPLE_RUNS)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders run rows from the fetcher with source badges', async () => {
    render(<RunsSidebar brSessionId="studio_demo" runtimeReady={true} />)
    fireEvent.click(screen.getByTestId('runs-sidebar-trigger'))
    await waitFor(() => expect(mocks.fetchSidebarRuns).toHaveBeenCalled())
    expect(
      await screen.findByTestId('runs-sidebar-row-run_active_1'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('runs-sidebar-source-run_active_1').textContent,
    ).toMatch(/External agent/)
    expect(
      screen.getByTestId('runs-sidebar-source-run_done_1').textContent,
    ).toMatch(/Studio/)
    // A run with no known source no longer shows the misleading "Unknown source"
    // badge at all.
    expect(
      screen.queryByTestId('runs-sidebar-source-run_unknown_1'),
    ).toBeNull()
  })

  it('renders a human title, task chip, and dataset label from the enriched facets', async () => {
    render(<RunsSidebar brSessionId="studio_demo" runtimeReady={true} />)
    fireEvent.click(screen.getByTestId('runs-sidebar-trigger'))
    await waitFor(() => expect(mocks.fetchSidebarRuns).toHaveBeenCalled())
    const row = await screen.findByTestId('runs-sidebar-row-run_active_1')
    // Title prefers the human title over the raw workflow_id.
    expect(row.textContent).toMatch(/Within-DMN connectivity/)
    expect(row.textContent).not.toMatch(/glm_v1/)
    // Task/paradigm chip is surfaced.
    expect(
      screen.getByTestId('runs-sidebar-task-run_active_1').textContent,
    ).toMatch(/rest/)
    // Dataset shows the human label, not the raw id.
    expect(row.textContent).toMatch(/OpenNeuro ds000001/)
    expect(row.textContent).not.toMatch(/ds:openneuro:ds000001/)
  })

  it('disables Attach in notebook when runtime is not ready', async () => {
    render(<RunsSidebar brSessionId="studio_demo" runtimeReady={false} />)
    fireEvent.click(screen.getByTestId('runs-sidebar-trigger'))
    await waitFor(() => expect(mocks.fetchSidebarRuns).toHaveBeenCalled())
    const attach = (await screen.findByTestId(
      'runs-sidebar-attach-run_active_1',
    )) as HTMLButtonElement
    expect(attach.disabled).toBe(true)
  })

  it('POSTs to hub-sessions/cells on Attach click and shows success toast', async () => {
    mocks.appendHubSessionCell.mockResolvedValue({
      cell_id: 'cell-xxx',
      runtime_session_id: 'rt_demo',
    })
    render(<RunsSidebar brSessionId="studio_demo" runtimeReady={true} />)
    fireEvent.click(screen.getByTestId('runs-sidebar-trigger'))
    await waitFor(() => expect(mocks.fetchSidebarRuns).toHaveBeenCalled())
    const attach = await screen.findByTestId('runs-sidebar-attach-run_active_1')
    fireEvent.click(attach)
    await waitFor(() => {
      expect(mocks.appendHubSessionCell).toHaveBeenCalledWith(
        'studio_demo',
        expect.stringContaining("br.attach_run('run_active_1')"),
      )
    })
    // Server path doesn't live-render in the connected frontend, so the toast
    // must tell the user to reload rather than imply the cell is already visible.
    await waitFor(() => {
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: expect.stringContaining('to the runtime'),
          description: expect.stringContaining('Reload the notebook'),
        }),
      )
    })
  })

  it('shows a live success toast when the client bridge injects the cell', async () => {
    const appendCellClient = vi.fn().mockResolvedValue(undefined)
    render(
      <RunsSidebar
        brSessionId="studio_demo"
        runtimeReady={true}
        appendCellClient={appendCellClient}
      />,
    )
    fireEvent.click(screen.getByTestId('runs-sidebar-trigger'))
    await waitFor(() => expect(mocks.fetchSidebarRuns).toHaveBeenCalled())
    const attach = await screen.findByTestId('runs-sidebar-attach-run_active_1')
    fireEvent.click(attach)
    await waitFor(() =>
      expect(appendCellClient).toHaveBeenCalledWith(
        expect.stringContaining("br.attach_run('run_active_1')"),
      ),
    )
    // Bridge path renders live, so no server call and the toast says "to notebook".
    expect(mocks.appendHubSessionCell).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: expect.stringContaining('to notebook'),
        }),
      )
    })
  })
})
