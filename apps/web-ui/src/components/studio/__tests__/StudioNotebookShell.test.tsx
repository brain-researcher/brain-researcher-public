// @vitest-environment jsdom

import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, beforeEach, expect, it, vi } from 'vitest'

const {
  createOrAttachStudioSession,
  buildWorkspaceHandoff,
  getStudioAssistantState,
  submitStudioAssistantTurn,
} = vi.hoisted(() => ({
  createOrAttachStudioSession: vi.fn(),
  buildWorkspaceHandoff: vi.fn(),
  getStudioAssistantState: vi.fn(),
  submitStudioAssistantTurn: vi.fn(),
}))

vi.mock('@/lib/api/studio-sessions', () => ({
  createOrAttachStudioSession,
  buildWorkspaceHandoff,
}))

vi.mock('@/lib/api/studio-notebook', () => ({
  openOrCreateStudioNotebook: vi.fn(),
  saveStudioNotebook: vi.fn(),
  executeStudioNotebookCell: vi.fn(),
}))

vi.mock('@/lib/api/studio-assistant', () => ({
  getStudioAssistantState,
  submitStudioAssistantTurn,
}))

vi.mock('../assistant/StudioAssistantPane', () => ({
  StudioAssistantPane: ({
    assistantPrompt,
    onAssistantPromptChange,
    onSubmitPrompt,
  }: {
    assistantPrompt: string
    onAssistantPromptChange: (value: string) => void
    onSubmitPrompt: () => void
  }) => (
    <div data-testid="studio-assistant-pane">
      <label className="sr-only" htmlFor="studio-assistant-prompt">
        Studio assistant prompt
      </label>
      <textarea
        id="studio-assistant-prompt"
        aria-label="Studio assistant prompt"
        value={assistantPrompt}
        onChange={(event) => onAssistantPromptChange(event.target.value)}
      />
      <button type="button" onClick={onSubmitPrompt}>
        Send
      </button>
    </div>
  ),
}))

vi.mock('../notebook/StudioNotebookPanel', () => ({
  StudioNotebookPanel: () => <div data-testid="studio-notebook-panel" />,
}))

import { StudioNotebookShell } from '../StudioNotebookShell'

describe('StudioNotebookShell', () => {
  const openSpy = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('open', openSpy)

    createOrAttachStudioSession.mockResolvedValue({
      id: 'studio_session_1',
      project_id: 'proj_studio_demo',
      owner_user_id: 'user_123',
      display_name: 'Studio Session',
      runtime_profile_id: 'standard',
      runtime_session_id: 'runtime_123',
      assistant_session_id: 'assistant_123',
      status: 'ready',
      metadata: {},
      created_at: '2026-03-30T00:00:00Z',
      updated_at: '2026-03-30T00:00:00Z',
      last_activity_at: '2026-03-30T00:00:00Z',
    })
    buildWorkspaceHandoff.mockResolvedValue({
      project_id: 'proj_studio_demo',
      runtime_session_id: 'runtime_123',
      runtime_profile_id: 'standard',
      launch_mode: 'reuse_active_runtime',
      workspace_url: 'https://hub.brain-researcher.com/user/demo/lab',
      target_path: 'projects/proj_studio_demo/notebooks/studio/studio_session_1.ipynb',
      notebook_path: 'projects/proj_studio_demo/notebooks/studio/studio_session_1.ipynb',
      open_artifact_id: null,
      initial_focus: 'notebook',
      materialize_notebook_if_needed: true,
    })
    getStudioAssistantState.mockResolvedValue({ messages: [] })
    submitStudioAssistantTurn.mockResolvedValue({
      assistant_session_id: 'assistant_123',
      thread: {
        thread_id: 'thread_123',
        title: 'Studio thread',
        created_at: '2026-03-30T00:00:00Z',
        updated_at: '2026-03-30T00:00:00Z',
        message_count: 2,
        context: {},
        metadata: {},
        scenario_id: 'studio_notebook_assistant',
      },
      messages: [],
      user_message: {
        id: 'msg_user_1',
        thread_id: 'thread_123',
        role: 'user',
        content: 'Generate a notebook scaffold.',
        timestamp: '2026-03-30T00:00:00Z',
        metadata: {},
      },
      assistant_message: {
        id: 'msg_assistant_1',
        thread_id: 'thread_123',
        role: 'assistant',
        content: 'Drafting notebook cells...',
        timestamp: '2026-03-30T00:00:00Z',
        metadata: {},
      },
      plan: {
        assistant_message: 'Drafting notebook cells...',
        ops: [],
        source: 'agent_typed',
      },
      notebook: {
        id: 'nb_studio_session_1',
        project_id: 'proj_studio_demo',
        session_id: 'studio_session_1',
        path: 'projects/proj_studio_demo/notebooks/studio/studio_session_1.ipynb',
        title: 'Studio Session notebook',
        kernel_name: 'python3',
        format: 'ipynb',
        metadata: {},
        created_at: '2026-03-30T00:00:00Z',
        updated_at: '2026-03-30T00:00:00Z',
        last_saved_at: null,
        revision: 1,
        cells: [],
      },
    })
  })

  it('creates a session, builds a handoff, and opens the workspace', async () => {
    render(<StudioNotebookShell />)

    fireEvent.click(screen.getByRole('button', { name: /launch workspace/i }))

    await waitFor(() => {
      expect(createOrAttachStudioSession).toHaveBeenCalledTimes(1)
      expect(buildWorkspaceHandoff).toHaveBeenCalledTimes(1)
      expect(openSpy).toHaveBeenCalledWith(
        'https://hub.brain-researcher.com/user/demo/lab',
        '_blank',
        'noopener,noreferrer',
      )
    })
  })

  it('reuses an existing handoff instead of rebuilding it on the next launch', async () => {
    render(<StudioNotebookShell />)

    fireEvent.click(screen.getByRole('button', { name: /launch workspace/i }))

    await waitFor(() => {
      expect(buildWorkspaceHandoff).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(screen.getByRole('button', { name: /launch workspace/i }))

    await waitFor(() => {
      expect(buildWorkspaceHandoff).toHaveBeenCalledTimes(1)
      expect(openSpy).toHaveBeenCalledTimes(2)
    })
  })

  it('surfaces a compact fallback banner when the assistant planner degrades', async () => {
    submitStudioAssistantTurn.mockResolvedValueOnce({
      assistant_session_id: 'assistant_123',
      thread: {
        thread_id: 'thread_123',
        title: 'Studio thread',
        created_at: '2026-03-30T00:00:00Z',
        updated_at: '2026-03-30T00:00:00Z',
        message_count: 2,
        context: {},
        metadata: {},
        scenario_id: 'studio_notebook_assistant',
      },
      messages: [
        {
          id: 'msg_assistant_1',
          thread_id: 'thread_123',
          role: 'assistant',
          content: 'Drafting notebook cells...',
          timestamp: '2026-03-30T00:00:00Z',
          metadata: {
            planner_source: 'heuristic_fallback',
            fallback_reason: 'Using the local notebook heuristic.',
          },
        },
      ],
      user_message: {
        id: 'msg_user_1',
        thread_id: 'thread_123',
        role: 'user',
        content: 'Generate a notebook scaffold.',
        timestamp: '2026-03-30T00:00:00Z',
        metadata: {},
      },
      assistant_message: {
        id: 'msg_assistant_1',
        thread_id: 'thread_123',
        role: 'assistant',
        content: 'Drafting notebook cells...',
        timestamp: '2026-03-30T00:00:00Z',
        metadata: {},
      },
      plan: {
        assistant_message: 'Drafting notebook cells...',
        ops: [],
        source: 'heuristic_fallback',
        fallback_reason: 'Using the local notebook heuristic.',
      },
      notebook: {
        id: 'nb_studio_session_1',
        project_id: 'proj_studio_demo',
        session_id: 'studio_session_1',
        path: 'projects/proj_studio_demo/notebooks/studio/studio_session_1.ipynb',
        title: 'Studio Session notebook',
        kernel_name: 'python3',
        format: 'ipynb',
        metadata: {},
        created_at: '2026-03-30T00:00:00Z',
        updated_at: '2026-03-30T00:00:00Z',
        last_saved_at: null,
        revision: 1,
        cells: [],
      },
    })

    render(<StudioNotebookShell />)

    fireEvent.change(screen.getByLabelText(/studio assistant prompt/i), {
      target: { value: 'Generate a notebook scaffold.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(submitStudioAssistantTurn).toHaveBeenCalledTimes(1)
      expect(screen.getByText(/planner fallback/i)).toBeInTheDocument()
      expect(
        screen.getByText(/using the local notebook heuristic\./i),
      ).toBeInTheDocument()
    })
  })

  it('uses the session-scoped notebook path on first turn after implicit session creation', async () => {
    render(<StudioNotebookShell />)

    fireEvent.change(screen.getByLabelText(/studio assistant prompt/i), {
      target: { value: 'Generate a notebook scaffold.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(submitStudioAssistantTurn).toHaveBeenCalledTimes(1)
    })

    expect(submitStudioAssistantTurn).toHaveBeenCalledWith(
      'studio_session_1',
      expect.objectContaining({
        notebook: expect.objectContaining({
          path: 'projects/proj_studio_demo/notebooks/studio/studio_session_1.ipynb',
          session_id: 'studio_session_1',
        }),
      }),
    )
  })
})
