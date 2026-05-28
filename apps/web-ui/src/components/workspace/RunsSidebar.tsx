'use client'

import * as React from 'react'
import { formatDistanceToNow } from 'date-fns'
import { AlertCircle, Hand, PlusSquare, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import {
  appendHubSessionCell,
  AppendHubSessionCellError,
  type AppendHubSessionCellErrorCode,
} from '@/lib/api/hub-sessions'
import {
  countActiveRuns,
  fetchSidebarRuns,
  filterRunsForTab,
  type RunSidebarItem,
  type RunSidebarStatus,
  type RunSidebarTab,
} from '@/lib/api/runs'
import {
  HandoffModal,
  type HandoffRunHandlePayload,
} from '@/components/handoff/HandoffModal'

const POLL_INTERVAL_MS = 15_000
const ATTACH_RETRY_DELAYS_MS = [250, 500, 1000]

const STATUS_PILL_STYLE: Record<RunSidebarStatus, string> = {
  pending: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  queued: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
  retrying: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
  cancelling:
    'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  paused: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  completed:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  timeout: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
  cancelled:
    'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
  skipped:
    'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
  unknown: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
}

const ATTACH_ERROR_TOAST: Record<
  AppendHubSessionCellErrorCode,
  { title: string; description: string }
> = {
  'marimo-runtime-not-ready': {
    title: 'Notebook runtime not ready',
    description: 'Open the notebook and wait for it to be ready, then try again.',
  },
  'marimo-session-not-found': {
    title: 'Notebook session not found',
    description:
      'The Studio session has expired. Refresh the page to reconnect to the notebook.',
  },
  'marimo-auth-failed': {
    title: 'Notebook authentication failed',
    description:
      'The orchestrator could not authenticate against the notebook runtime. Please reload.',
  },
  'marimo-upstream-rejected': {
    title: 'Notebook rejected the cell',
    description: 'Marimo could not apply the new cell. Check the runtime logs.',
  },
  'network-error': {
    title: 'Network error',
    description: 'The request did not reach the orchestrator. Try again in a moment.',
  },
  'unknown-error': {
    title: 'Failed to attach run',
    description: 'An unexpected error occurred while sending the cell to the notebook.',
  },
}

function formatTimestamp(value: string | null): string {
  if (!value) return ''
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return ''
  try {
    return formatDistanceToNow(new Date(ms), { addSuffix: true })
  } catch {
    return ''
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export interface RunsSidebarProps {
  brSessionId: string | null
  runtimeReady: boolean
}

export function RunsSidebar({ brSessionId, runtimeReady }: RunsSidebarProps) {
  const { toast } = useToast()
  const [open, setOpen] = React.useState(false)
  const [tab, setTab] = React.useState<RunSidebarTab>('all')
  const [runs, setRuns] = React.useState<RunSidebarItem[]>([])
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [attachingId, setAttachingId] = React.useState<string | null>(null)
  const [handoffPayload, setHandoffPayload] =
    React.useState<HandoffRunHandlePayload | null>(null)

  const load = React.useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const next = await fetchSidebarRuns({ signal })
      setRuns(next)
      setError(null)
    } catch (err) {
      if ((err as Error)?.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Failed to load runs')
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    const intervalId = window.setInterval(() => {
      void load()
    }, POLL_INTERVAL_MS)
    return () => {
      controller.abort()
      window.clearInterval(intervalId)
    }
  }, [load])

  const activeCount = React.useMemo(() => countActiveRuns(runs), [runs])
  const filtered = React.useMemo(
    () => filterRunsForTab(runs, tab),
    [runs, tab],
  )

  const handleAttachInNotebook = React.useCallback(
    async (run: RunSidebarItem) => {
      if (!brSessionId) return
      const code = `import brain_researcher.sdk as br\nrun_${run.run_id.replace(/[^A-Za-z0-9]/g, '_')} = br.attach_run('${run.run_id.replace(/'/g, "\\'")}')`
      setAttachingId(run.run_id)
      let lastError: AppendHubSessionCellError | null = null
      for (let attempt = 0; attempt <= ATTACH_RETRY_DELAYS_MS.length; attempt++) {
        try {
          await appendHubSessionCell(brSessionId, code)
          toast({
            title: `Attached run ${run.run_id.slice(0, 12)} to notebook`,
            description:
              'A new cell calling `br.attach_run(...)` was added at the end of the notebook.',
          })
          lastError = null
          break
        } catch (err) {
          if (!(err instanceof AppendHubSessionCellError)) {
            lastError = new AppendHubSessionCellError(
              'unknown-error',
              0,
              err instanceof Error ? err.message : String(err),
            )
            break
          }
          lastError = err
          if (err.status === 503 && attempt < ATTACH_RETRY_DELAYS_MS.length) {
            await sleep(ATTACH_RETRY_DELAYS_MS[attempt])
            continue
          }
          break
        }
      }
      setAttachingId(null)
      if (lastError) {
        const tone = ATTACH_ERROR_TOAST[lastError.code] ?? ATTACH_ERROR_TOAST['unknown-error']
        toast({
          title: tone.title,
          description:
            lastError.reason && lastError.reason.length > 0
              ? `${tone.description} (${lastError.reason})`
              : tone.description,
          variant: 'destructive',
        })
      }
    },
    [brSessionId, toast],
  )

  return (
    <TooltipProvider delayDuration={150}>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="runs-sidebar-trigger"
          >
            Runs
            <Badge
              variant="secondary"
              className="ml-2 px-1.5 py-0 text-xs font-semibold"
              data-testid="runs-sidebar-count"
            >
              {runs.length}
            </Badge>
            {activeCount > 0 ? (
              <span
                className="ml-1 inline-flex h-2 w-2 rounded-full bg-blue-500"
                aria-label={`${activeCount} active`}
              />
            ) : null}
          </Button>
        </SheetTrigger>
        <SheetContent
          side="right"
          className="flex w-[420px] flex-col gap-3 p-4 sm:max-w-[420px]"
        >
          <SheetHeader className="flex flex-row items-center justify-between space-y-0">
            <SheetTitle className="text-base font-semibold">Runs</SheetTitle>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => void load()}
              aria-label="Refresh runs"
              disabled={loading}
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </SheetHeader>

          <Tabs value={tab} onValueChange={(v) => setTab(v as RunSidebarTab)}>
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="active">Active</TabsTrigger>
              <TabsTrigger value="recent">Recent</TabsTrigger>
              <TabsTrigger value="failed">Failed</TabsTrigger>
            </TabsList>
            <TabsContent value={tab} className="mt-3">
              {error ? (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              ) : null}
              {!error && !loading && filtered.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  No runs in this view.
                </div>
              ) : null}
              <ul
                className="flex flex-col gap-2"
                data-testid="runs-sidebar-list"
              >
                {filtered.map((run) => {
                  const updated = formatTimestamp(run.updated_at)
                  const attachDisabled =
                    !runtimeReady || !brSessionId || attachingId === run.run_id
                  const attachButton = (
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => void handleAttachInNotebook(run)}
                      disabled={attachDisabled}
                      data-testid={`runs-sidebar-attach-${run.run_id}`}
                    >
                      <PlusSquare className="mr-1.5 h-3.5 w-3.5" />
                      {attachingId === run.run_id
                        ? 'Attaching…'
                        : 'Attach in notebook'}
                    </Button>
                  )
                  return (
                    <li
                      key={run.run_id}
                      className="rounded-md border border-slate-200 bg-white p-3 text-sm shadow-sm dark:border-slate-800 dark:bg-slate-900"
                      data-testid={`runs-sidebar-row-${run.run_id}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate font-medium">
                              {run.workflow_id || `Run ${run.run_id.slice(0, 8)}`}
                            </span>
                            <Badge
                              className={`px-2 py-0 text-[10px] font-semibold uppercase tracking-wide ${STATUS_PILL_STYLE[run.status]}`}
                            >
                              {run.status}
                            </Badge>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                            {run.dataset_id ? (
                              <span className="truncate">
                                Dataset: {run.dataset_id}
                              </span>
                            ) : null}
                            <Badge
                              variant="outline"
                              className="px-1.5 py-0 text-[10px]"
                              data-testid={`runs-sidebar-source-${run.run_id}`}
                            >
                              {run.source === 'internal'
                                ? 'Studio'
                                : run.source === 'external'
                                  ? 'External agent'
                                  : 'Unknown'}
                            </Badge>
                            {updated ? <span>· {updated}</span> : null}
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {attachDisabled && !brSessionId ? (
                          attachButton
                        ) : !runtimeReady ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span>{attachButton}</span>
                            </TooltipTrigger>
                            <TooltipContent>
                              Open notebook first to attach runs
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          attachButton
                        )}
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setHandoffPayload({
                              kind: 'run-handle',
                              runId: run.run_id,
                              workflowId: run.workflow_id,
                              workflowLabel: run.workflow_id,
                              datasetId: run.dataset_id,
                            })
                          }
                          data-testid={`runs-sidebar-handoff-${run.run_id}`}
                        >
                          <Hand className="mr-1.5 h-3.5 w-3.5" />
                          Hand off
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </TabsContent>
          </Tabs>
        </SheetContent>
      </Sheet>
      {handoffPayload ? (
        <HandoffModal
          open={Boolean(handoffPayload)}
          onClose={() => setHandoffPayload(null)}
          mode="run-handle"
          payload={handoffPayload}
        />
      ) : null}
    </TooltipProvider>
  )
}
