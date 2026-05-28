'use client'

import * as React from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { loader } from '@monaco-editor/react'
import {
  Bot,
  Circle,
  ExternalLink,
  FolderOpen,
  Play,
  Sparkles,
  Square,
  TerminalSquare,
} from 'lucide-react'

import {
  buildWorkspaceHandoff,
  createOrAttachStudioSession,
  type StudioRuntimeProfile,
  type StudioSession,
  type StudioSessionStatus,
  type WorkspaceHandoff,
} from '@/lib/api/studio-sessions'
import {
  cancelStudioExecution,
  createStudioExecution,
  getStudioExecution,
  type StudioExecution,
  type StudioExecutionBackend,
} from '@/lib/api/studio-executions'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false })
const MONACO_VS_PATH = '/monaco/vs'

loader.config({
  paths: {
    vs: MONACO_VS_PATH,
  },
})

const DEFAULT_PROJECT_ID = 'proj_studio_demo'
const DEFAULT_DISPLAY_NAME = 'Studio Session'
const DEFAULT_HANDOFF_PATH = 'notebooks/studio/session.py'

const runtimeProfiles: Array<{ value: StudioRuntimeProfile; label: string }> = [
  { value: 'standard', label: 'Standard' },
  { value: 'high_mem', label: 'High memory' },
  { value: 'gpu', label: 'GPU' },
]

const runtimeBackends: Array<{
  value: StudioExecutionBackend
  label: string
  description: string
}> = [
  {
    value: 'jupyter_kernel',
    label: 'Python kernel',
    description: 'Stateful Python in the bound Jupyter runtime.',
  },
  {
    value: 'neurodesk_module',
    label: 'Neurodesk module',
    description: 'Shell code with Lmod initialized on the shared backend.',
  },
  {
    value: 'container',
    label: 'Container shell',
    description: 'General shell execution on the orchestrator backend.',
  },
]

const pollingStatuses = new Set<StudioExecution['status']>(['accepted', 'running'])

const defaultCodeByBackend: Record<StudioExecutionBackend, string> = {
  stub: "print('dry run')",
  jupyter_kernel: [
    'from pathlib import Path',
    '',
    "root = Path.cwd()",
    "print('Studio kernel ready')",
    "print(f'cwd={root}')",
  ].join('\n'),
  neurodesk_module: [
    'python - <<\'PY\'',
    "print('Neurodesk module lane ready')",
    'PY',
  ].join('\n'),
  container: ['pwd', 'python -c "print(\'container lane ready\')"'].join('\n'),
}

type AssistantBubbleTone = 'neutral' | 'success' | 'warning' | 'error'

type AssistantBubble = {
  id: string
  title: string
  body: string
  tone: AssistantBubbleTone
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return 'Not yet'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString()
}

function statusAccent(status: StudioSessionStatus | StudioExecution['status'] | null | undefined) {
  switch (status) {
    case 'ready':
    case 'succeeded':
      return 'bg-emerald-500'
    case 'busy':
    case 'running':
      return 'bg-amber-500'
    case 'accepted':
    case 'idle':
      return 'bg-sky-500'
    case 'failed':
    case 'canceled':
    case 'degraded':
      return 'bg-rose-500'
    default:
      return 'bg-slate-300'
  }
}

export function StudioWorkbenchPage() {
  const [projectId, setProjectId] = React.useState(DEFAULT_PROJECT_ID)
  const [displayName, setDisplayName] = React.useState(DEFAULT_DISPLAY_NAME)
  const [runtimeProfileId, setRuntimeProfileId] =
    React.useState<StudioRuntimeProfile>('standard')
  const [runtimeBackend, setRuntimeBackend] =
    React.useState<StudioExecutionBackend>('jupyter_kernel')
  const [workingDirectory, setWorkingDirectory] = React.useState('notebooks')
  const [handoffTargetPath, setHandoffTargetPath] = React.useState(DEFAULT_HANDOFF_PATH)
  const [code, setCode] = React.useState(defaultCodeByBackend.jupyter_kernel)
  const [session, setSession] = React.useState<StudioSession | null>(null)
  const [execution, setExecution] = React.useState<StudioExecution | null>(null)
  const [handoff, setHandoff] = React.useState<WorkspaceHandoff | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [connecting, setConnecting] = React.useState(false)
  const [running, setRunning] = React.useState(false)
  const [handoffLoading, setHandoffLoading] = React.useState(false)

  const monacoLanguage = runtimeBackend === 'jupyter_kernel' ? 'python' : 'shell'
  const backendLabel =
    runtimeBackends.find((option) => option.value === runtimeBackend)?.label ?? runtimeBackend

  const ensureSession = React.useCallback(async () => {
    if (session?.id) {
      return session
    }
    const nextSession = await createOrAttachStudioSession({
      project_id: projectId.trim(),
      display_name: displayName.trim(),
      runtime_profile_id: runtimeProfileId,
      attach_if_exists: true,
      metadata: {
        source: 'studio_workbench',
      },
    })
    React.startTransition(() => {
      setSession(nextSession)
      setHandoff(null)
    })
    return nextSession
  }, [displayName, projectId, runtimeProfileId, session])

  const handleConnect = React.useCallback(async () => {
    setConnecting(true)
    setError(null)
    try {
      await ensureSession()
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to create Studio session')
    } finally {
      setConnecting(false)
    }
  }, [ensureSession])

  const handleRun = React.useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      const activeSession = await ensureSession()
      const nextExecution = await createStudioExecution(activeSession.id, {
        kind: 'code',
        language: runtimeBackend === 'jupyter_kernel' ? 'python' : 'bash',
        code,
        runtime_backend: runtimeBackend,
        runtime_profile_id: runtimeProfileId,
        working_directory: workingDirectory.trim() || null,
        timeout_seconds: 120,
        dry_run: false,
        metadata: {
          source: 'studio_workbench',
        },
      })
      React.startTransition(() => {
        setExecution(nextExecution)
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to run Studio execution')
    } finally {
      setRunning(false)
    }
  }, [code, ensureSession, runtimeBackend, runtimeProfileId, workingDirectory])

  const handleCancel = React.useCallback(async () => {
    if (!session?.id || !execution?.id) {
      return
    }
    setRunning(true)
    setError(null)
    try {
      const nextExecution = await cancelStudioExecution(session.id, execution.id, {
        reason: 'user_stopped',
      })
      React.startTransition(() => {
        setExecution(nextExecution)
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to cancel execution')
    } finally {
      setRunning(false)
    }
  }, [execution?.id, session?.id])

  const handleBuildHandoff = React.useCallback(async () => {
    if (!session?.id) {
      return
    }
    setHandoffLoading(true)
    setError(null)
    try {
      const nextHandoff = await buildWorkspaceHandoff(session.id, {
        target_path: handoffTargetPath.trim() || null,
        initial_focus: 'editor',
        materialize_notebook_if_needed: false,
        open_clean_workspace: false,
      })
      React.startTransition(() => {
        setHandoff(nextHandoff)
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Failed to launch workspace')
    } finally {
      setHandoffLoading(false)
    }
  }, [handoffTargetPath, session?.id])

  React.useEffect(() => {
    if (!session?.id || !execution?.id || !pollingStatuses.has(execution.status)) {
      return
    }

    let cancelled = false
    const refreshExecution = async () => {
      try {
        const latest = await getStudioExecution(session.id, execution.id)
        if (!cancelled) {
          React.startTransition(() => {
            setExecution(latest)
          })
        }
      } catch {
        // Best-effort polling only.
      }
    }

    void refreshExecution()
    const intervalId = window.setInterval(() => {
      void refreshExecution()
    }, 2000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [execution?.id, execution?.status, session?.id])

  const assistantBubbles: AssistantBubble[] = []

  if (!session) {
    assistantBubbles.push({
      id: 'connect',
      title: 'Attach a runtime first',
      body:
        'Create or attach a Studio session to bind this page to a runtime_session and assistant_session. Everything else builds on that attachment.',
      tone: 'neutral',
    })
  } else {
    assistantBubbles.push({
      id: 'session',
      title: `Session bound to ${session.runtime_profile_id}`,
      body: `Runtime session ${session.runtime_session_id} is ${session.status}. Use Python kernel for stateful code or switch to Neurodesk module when you want module-loaded shell execution.`,
      tone: session.status === 'degraded' ? 'warning' : 'success',
    })
  }

  assistantBubbles.push({
    id: 'backend',
    title: `${backendLabel} selected`,
    body:
      runtimeBackends.find((option) => option.value === runtimeBackend)?.description ??
      'No backend description available.',
    tone: runtimeBackend === 'neurodesk_module' ? 'warning' : 'neutral',
  })

  if (execution?.result?.summary) {
    assistantBubbles.push({
      id: 'execution',
      title: `Execution ${execution.status}`,
      body: execution.result.summary,
      tone:
        execution.status === 'failed'
          ? 'error'
          : execution.status === 'succeeded'
            ? 'success'
            : 'neutral',
    })
  }

  if (handoff?.workspace_url) {
    assistantBubbles.push({
      id: 'handoff',
      title: 'Workspace ready',
      body: `Open the notebook workspace in JupyterLab at ${handoff.workspace_url}`,
      tone: 'success',
    })
  }

  if (error) {
    assistantBubbles.push({
      id: 'error',
      title: 'Request failed',
      body: error,
      tone: 'error',
    })
  }

  const latestStdout = execution?.result?.stdout?.trim() || ''
  const latestStderr = execution?.result?.stderr?.trim() || ''

  return (
    <section className="min-h-[calc(100vh-4rem)] bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.12),_transparent_30%),linear-gradient(180deg,_#f8fbff_0%,_#eef4ff_45%,_#f8fafc_100%)]">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 px-4 pb-10 pt-6 md:px-6">
        <Card className="border-slate-200/80 bg-white/85 shadow-[0_24px_90px_-50px_rgba(15,23,42,0.35)] backdrop-blur">
          <CardContent className="flex flex-col gap-5 p-6 md:flex-row md:items-end md:justify-between">
            <div className="space-y-3">
              <Badge variant="outline" className="border-sky-200 bg-sky-50 text-sky-700">
                Hosted Studio Surface
              </Badge>
              <div className="space-y-2">
                <h1 className="max-w-4xl text-3xl font-semibold tracking-tight text-slate-950 md:text-5xl">
                  Monaco in the center, runtime-aware assistant on the right.
                </h1>
                <p className="max-w-3xl text-sm leading-7 text-slate-600 md:text-base">
                  This surface stays lighter than JupyterLab while still binding to the same
                  Studio session and execution gateway. Use it for fast iteration, then launch
                  into the full Workspace when you need the notebook-native shell.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" asChild>
                <Link href="/workspace">
                  Workspace launcher
                </Link>
              </Button>
              <Button
                variant="outline"
                onClick={handleBuildHandoff}
                disabled={!session?.id || handoffLoading}
              >
                <FolderOpen className="mr-2 h-4 w-4" />
                {handoffLoading ? 'Launching Workspace...' : 'Launch Workspace'}
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.7fr)_420px]">
          <div className="space-y-6">
            <Card className="border-slate-200/80 bg-white/90 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.28)]">
              <CardHeader className="gap-4 border-b border-slate-100 pb-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <CardTitle className="text-xl text-slate-950">Studio workbench</CardTitle>
                    <CardDescription className="mt-2 max-w-2xl text-slate-600">
                      The editor drives the same session and execution gateway you already wired.
                      Python uses the bound Jupyter runtime. Neurodesk module and shell lanes stay
                      on the existing orchestrator backend.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
                      <Circle className={cn('h-2.5 w-2.5 fill-current', statusAccent(session?.status))} />
                      {session ? `Session ${session.status}` : 'No session yet'}
                    </div>
                    <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
                      <TerminalSquare className="h-3.5 w-3.5" />
                      {backendLabel}
                    </div>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <label className="space-y-2 xl:col-span-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Project ID
                    </span>
                    <Input value={projectId} onChange={(event) => setProjectId(event.target.value)} />
                  </label>
                  <label className="space-y-2 xl:col-span-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Session name
                    </span>
                    <Input
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                    />
                  </label>
                  <label className="space-y-2 xl:col-span-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Runtime profile
                    </span>
                    <Select
                      value={runtimeProfileId}
                      onValueChange={(value) => setRuntimeProfileId(value as StudioRuntimeProfile)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {runtimeProfiles.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="space-y-2 xl:col-span-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Backend
                    </span>
                    <Select
                      value={runtimeBackend}
                      onValueChange={(value) => {
                        const nextBackend = value as StudioExecutionBackend
                        setRuntimeBackend(nextBackend)
                        setCode((current) => {
                          if (
                            current === defaultCodeByBackend.jupyter_kernel ||
                            current === defaultCodeByBackend.neurodesk_module ||
                            current === defaultCodeByBackend.container
                          ) {
                            return defaultCodeByBackend[nextBackend]
                          }
                          return current
                        })
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {runtimeBackends.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="space-y-2 xl:col-span-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Working directory
                    </span>
                    <Input
                      value={workingDirectory}
                      onChange={(event) => setWorkingDirectory(event.target.value)}
                    />
                  </label>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button onClick={handleConnect} variant="outline" disabled={connecting}>
                    {connecting ? 'Attaching...' : 'Create / attach session'}
                  </Button>
                  <Button onClick={handleRun} disabled={running || !code.trim()}>
                    <Play className="mr-2 h-4 w-4" />
                    {running ? 'Submitting...' : 'Run code'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleCancel}
                    disabled={!execution?.id || !pollingStatuses.has(execution.status)}
                  >
                    <Square className="mr-2 h-4 w-4" />
                    Cancel
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 p-0">
                <div className="border-b border-slate-100 px-5 py-3 text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                  Editor
                </div>
                <div className="px-2 pb-2">
                  <div className="overflow-hidden rounded-2xl border border-slate-200 bg-[#fbfcff] shadow-inner">
                    <MonacoEditor
                      height="560px"
                      language={monacoLanguage}
                      theme="vs-light"
                      value={code}
                      onChange={(value) => setCode(value ?? '')}
                      loading={
                        <div className="flex h-[560px] items-center justify-center bg-slate-50 text-sm text-slate-500">
                          Loading editor...
                        </div>
                      }
                      options={{
                        automaticLayout: true,
                        minimap: { enabled: false },
                        fontSize: 14,
                        lineHeight: 22,
                        padding: { top: 18 },
                        scrollBeyondLastLine: false,
                        wordWrap: 'on',
                      }}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-slate-200/80 bg-white/90 shadow-[0_24px_80px_-50px_rgba(15,23,42,0.24)]">
              <CardHeader>
                <CardTitle className="text-lg text-slate-950">Execution output</CardTitle>
                <CardDescription>
                  Live status from the Studio execution gateway. Python goes through the Jupyter
                  session model; Neurodesk module and container lanes stay on the orchestrator
                  backend.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-sm text-emerald-200">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300/70">
                    stdout
                  </div>
                  <pre className="min-h-[180px] whitespace-pre-wrap break-words font-mono text-[13px] leading-6">
                    {latestStdout || 'No stdout yet.'}
                  </pre>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-sm text-rose-200">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-rose-300/70">
                    stderr / summary
                  </div>
                  <pre className="min-h-[180px] whitespace-pre-wrap break-words font-mono text-[13px] leading-6">
                    {latestStderr || execution?.result?.summary || 'No stderr yet.'}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card className="sticky top-20 border-slate-200/80 bg-white/92 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.32)]">
              <CardHeader className="border-b border-slate-100">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      <Bot className="h-4 w-4" />
                      Studio assistant
                    </div>
                    <CardTitle className="text-xl text-slate-950">Gateway-aware control panel</CardTitle>
                  </div>
                  <Badge variant="outline" className="border-slate-200 bg-slate-50 text-slate-700">
                    Session + execution
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-5 p-0">
                <ScrollArea className="h-[420px] px-5 py-5">
                  <div className="space-y-4">
                    {assistantBubbles.map((bubble) => (
                      <div
                        key={bubble.id}
                        className={cn(
                          'rounded-2xl border px-4 py-4 shadow-sm',
                          bubble.tone === 'success' &&
                            'border-emerald-200 bg-emerald-50/80 text-emerald-950',
                          bubble.tone === 'warning' &&
                            'border-amber-200 bg-amber-50/85 text-amber-950',
                          bubble.tone === 'error' &&
                            'border-rose-200 bg-rose-50/90 text-rose-950',
                          bubble.tone === 'neutral' &&
                            'border-slate-200 bg-slate-50/90 text-slate-900',
                        )}
                      >
                        <div className="flex items-start gap-3">
                          <div
                            className={cn(
                              'mt-1 h-2.5 w-2.5 rounded-full',
                              bubble.tone === 'success' && 'bg-emerald-500',
                              bubble.tone === 'warning' && 'bg-amber-500',
                              bubble.tone === 'error' && 'bg-rose-500',
                              bubble.tone === 'neutral' && 'bg-sky-500',
                            )}
                          />
                          <div className="space-y-1">
                            <p className="text-sm font-semibold">{bubble.title}</p>
                            <p className="text-sm leading-6 opacity-90">{bubble.body}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
                <Separator />
                <div className="space-y-4 px-5 pb-5">
                  <label className="space-y-2">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Workspace target path
                    </span>
                    <Input
                      value={handoffTargetPath}
                      onChange={(event) => setHandoffTargetPath(event.target.value)}
                    />
                  </label>

                  <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-700">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900">Session status</span>
                      <span className="rounded-full bg-white px-2 py-1 text-xs">
                        {session?.status ?? 'none'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900">Runtime session</span>
                      <span className="truncate text-xs">{session?.runtime_session_id ?? 'n/a'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900">Last execution</span>
                      <span className="rounded-full bg-white px-2 py-1 text-xs">
                        {execution?.status ?? 'none'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900">Updated</span>
                      <span className="text-xs">{formatTimestamp(execution?.updated_at ?? session?.updated_at)}</span>
                    </div>
                  </div>

                  {handoff?.workspace_url ? (
                    <Button asChild className="w-full">
                      <Link href={handoff.workspace_url} target="_blank" rel="noreferrer">
                        <ExternalLink className="mr-2 h-4 w-4" />
                        Launch notebook workspace
                      </Link>
                    </Button>
                  ) : (
                    <Button
                      className="w-full"
                      variant="outline"
                      onClick={handleBuildHandoff}
                      disabled={!session?.id || handoffLoading}
                    >
                      <Sparkles className="mr-2 h-4 w-4" />
                      {handoffLoading ? 'Launching Workspace...' : 'Launch Workspace'}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </section>
  )
}
