import '@testing-library/jest-dom/vitest'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const createOrAttachStudioSessionMock = vi.fn()
const getStudioAssistantStateMock = vi.fn()
const submitStudioAssistantTurnMock = vi.fn()

vi.mock('@/lib/api/studio-sessions', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/studio-sessions')>(
    '@/lib/api/studio-sessions',
  )
  return {
    ...actual,
    createOrAttachStudioSession: (...args: unknown[]) =>
      createOrAttachStudioSessionMock(...args),
  }
})

vi.mock('@/lib/api/studio-assistant', () => ({
  getStudioAssistantState: (...args: unknown[]) =>
    getStudioAssistantStateMock(...args),
  submitStudioAssistantTurn: (...args: unknown[]) =>
    submitStudioAssistantTurnMock(...args),
}))

import { StudioNotebookShell } from '@/components/studio/StudioNotebookShell'

describe('StudioNotebookShell', () => {
  beforeEach(() => {
    createOrAttachStudioSessionMock.mockReset()
    getStudioAssistantStateMock.mockReset()
    submitStudioAssistantTurnMock.mockReset()

    createOrAttachStudioSessionMock.mockResolvedValue({
      id: 'studio_demo123',
      project_id: 'proj_studio_demo',
      owner_user_id: 'user_demo',
      display_name: 'Studio Session',
      runtime_profile_id: 'standard',
      runtime_session_id: 'rt_demo123',
      assistant_session_id: 'ast_demo123',
      status: 'ready',
      metadata: {},
      created_at: '2026-03-28T00:00:00Z',
      updated_at: '2026-03-28T00:00:00Z',
      last_activity_at: '2026-03-28T00:00:00Z',
    })

    getStudioAssistantStateMock.mockResolvedValue({
      assistant_session_id: 'ast_demo123',
      thread: {
        thread_id: 'thread_demo123',
        title: 'Studio Session assistant',
        created_at: '2026-03-28T00:00:00Z',
        updated_at: '2026-03-28T00:00:00Z',
        message_count: 3,
        context: {},
        metadata: {},
      },
      messages: [
        {
          id: 'msg_bootstrap',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content:
            'Tell me what notebook you want to generate. I can draft cells, revise existing cells, and explain the next analysis step.',
          timestamp: '2026-03-28T00:00:00Z',
          metadata: {},
        },
        {
          id: 'msg_user_1',
          thread_id: 'thread_demo123',
          role: 'user',
          content: '请创建一个 markdown cell 写研究目标，再加一个 python cell 打印 hello',
          timestamp: '2026-03-28T00:00:01Z',
          metadata: {},
        },
        {
          id: 'msg_assistant_1',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content: 'Added one markdown cell and one code cell from BR assistant.',
          timestamp: '2026-03-28T00:00:02Z',
          metadata: {},
        },
      ],
    })

    submitStudioAssistantTurnMock.mockResolvedValue({
      assistant_session_id: 'ast_demo123',
      thread: {
        thread_id: 'thread_demo123',
        title: 'Studio Session assistant',
        created_at: '2026-03-28T00:00:00Z',
        updated_at: '2026-03-28T00:00:02Z',
        message_count: 3,
        context: {},
        metadata: {},
      },
      messages: [
        {
          id: 'msg_bootstrap',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content:
            'Tell me what notebook you want to generate. I can draft cells, revise existing cells, and explain the next analysis step.',
          timestamp: '2026-03-28T00:00:00Z',
          metadata: {},
        },
        {
          id: 'msg_user_1',
          thread_id: 'thread_demo123',
          role: 'user',
          content: '请创建一个 markdown cell 写研究目标，再加一个 python cell 打印 hello',
          timestamp: '2026-03-28T00:00:01Z',
          metadata: {},
        },
        {
          id: 'msg_assistant_1',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content: 'Added one markdown cell and one code cell from BR assistant.',
          timestamp: '2026-03-28T00:00:02Z',
          metadata: {},
        },
      ],
      user_message: {
        id: 'msg_user_1',
        thread_id: 'thread_demo123',
        role: 'user',
        content: '请创建一个 markdown cell 写研究目标，再加一个 python cell 打印 hello',
        timestamp: '2026-03-28T00:00:01Z',
        metadata: {},
      },
      assistant_message: {
        id: 'msg_assistant_1',
        thread_id: 'thread_demo123',
        role: 'assistant',
        content: 'Added one markdown cell and one code cell from BR assistant.',
        timestamp: '2026-03-28T00:00:02Z',
        metadata: {},
      },
      plan: {
        assistant_message: 'Added one markdown cell and one code cell from BR assistant.',
        source: 'agent_typed',
        ops: [
          {
            type: 'append',
            cell_type: 'markdown',
            source: '## Research goal\n\nMap the task objective.',
            after_cell_id: 'cell_start',
          },
          {
            type: 'append',
            cell_type: 'code',
            source: 'print("hello")',
            after_cell_id: null,
          },
        ],
      },
      notebook: {
        id: 'nb_studio_demo123',
        project_id: 'proj_studio_demo',
        session_id: 'studio_demo123',
        path: 'projects/proj_studio_demo/notebooks/studio/studio_demo123.ipynb',
        title: 'Studio notebook',
        kernel_name: 'python3',
        format: 'ipynb',
        metadata: {
          source: 'brain_researcher.studio',
          surface: 'assistant_first',
        },
        created_at: '2026-03-28T00:00:00Z',
        updated_at: '2026-03-28T00:00:02Z',
        last_saved_at: '2026-03-28T00:00:02Z',
        revision: 2,
        cells: [
          {
            id: 'cell_welcome',
            cell_type: 'markdown',
            source:
              '# Notebook draft\n\nAsk the assistant to generate the first cells, or start editing this notebook directly.',
            metadata: {},
            outputs: [],
            execution_count: null,
            status: 'idle',
          },
          {
            id: 'cell_start',
            cell_type: 'code',
            source:
              "# Placeholder cell\n# Ask the assistant for a concrete notebook scaffold,\n# for example: 'Generate a notebook to visualize T1 images.'",
            metadata: {},
            outputs: [],
            execution_count: null,
            status: 'idle',
          },
          {
            id: 'cell_goal',
            cell_type: 'markdown',
            source: '## Research goal\n\nMap the task objective.',
            metadata: {},
            outputs: [],
            execution_count: null,
            status: 'idle',
          },
          {
            id: 'cell_code',
            cell_type: 'code',
            source: 'print(\"hello\")',
            metadata: {},
            outputs: [],
            execution_count: null,
            status: 'idle',
          },
        ],
      },
    })
  })

  it('creates a Studio session, sends the assistant turn, and renders returned notebook cells', async () => {
    render(<StudioNotebookShell />)

    expect(screen.getAllByRole('button', { name: 'Run' })).toHaveLength(1)

    const promptInput = screen.getByPlaceholderText(
      'Describe the notebook you want, for example: generate a notebook to visualize T1 images.',
    )

    fireEvent.change(promptInput, {
      target: {
        value: '请创建一个 markdown cell 写研究目标，再加一个 python cell 打印 hello',
      },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(createOrAttachStudioSessionMock).toHaveBeenCalledTimes(1),
    )
    await waitFor(() =>
      expect(submitStudioAssistantTurnMock).toHaveBeenCalledTimes(1),
    )
    await waitFor(() =>
      expect(
        screen.getByText(
          'Added one markdown cell and one code cell from BR assistant.',
        ),
      ).toBeInTheDocument(),
    )

    expect(screen.getAllByRole('button', { name: 'Run' })).toHaveLength(2)
    expect(screen.getByText(/Research goal/)).toBeInTheDocument()
    expect(screen.getByText('print("hello")')).toBeInTheDocument()
  })

  it('shows a pending assistant message while the notebook turn is in flight', async () => {
    let resolveTurn: ((value: any) => void) | null = null
    submitStudioAssistantTurnMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTurn = resolve
        }),
    )

    render(<StudioNotebookShell />)

    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() =>
      expect(getStudioAssistantStateMock).toHaveBeenCalledTimes(1),
    )

    const promptInput = screen.getByPlaceholderText(
      'Describe the notebook you want, for example: generate a notebook to visualize T1 images.',
    )
    fireEvent.change(promptInput, {
      target: {
        value: 'Generate a notebook for visualizing T1 images.',
      },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(screen.getByText('Drafting notebook cells...')).toBeInTheDocument(),
    )
    expect(
      screen.getAllByText('Generate a notebook for visualizing T1 images.').length,
    ).toBeGreaterThan(0)

    resolveTurn?.({
      assistant_session_id: 'ast_demo123',
      thread: {
        thread_id: 'thread_demo123',
        title: 'Studio Session assistant',
        created_at: '2026-03-28T00:00:00Z',
        updated_at: '2026-03-28T00:00:02Z',
        message_count: 3,
        context: {},
        metadata: {},
      },
      messages: [
        {
          id: 'msg_bootstrap',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content:
            'Tell me what notebook you want to generate. I can draft cells, revise existing cells, and explain the next analysis step.',
          timestamp: '2026-03-28T00:00:00Z',
          metadata: {},
        },
        {
          id: 'msg_user_t1',
          thread_id: 'thread_demo123',
          role: 'user',
          content: 'Generate a notebook for visualizing T1 images.',
          timestamp: '2026-03-28T00:00:01Z',
          metadata: {},
        },
        {
          id: 'msg_assistant_t1',
          thread_id: 'thread_demo123',
          role: 'assistant',
          content: 'Drafted a T1 visualization notebook scaffold.',
          timestamp: '2026-03-28T00:00:02Z',
          metadata: {},
        },
      ],
      user_message: {
        id: 'msg_user_t1',
        thread_id: 'thread_demo123',
        role: 'user',
        content: 'Generate a notebook for visualizing T1 images.',
        timestamp: '2026-03-28T00:00:01Z',
        metadata: {},
      },
      assistant_message: {
        id: 'msg_assistant_t1',
        thread_id: 'thread_demo123',
        role: 'assistant',
        content: 'Drafted a T1 visualization notebook scaffold.',
        timestamp: '2026-03-28T00:00:02Z',
        metadata: {},
      },
      plan: {
        assistant_message: 'Drafted a T1 visualization notebook scaffold.',
        source: 'heuristic_fallback',
        ops: [
          {
            type: 'append',
            cell_type: 'markdown',
            source: '## T1 visualization notebook',
            after_cell_id: 'cell_start',
          },
        ],
      },
      notebook: {
        id: 'nb_studio_demo123',
        project_id: 'proj_studio_demo',
        session_id: 'studio_demo123',
        path: 'projects/proj_studio_demo/notebooks/studio/studio_demo123.ipynb',
        title: 'Studio notebook',
        kernel_name: 'python3',
        format: 'ipynb',
        metadata: {
          source: 'brain_researcher.studio',
          surface: 'assistant_first',
        },
        created_at: '2026-03-28T00:00:00Z',
        updated_at: '2026-03-28T00:00:02Z',
        last_saved_at: '2026-03-28T00:00:02Z',
        revision: 2,
        cells: [
          {
            id: 'cell_welcome',
            cell_type: 'markdown',
            source: '# Notebook draft',
            metadata: {},
            outputs: [],
            execution_count: null,
            status: 'idle',
          },
        ],
      },
    })

    await waitFor(() =>
      expect(
        screen.getByText('Drafted a T1 visualization notebook scaffold.'),
      ).toBeInTheDocument(),
    )
  })
})
