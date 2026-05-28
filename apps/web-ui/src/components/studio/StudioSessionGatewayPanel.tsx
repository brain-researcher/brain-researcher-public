'use client'

import * as React from 'react'
import Link from 'next/link'
import { ExternalLink, RotateCcw, Sparkles } from 'lucide-react'

import {
  buildWorkspaceHandoff,
  createOrAttachStudioSession,
  type StudioRuntimeProfile,
  type StudioSession,
  type WorkspaceHandoff,
} from '@/lib/api/studio-sessions'
import {
  cancelStudioExecution,
  createStudioExecution,
  getStudioExecution,
  type StudioExecution,
} from '@/lib/api/studio-executions'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

const DEFAULT_PROJECT_ID = 'proj_studio_demo'
const DEFAULT_DISPLAY_NAME = 'Studio Session'

const runtimeProfiles: Array<{ value: StudioRuntimeProfile; label: string }> = [
  { value: 'standard', label: 'Standard' },
  { value: 'high_mem', label: 'High memory' },
  { value: 'gpu', label: 'GPU' },
]

const pollingStatuses = new Set<StudioExecution['status']>(['accepted', 'running'])

export function StudioSessionGatewayPanel() {
  const [projectId, setProjectId] = React.useState(DEFAULT_PROJECT_ID)
  const [displayName, setDisplayName] = React.useState(DEFAULT_DISPLAY_NAME)
  const [runtimeProfileId, setRuntimeProfileId] =
    React.useState<StudioRuntimeProfile>('standard')
  const [targetPath, setTargetPath] = React.useState('scripts/demo.py')
  const [executionCode, setExecutionCode] = React.useState("print('hello from studio')")
  const [session, setSession] = React.useState<StudioSession | null>(null)
  const [handoff, setHandoff] = React.useState<WorkspaceHandoff | null>(null)
  const [execution, setExecution] = React.useState<StudioExecution | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [handoffLoading, setHandoffLoading] = React.useState(false)
  const [executionLoading, setExecutionLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const canBuildHandoff = Boolean(session?.id)

  const handleCreateOrAttach = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextSession = await createOrAttachStudioSession({
        project_id: projectId.trim(),
        display_name: displayName.trim(),
        runtime_profile_id: runtimeProfileId,
        attach_if_exists: true,
        metadata: {
          source: 'studio',
        },
      })
      setSession(nextSession)
      setHandoff(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create Studio session')
    } finally {
      setLoading(false)
    }
  }, [displayName, projectId, runtimeProfileId])

  const handleBuildHandoff = React.useCallback(async () => {
    if (!session?.id) return
    setHandoffLoading(true)
    setError(null)
    try {
      const nextHandoff = await buildWorkspaceHandoff(session.id, {
        target_path: targetPath.trim() || null,
        initial_focus: 'editor',
        materialize_notebook_if_needed: false,
        open_clean_workspace: false,
      })
      setHandoff(nextHandoff)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to launch workspace')
    } finally {
      setHandoffLoading(false)
    }
  }, [session?.id, targetPath])

  const handleReset = React.useCallback(() => {
    setSession(null)
    setHandoff(null)
    setExecution(null)
    setError(null)
  }, [])

  const handleCreateExecution = React.useCallback(async () => {
    if (!session?.id) return
    setExecutionLoading(true)
    setError(null)
    try {
      const nextExecution = await createStudioExecution(session.id, {
        kind: 'code',
        language: 'python',
        code: executionCode,
        runtime_backend: 'jupyter_kernel',
        runtime_profile_id: runtimeProfileId,
        working_directory: 'notebooks',
        timeout_seconds: 60,
        dry_run: false,
        metadata: {
          source: 'studio',
        },
      })
      setExecution(nextExecution)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create Studio execution')
    } finally {
      setExecutionLoading(false)
    }
  }, [executionCode, runtimeProfileId, session?.id])

  const handleCancelExecution = React.useCallback(async () => {
    if (!session?.id || !execution?.id) return
    setExecutionLoading(true)
    setError(null)
    try {
      const canceled = await cancelStudioExecution(session.id, execution.id, {
        reason: 'user_stopped',
      })
      setExecution(canceled)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel Studio execution')
    } finally {
      setExecutionLoading(false)
    }
  }, [execution?.id, session?.id])

  React.useEffect(() => {
    if (!session?.id || !execution?.id || !pollingStatuses.has(execution.status)) {
      return
    }

    let cancelled = false

    const refreshExecution = async () => {
      try {
        const latestExecution = await getStudioExecution(session.id, execution.id)
        if (!cancelled) {
          setExecution(latestExecution)
        }
      } catch {
        // Keep the last known execution state; polling is best-effort.
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

  return (
    <section className="mx-auto w-full max-w-6xl px-6 pb-16 md:px-10">
      <Card className="border-slate-200/80 bg-white/90 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.45)]">
        <CardHeader className="space-y-3">
          <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            <Sparkles className="h-4 w-4" />
            Studio session gateway
          </div>
          <CardTitle className="text-2xl text-slate-950">Create or attach a Studio session</CardTitle>
          <CardDescription className="max-w-3xl text-slate-700">
            This is the minimal hosted path: Brain Researcher owns the session record,
            JupyterHub owns execution, and the UI gets a workspace launch payload it can
            launch or reuse.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6">
          <div className="grid gap-4 lg:grid-cols-3">
            <label className="space-y-2">
              <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                Project ID
              </span>
              <Input
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                placeholder="proj_studio_demo"
              />
            </label>
            <label className="space-y-2">
              <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                Session name
              </span>
              <Input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Studio Session"
              />
            </label>
            <label className="space-y-2">
              <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                Runtime profile
              </span>
              <Select
                value={runtimeProfileId}
                onValueChange={(value) => setRuntimeProfileId(value as StudioRuntimeProfile)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a runtime profile" />
                </SelectTrigger>
                <SelectContent>
                  {runtimeProfiles.map((profile) => (
                    <SelectItem key={profile.value} value={profile.value}>
                      {profile.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button type="button" onClick={handleCreateOrAttach} disabled={loading}>
              {loading ? 'Creating…' : 'Create / attach session'}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleBuildHandoff}
              disabled={!canBuildHandoff || handoffLoading}
            >
              {handoffLoading ? 'Launching…' : 'Launch Workspace'}
            </Button>
            {handoff?.workspace_url ? (
              <Button type="button" variant="ghost" asChild>
                <Link href={handoff.workspace_url} target="_blank" rel="noreferrer">
                  <ExternalLink className="mr-2 h-4 w-4" />
                  Open Workspace
                </Link>
              </Button>
            ) : null}
            <Button type="button" variant="ghost" onClick={handleReset}>
              <RotateCcw className="mr-2 h-4 w-4" />
              Reset panel
            </Button>
          </div>

          <label className="space-y-2 block">
            <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
              Target path for workspace
            </span>
            <Input
              value={targetPath}
              onChange={(event) => setTargetPath(event.target.value)}
              placeholder="scripts/demo.py"
            />
          </label>

          {error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="border-slate-200/80 bg-slate-50/80">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Session record</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {session ? (
                  <>
                    <div className="grid grid-cols-[140px_1fr] gap-2">
                      <span className="text-slate-500">Session ID</span>
                      <span className="font-mono text-slate-950">{session.id}</span>
                      <span className="text-slate-500">Runtime</span>
                      <span>{session.runtime_profile_id}</span>
                      <span className="text-slate-500">Runtime session</span>
                      <span className="font-mono text-slate-950">{session.runtime_session_id}</span>
                      <span className="text-slate-500">Status</span>
                      <span>{session.status}</span>
                      <span className="text-slate-500">Assistant</span>
                      <span className="font-mono text-slate-950">{session.assistant_session_id}</span>
                    </div>
                    <p className="text-slate-600">
                      The session record lives in the orchestrator and can be reused when
                      you return to the same project.
                    </p>
                  </>
                ) : (
                  <p className="text-slate-600">
                    Create or attach a session to see runtime attachment metadata here.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="border-slate-200/80 bg-slate-50/80">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Workspace launch</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {handoff ? (
                  <>
                    <div className="grid grid-cols-[140px_1fr] gap-2">
                      <span className="text-slate-500">Launch mode</span>
                      <span>{handoff.launch_mode}</span>
                      <span className="text-slate-500">Workspace URL</span>
                      <span className="break-all font-mono text-slate-950">
                        {handoff.workspace_url}
                      </span>
                      <span className="text-slate-500">Target path</span>
                      <span>{handoff.target_path || 'None'}</span>
                    </div>
                    <pre className="overflow-auto rounded-xl bg-slate-950 px-3 py-3 text-xs leading-5 text-slate-100">
{JSON.stringify(handoff, null, 2)}
                    </pre>
                  </>
                ) : (
                  <p className="text-slate-600">
                    Launch the workspace to inspect the exact payload Brain Researcher
                    will pass into the workspace flow.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card className="border-slate-200/80 bg-slate-50/80">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Execution run</CardTitle>
              <CardDescription>
                Submit Python into the bound Jupyter kernel and watch the shared runtime update.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
                  Python code
                </span>
                <Textarea
                  value={executionCode}
                  onChange={(event) => setExecutionCode(event.target.value)}
                  rows={6}
                  placeholder="print('hello from studio')"
                />
              </label>

              <div className="flex flex-wrap gap-3">
                <Button
                  type="button"
                  onClick={handleCreateExecution}
                  disabled={!session?.id || executionLoading}
                >
                  {executionLoading ? 'Submitting…' : 'Run execution'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleCancelExecution}
                  disabled={!session?.id || !execution?.id || executionLoading}
                >
                  Cancel execution
                </Button>
              </div>

              {execution ? (
                <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
                  <div className="grid grid-cols-[140px_1fr] gap-2 text-sm">
                    <span className="text-slate-500">Execution ID</span>
                    <span className="font-mono text-slate-950">{execution.id}</span>
                    <span className="text-slate-500">Kind</span>
                    <span>{execution.kind}</span>
                    <span className="text-slate-500">Runtime session</span>
                    <span className="font-mono text-slate-950">{execution.runtime_session_id}</span>
                    <span className="text-slate-500">Backend</span>
                    <span>{execution.runtime_backend}</span>
                    <span className="text-slate-500">Status</span>
                    <span>{execution.status}</span>
                  </div>
                  <pre className="overflow-auto rounded-xl bg-slate-950 px-3 py-3 text-xs leading-5 text-slate-100">
{JSON.stringify(execution, null, 2)}
                  </pre>
                </div>
              ) : (
                <p className="text-sm text-slate-600">
                  Create a Studio session first, then submit an execution request.
                </p>
              )}
            </CardContent>
          </Card>
        </CardContent>
      </Card>
    </section>
  )
}
