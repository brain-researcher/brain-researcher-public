'use client'

import * as React from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  buildWorkspaceHandoff,
  createOrAttachStudioSession,
  type StudioRuntimeProfile,
  type StudioSession,
  type WorkspaceHandoff,
} from '@/lib/api/studio-sessions'
import {
  executeStudioNotebookCell,
  openOrCreateStudioNotebook,
  saveStudioNotebook,
  type StudioNotebookCellType,
  type StudioNotebookDocument,
  type StudioNotebookMode,
} from '@/lib/api/studio-notebook'
import {
  getStudioAssistantState,
  submitStudioAssistantTurn,
  type StudioAssistantTurnResponse,
  type StudioAssistantMessage as BackendStudioAssistantMessage,
} from '@/lib/api/studio-assistant'
import { cn } from '@/lib/utils'
import {
  applyNotebookOperation,
  buildStarterNotebook,
  markNotebookSaved,
  normalizeStudioNotebookDocument,
} from './notebook/studio-notebook-state'
import { StudioAssistantPane, type StudioAssistantMessage } from './assistant/StudioAssistantPane'
import { StudioNotebookPanel } from './notebook/StudioNotebookPanel'

const DEFAULT_PROJECT_ID = 'proj_studio_demo'
const DEFAULT_DISPLAY_NAME = 'Studio Session'

function nowIso() {
  return new Date().toISOString()
}

function messageId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`
}

function assistantTitleForRole(role: BackendStudioAssistantMessage['role']) {
  if (role === 'assistant') return 'Assistant'
  if (role === 'system') return 'System'
  return 'You'
}

function toPaneMessages(
  messages: BackendStudioAssistantMessage[],
): StudioAssistantMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    title: assistantTitleForRole(message.role),
    content: message.content,
  }))
}

function notebookTitleForSession(session: StudioSession | null) {
  if (!session) {
    return 'Studio notebook'
  }
  return `${session.display_name} notebook`
}

function buildLocalAssistantMessages(session: StudioSession | null): StudioAssistantMessage[] {
  return [
    {
      id: 'msg_system',
      role: 'system',
      title: 'Notebook flow',
      content:
        'Draft in Studio, then launch the full notebook workspace in JupyterLab when you are ready to run and iterate.',
    },
    {
      id: 'msg_assistant_intro',
      role: 'assistant',
      title: 'Assistant',
      content: session
        ? 'Session attached. Ask for notebook cells, revisions, or the next analysis step.'
        : 'Start with a request like “Generate a notebook to visualize T1 images.”',
    },
  ]
}

function buildFallbackNotebook(
  projectId: string,
  session: StudioSession | null,
): StudioNotebookDocument {
  return buildStarterNotebook(projectId, session?.id ?? null)
}

type PlannerSignal = {
  label: string
  detail: string
}

const FALLBACK_PLANNER_DETAIL = 'Heuristic notebook draft used for this turn.'
const FALLBACK_REASON_DETAILS: Record<string, string> = {
  agent_error: 'Agent planner was unavailable, so Studio used a heuristic draft.',
  agent_no_plan: 'Agent planner returned no typed plan, so Studio used a heuristic draft.',
  fast_path: FALLBACK_PLANNER_DETAIL,
}

function readStringField(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return trimmed || null
}

function isFallbackPlannerValue(value: unknown): boolean {
  const normalized = readStringField(value)?.toLowerCase()
  if (!normalized) {
    return false
  }
  return (
    normalized === 'heuristic_fallback' ||
    normalized === 'fallback' ||
    normalized === 'degraded' ||
    normalized.includes('fallback')
  )
}

function plannerSignalFromTurnResponse(
  response: StudioAssistantTurnResponse | null | undefined,
): PlannerSignal | null {
  if (!response) {
    return null
  }
  const plannerValue =
    response.planner_status ??
    response.planner_source ??
    response.plan.planner_status ??
    response.plan.planner_source ??
    response.plan.source
  if (!isFallbackPlannerValue(plannerValue)) {
    return null
  }
  const fallbackReason = readStringField(response.fallback_reason)
    ?? readStringField(response.plan.fallback_reason)
  const plannerErrorMessage = readStringField(response.plan.planner_error?.message)
  return {
    label: 'Planner fallback',
    detail:
      plannerErrorMessage ??
      (fallbackReason ? FALLBACK_REASON_DETAILS[fallbackReason] ?? fallbackReason : null) ??
      FALLBACK_PLANNER_DETAIL,
  }
}

function plannerSignalFromMessages(
  messages: BackendStudioAssistantMessage[],
): PlannerSignal | null {
  const lastAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant')
  if (!lastAssistantMessage) {
    return null
  }
  const plannerValue = readStringField(lastAssistantMessage.metadata?.['planner_status'])
    ?? readStringField(lastAssistantMessage.metadata?.['planner_source'])
  if (!isFallbackPlannerValue(plannerValue)) {
    return null
  }
  const fallbackReason = readStringField(lastAssistantMessage.metadata?.['planner_fallback_reason'])
    ?? readStringField(lastAssistantMessage.metadata?.['fallback_reason'])
  return {
    label: 'Planner fallback',
    detail: (fallbackReason
      ? FALLBACK_REASON_DETAILS[fallbackReason] ?? fallbackReason
      : null) ?? FALLBACK_PLANNER_DETAIL,
  }
}

export function StudioNotebookShell() {
  const [projectId, setProjectId] = React.useState(DEFAULT_PROJECT_ID)
  const [displayName, setDisplayName] = React.useState(DEFAULT_DISPLAY_NAME)
  const [runtimeProfileId, setRuntimeProfileId] =
    React.useState<StudioRuntimeProfile>('standard')
  const [session, setSession] = React.useState<StudioSession | null>(null)
  const [workspaceHandoff, setWorkspaceHandoff] = React.useState<WorkspaceHandoff | null>(null)
  const [notebook, setNotebook] = React.useState<StudioNotebookDocument>(() =>
    buildFallbackNotebook(DEFAULT_PROJECT_ID, null),
  )
  const [notebookMode, setNotebookMode] = React.useState<StudioNotebookMode>('preview')
  const [assistantMessages, setAssistantMessages] = React.useState<StudioAssistantMessage[]>(() =>
    buildLocalAssistantMessages(null),
  )
  const [assistantPrompt, setAssistantPrompt] = React.useState('')
  const [plannerSignal, setPlannerSignal] = React.useState<PlannerSignal | null>(null)
  const [loadingSession, setLoadingSession] = React.useState(false)
  const [loadingNotebook, setLoadingNotebook] = React.useState(false)
  const [loadingAssistant, setLoadingAssistant] = React.useState(false)
  const [submittingAssistantTurn, setSubmittingAssistantTurn] = React.useState(false)
  const [savingNotebook, setSavingNotebook] = React.useState(false)
  const [runningCellId, setRunningCellId] = React.useState<string | null>(null)
  const [launchingWorkspace, setLaunchingWorkspace] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [notebookConnected, setNotebookConnected] = React.useState(false)
  const [notebookDirty, setNotebookDirty] = React.useState(false)

  const createSession = React.useCallback(async (): Promise<StudioSession> => {
    setLoadingSession(true)
    setError(null)
    try {
      const nextSession = await createOrAttachStudioSession({
        project_id: projectId.trim(),
        display_name: displayName.trim(),
        runtime_profile_id: runtimeProfileId,
        attach_if_exists: true,
        metadata: {
          source: 'studio_shell',
        },
      })
      setSession(nextSession)
      setWorkspaceHandoff(null)
      setAssistantMessages(buildLocalAssistantMessages(nextSession))
      setPlannerSignal(null)
      return nextSession
    } finally {
      setLoadingSession(false)
    }
  }, [displayName, projectId, runtimeProfileId])

  const syncNotebookFromRemote = React.useCallback(
    (payload: unknown, fallbackProjectId = projectId, fallbackSessionId = session?.id ?? null) => {
      const nextNotebook = normalizeStudioNotebookDocument(payload, {
        projectId: fallbackProjectId,
        sessionId: fallbackSessionId,
      })
      setNotebook(nextNotebook)
      setNotebookConnected(true)
      setNotebookDirty(false)
      setError(null)
    },
    [projectId, session?.id],
  )

  const hydrateAssistantThread = React.useCallback(async (activeSession: StudioSession) => {
    setLoadingAssistant(true)
    try {
      const state = await getStudioAssistantState(activeSession.id)
      setAssistantMessages(toPaneMessages(state.messages))
      setPlannerSignal(plannerSignalFromMessages(state.messages))
      setError(null)
    } catch (nextError) {
      setAssistantMessages(buildLocalAssistantMessages(activeSession))
      setPlannerSignal(null)
      setError(
        nextError instanceof Error
          ? nextError.message
          : 'Failed to load Studio assistant thread',
      )
    } finally {
      setLoadingAssistant(false)
    }
  }, [])

  const refreshLocalDraft = React.useCallback(() => {
    setNotebook(buildFallbackNotebook(projectId, session))
    setNotebookConnected(false)
    setNotebookDirty(false)
    setPlannerSignal(null)
  }, [projectId, session])

  const openOrCreateNotebook = React.useCallback(
    async (activeSession: StudioSession) => {
      setLoadingNotebook(true)
      try {
        const remoteNotebook = await openOrCreateStudioNotebook(activeSession.id, {
          notebook_path: `projects/${activeSession.project_id}/notebooks/studio/${activeSession.id}.ipynb`,
          title: notebookTitleForSession(activeSession),
          kernel_name: 'python3',
          metadata: {
            source: 'studio_shell',
          },
        })
        syncNotebookFromRemote(remoteNotebook, activeSession.project_id, activeSession.id)
      } catch (nextError) {
        refreshLocalDraft()
        setAssistantMessages((current) => [
          ...current,
          {
            id: messageId('msg_system'),
            role: 'system',
            title: 'Notebook backend unavailable',
            content:
              nextError instanceof Error
                ? nextError.message
                : 'Using a local draft until the notebook backend is available.',
          },
        ])
      } finally {
        setLoadingNotebook(false)
      }
    },
    [refreshLocalDraft, syncNotebookFromRemote],
  )

  const handleConnectSession = React.useCallback(async () => {
    try {
      const nextSession = await createSession()
      await openOrCreateNotebook(nextSession)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to create Studio session')
    }
  }, [createSession, openOrCreateNotebook])

  const handleOpenNotebook = React.useCallback(async () => {
    setError(null)
    try {
      const activeSession = session ?? (await createSession())
      await openOrCreateNotebook(activeSession)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to open notebook')
    }
  }, [createSession, openOrCreateNotebook, session])

  const ensureWorkspaceHandoff = React.useCallback(
    async (activeSession: StudioSession): Promise<WorkspaceHandoff> => {
      if (workspaceHandoff?.workspace_url) {
        return workspaceHandoff
      }
      const nextHandoff = await buildWorkspaceHandoff(activeSession.id, {
        notebook_path: notebook.path,
        target_path: notebook.path,
        initial_focus: 'notebook',
        materialize_notebook_if_needed: true,
        open_clean_workspace: false,
      })
      setWorkspaceHandoff(nextHandoff)
      return nextHandoff
    },
    [notebook.path, workspaceHandoff],
  )

  const handleLaunchWorkspace = React.useCallback(async () => {
    setLaunchingWorkspace(true)
    setError(null)
    try {
      const activeSession = session ?? (await createSession())
      const nextHandoff = await ensureWorkspaceHandoff(activeSession)
      window.open(nextHandoff.workspace_url, '_blank', 'noopener,noreferrer')
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : 'Failed to launch workspace',
      )
    } finally {
      setLaunchingWorkspace(false)
    }
  }, [createSession, ensureWorkspaceHandoff, session])

  React.useEffect(() => {
    setWorkspaceHandoff((current) => {
      if (!current) {
        return current
      }
      const currentNotebookPath = notebook.path?.trim()
      const handoffNotebookPath = current.notebook_path?.trim() ?? current.target_path?.trim()
      if (currentNotebookPath && handoffNotebookPath && currentNotebookPath !== handoffNotebookPath) {
        return null
      }
      return current
    })
  }, [notebook.path])

  const handleSaveNotebook = React.useCallback(async () => {
    setSavingNotebook(true)
    setError(null)
    try {
      if (session) {
        const saved = await saveStudioNotebook(session.id, notebook)
        syncNotebookFromRemote(saved, session.project_id, session.id)
      } else {
        const savedAt = nowIso()
        setNotebook((current) => markNotebookSaved(current, savedAt))
        setNotebookDirty(false)
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to save notebook')
    } finally {
      setSavingNotebook(false)
    }
  }, [notebook, session, syncNotebookFromRemote])

  const handleAppendCell = React.useCallback(
    (cellType: StudioNotebookCellType) => {
      setNotebook((current) =>
        applyNotebookOperation(current, {
          type: 'append',
          cell_type: cellType,
          source:
            cellType === 'markdown'
              ? '## New note\n\nDescribe the next step.'
              : "print('new cell')",
        }),
      )
      setNotebookDirty(true)
    },
    [],
  )

  const handleUpdateCellSource = React.useCallback((cellId: string, source: string) => {
    setNotebook((current) =>
      applyNotebookOperation(current, {
        type: 'edit',
        cell_id: cellId,
        source,
      }),
    )
    setNotebookDirty(true)
  }, [])

  const handleDeleteCell = React.useCallback((cellId: string) => {
    setNotebook((current) =>
      applyNotebookOperation(current, {
        type: 'delete_cell',
        cell_id: cellId,
      }),
    )
    setNotebookDirty(true)
  }, [])

  const handleMoveCell = React.useCallback((cellId: string, direction: -1 | 1) => {
    setNotebook((current) => {
      const currentIndex = current.cells.findIndex((cell) => cell.id === cellId)
      if (currentIndex < 0) {
        return current
      }
      const targetIndex = currentIndex + direction
      return applyNotebookOperation(current, {
        type: 'move_cell',
        cell_id: cellId,
        target_index: targetIndex,
      })
    })
    setNotebookDirty(true)
  }, [])

  const handleRunCell = React.useCallback(
    async (cellId: string) => {
      const targetCell = notebook.cells.find((cell) => cell.id === cellId)
      if (!targetCell || targetCell.cell_type !== 'code') {
        return
      }
      setRunningCellId(cellId)
      setError(null)
      setNotebook((current) =>
        applyNotebookOperation(current, {
          type: 'apply_outputs',
          cell_id: cellId,
          status: 'running',
          outputs: targetCell.outputs,
          execution_count: targetCell.execution_count,
        }),
      )
      try {
        if (session) {
          const response = await executeStudioNotebookCell(session.id, {
            cell_id: cellId,
            notebook_path: notebook.path,
            runtime_profile_id: runtimeProfileId,
            working_directory: notebook.path.replace(/\/[^/]+$/, ''),
            timeout_seconds: 120,
            metadata: {
              source: 'studio_shell',
            },
          })
          if (response && typeof response === 'object' && 'notebook' in response) {
            const maybeNotebook = (response as { notebook?: unknown }).notebook
            if (maybeNotebook) {
              syncNotebookFromRemote(maybeNotebook, session.project_id, session.id)
              return
            }
          }
        }
        setNotebook((current) =>
          applyNotebookOperation(current, {
            type: 'apply_outputs',
            cell_id: cellId,
            status: 'finished',
            execution_count:
              typeof targetCell.execution_count === 'number'
                ? targetCell.execution_count + 1
                : 1,
            outputs: [
              {
                output_type: 'stream',
                name: 'stdout',
                text: `Executed locally at ${new Date().toLocaleTimeString()}\n`,
              },
            ],
          }),
        )
      } catch (nextError) {
        setNotebook((current) =>
          applyNotebookOperation(current, {
            type: 'apply_outputs',
            cell_id: cellId,
            status: 'error',
            outputs: [
              {
                output_type: 'error',
                ename: nextError instanceof Error ? nextError.name : 'ExecutionError',
                evalue:
                  nextError instanceof Error
                    ? nextError.message
                    : 'Notebook execution failed.',
                traceback: ['Backend execution is not available yet.'],
              },
            ],
            execution_count: targetCell.execution_count,
          }),
        )
        setError(
          nextError instanceof Error ? nextError.message : 'Failed to execute notebook cell',
        )
      } finally {
        setNotebookDirty(true)
        setRunningCellId(null)
      }
    },
    [notebook.cells, notebook.path, runtimeProfileId, session, syncNotebookFromRemote],
  )

  const handleAssistantPromptSubmit = React.useCallback(async () => {
    const prompt = assistantPrompt.trim()
    if (!prompt) {
      return
    }
    setSubmittingAssistantTurn(true)
    setError(null)
    try {
      const activeSession = session ?? (await createSession())
      const requestNotebook = normalizeStudioNotebookDocument(notebook, {
        projectId: activeSession.project_id,
        sessionId: activeSession.id,
      })
      if (requestNotebook.path !== notebook.path || requestNotebook.session_id !== notebook.session_id) {
        setNotebook(requestNotebook)
      }
      const optimisticUserMessage: StudioAssistantMessage = {
        id: messageId('msg_user'),
        role: 'user',
        title: 'You',
        content: prompt,
      }
      const optimisticAssistantMessage: StudioAssistantMessage = {
        id: messageId('msg_pending'),
        role: 'assistant',
        title: 'Assistant',
        content: 'Drafting notebook cells...',
        pending: true,
      }
      setAssistantMessages((current) => [
        ...current,
        optimisticUserMessage,
        optimisticAssistantMessage,
      ])
      const response = await submitStudioAssistantTurn(activeSession.id, {
        content: prompt,
        notebook: requestNotebook,
      })
      setAssistantMessages(toPaneMessages(response.messages))
      setPlannerSignal(plannerSignalFromTurnResponse(response))
      syncNotebookFromRemote(response.notebook, activeSession.project_id, activeSession.id)
      setNotebookDirty(false)
      setAssistantPrompt('')
      return
    } catch (nextError) {
      setAssistantMessages((current) => {
        if (!current.some((message) => message.pending)) {
          return current
        }
        return current.map((message) =>
          message.pending
            ? {
                ...message,
                role: 'system',
                title: 'Request failed',
                content:
                  nextError instanceof Error
                    ? nextError.message
                    : 'Failed to process Studio assistant turn',
                pending: false,
              }
            : message,
        )
      })
      setError(
        nextError instanceof Error
          ? nextError.message
          : 'Failed to process Studio assistant turn',
      )
    } finally {
      setSubmittingAssistantTurn(false)
    }
  }, [
    assistantPrompt,
    notebook,
    createSession,
    session,
    syncNotebookFromRemote,
  ])

  React.useEffect(() => {
    setNotebook((current) => {
      if (current.project_id === projectId) {
        return current
      }
      return buildFallbackNotebook(projectId, session)
    })
  }, [projectId, session])

  React.useEffect(() => {
    if (session?.id && notebook.session_id !== session.id) {
      setNotebook((current) =>
        normalizeStudioNotebookDocument(current, {
          projectId: session.project_id,
          sessionId: session.id,
        }),
      )
    }
  }, [notebook.session_id, session])

  React.useEffect(() => {
    if (!session?.id) {
      setAssistantMessages(buildLocalAssistantMessages(null))
      return
    }
    void hydrateAssistantThread(session)
  }, [hydrateAssistantThread, session])

  return (
    <div className="min-h-screen bg-slate-100">
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 w-full max-w-[1800px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Brain Researcher Studio
            </div>
          </div>
          <div className="flex items-center gap-2">
            {error ? (
              <div className="max-w-[420px] truncate text-xs text-rose-600">{error}</div>
            ) : null}
            <Button
              onClick={handleLaunchWorkspace}
              size="sm"
              disabled={launchingWorkspace}
            >
              {launchingWorkspace ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <ExternalLink className="mr-2 h-4 w-4" />
              )}
              {launchingWorkspace ? 'Launching Workspace…' : 'Launch Workspace'}
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1800px] px-4 py-4 sm:px-6 lg:px-8">
        <div className="grid gap-3 lg:grid-cols-[minmax(320px,0.67fr)_minmax(0,1fr)]">
          <div className="space-y-2">
            {plannerSignal ? (
              <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-950 shadow-sm">
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn(
                      'border-amber-300 bg-amber-100 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-900',
                    )}
                  >
                    {plannerSignal.label}
                  </Badge>
                  <div className="min-w-0 truncate leading-5">{plannerSignal.detail}</div>
                </div>
              </div>
            ) : null}

            <StudioAssistantPane
              projectId={projectId}
              displayName={displayName}
              runtimeProfileId={runtimeProfileId}
              assistantMessages={assistantMessages}
              assistantPrompt={assistantPrompt}
              session={session}
              loading={loadingSession || loadingNotebook || loadingAssistant}
              connecting={loadingSession}
              launchingWorkspace={launchingWorkspace}
              sending={submittingAssistantTurn}
              notebookReady={notebookConnected}
              onProjectIdChange={setProjectId}
              onDisplayNameChange={setDisplayName}
              onRuntimeProfileChange={setRuntimeProfileId}
              onAssistantPromptChange={setAssistantPrompt}
              onConnectSession={handleConnectSession}
              onSubmitPrompt={handleAssistantPromptSubmit}
              onLaunchWorkspace={handleLaunchWorkspace}
              onOpenNotebook={handleOpenNotebook}
            />
          </div>

          <StudioNotebookPanel
            notebook={notebook}
            mode={notebookMode}
            isConnected={notebookConnected}
            isSaving={savingNotebook || loadingNotebook}
            isDirty={notebookDirty}
            onModeChange={setNotebookMode}
            onSave={handleSaveNotebook}
            onOpenOrCreate={handleOpenNotebook}
            onRunCell={handleRunCell}
            onAppendCell={handleAppendCell}
            onUpdateCellSource={handleUpdateCellSource}
            onDeleteCell={handleDeleteCell}
            onMoveCell={handleMoveCell}
          />
        </div>
      </div>
    </div>
  )
}
