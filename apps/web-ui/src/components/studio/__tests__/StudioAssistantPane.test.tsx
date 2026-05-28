// @vitest-environment jsdom

import type { ComponentProps } from 'react'

import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { StudioAssistantPane, type StudioAssistantMessage } from '../assistant/StudioAssistantPane'

const baseMessages: StudioAssistantMessage[] = [
  {
    id: 'msg_1',
    role: 'assistant',
    title: 'Assistant',
    content: 'Ready to help.',
  },
]

const baseSession = {
  id: 'studio_test123',
  project_id: 'proj_demo',
  owner_user_id: 'user_123',
  display_name: 'Demo Session',
  runtime_profile_id: 'standard' as const,
  runtime_session_id: 'runtime_123',
  assistant_session_id: 'assistant_123',
  status: 'ready' as const,
  metadata: {},
  created_at: '2026-03-30T00:00:00Z',
  updated_at: '2026-03-30T00:00:00Z',
  last_activity_at: '2026-03-30T00:00:00Z',
}

function renderPane(overrides: Partial<ComponentProps<typeof StudioAssistantPane>> = {}) {
  const onLaunchWorkspace = vi.fn()

  render(
    <StudioAssistantPane
      projectId="proj_demo"
      displayName="Demo Session"
      runtimeProfileId="standard"
      assistantMessages={baseMessages}
      assistantPrompt=""
      session={baseSession}
      loading={false}
      connecting={false}
      launchingWorkspace={false}
      sending={false}
      notebookReady={true}
      onProjectIdChange={vi.fn()}
      onDisplayNameChange={vi.fn()}
      onRuntimeProfileChange={vi.fn()}
      onAssistantPromptChange={vi.fn()}
      onConnectSession={vi.fn()}
      onSubmitPrompt={vi.fn()}
      onLaunchWorkspace={onLaunchWorkspace}
      onOpenNotebook={vi.fn()}
      {...overrides}
    />,
  )

  return { onLaunchWorkspace }
}

describe('StudioAssistantPane', () => {
  it('renders the launch workspace CTA and helper copy', () => {
    const { onLaunchWorkspace } = renderPane()

    const button = screen.getByRole('button', { name: /launch workspace/i })
    expect(button).toBeEnabled()
    expect(
      screen.getByText(/full notebook-native experience, launch your workspace in jupyterlab/i),
    ).toBeInTheDocument()

    fireEvent.click(button)
    expect(onLaunchWorkspace).toHaveBeenCalledTimes(1)
  })

  it('shows a launching state while workspace startup is in progress', () => {
    renderPane({ launchingWorkspace: true })

    const button = screen.getByRole('button', { name: /launching/i })
    expect(button).toBeDisabled()
  })
})
