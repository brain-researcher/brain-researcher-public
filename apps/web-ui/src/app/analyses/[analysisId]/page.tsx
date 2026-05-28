'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { AttemptSwitcher } from '@/components/chat/attempt-switcher'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { AnalysisStreamEventsPanel } from '@/components/progress/analysis-stream-events-panel'
import { ShareModal } from '@/components/share/share-modal'
import { useAdvancedMode } from '@/hooks/use-advanced-mode'
import {
  buildCodingAgentHandoffHrefFromAnalysis,
  buildStudioPlanHrefFromAnalysis,
} from '@/lib/analysis-links'
import { extractErrorCode, planForError } from '@/lib/errors'
import type { AnalysisDetail, AnalysisStatus } from '@/types/analysis'

type JobProgress = {
  status?: string
  overall_progress?: number
  current_step?: number
  step_progress?: Array<{ id: string; name: string; status: string; progress?: number }>
  time_estimates?: { elapsed?: number; estimated_remaining?: number }
}

type Milestone = {
  stage?: string
  status?: string
  percent?: number
  step?: { name?: string }
}

type DemoBundleArtifact = {
  name: string
  path: string
  download_url: string
}

type DemoBundle = {
  slug: string
  available: boolean
  generated_at?: string | null
  artifact_count: number
  source_run_ids: string[]
  items: DemoBundleArtifact[]
}

function normalizeStatus(value: unknown): AnalysisStatus {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'claimed') return 'running'
  if (normalized === 'skipped') return 'cancelled'
  if (normalized === 'succeeded') return 'completed'
  const allowed = new Set<AnalysisStatus>([
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled',
    'cancelling',
    'retrying',
    'paused',
    'timeout',
    'unknown',
  ])
  return allowed.has(normalized as AnalysisStatus) ? (normalized as AnalysisStatus) : 'unknown'
}

function toEpochMillis(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    // Heuristic: epoch ms is ~1e12+; epoch seconds is ~1e9.
    return value > 1e11 ? value : value * 1000
  }
  if (typeof value === 'string' && value.trim()) {
    const ms = Date.parse(value)
    return Number.isFinite(ms) ? ms : null
  }
  return null
}

function formatTimestamp(value: unknown): string {
  const ms = toEpochMillis(value)
  if (!ms) return '-'
  return new Date(ms).toLocaleString()
}

function statusColor(status: AnalysisStatus): string {
  switch (status) {
    case 'queued':
    case 'pending':
      return 'bg-gray-100 text-gray-800'
    case 'running':
    case 'retrying':
    case 'cancelling':
      return 'bg-blue-100 text-blue-800'
    case 'completed':
      return 'bg-green-100 text-green-800'
    case 'failed':
    case 'timeout':
      return 'bg-red-100 text-red-800'
    case 'review_blocked':
      return 'bg-amber-100 text-amber-900'
    case 'cancelled':
      return 'bg-yellow-100 text-yellow-800'
    default:
      return 'bg-gray-100 text-gray-600'
  }
}

function shouldContinueViaMcp(status: AnalysisStatus): boolean {
  return status === 'failed' || status === 'timeout' || status === 'cancelled' || status === 'paused'
}

const TERMINAL_ANALYSIS_STATUSES = new Set<AnalysisStatus>([
  'completed',
  'failed',
  'cancelled',
  'timeout',
  'review_blocked',
])

function isTerminalStatus(status: AnalysisStatus): boolean {
  return TERMINAL_ANALYSIS_STATUSES.has(status)
}

function coerceArtifacts(raw: unknown) {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'object') {
    const obj = raw as any
    if (Array.isArray(obj.artifacts)) return obj.artifacts
  }
  return []
}

function coerceMethods(raw: unknown): { text: string; generated: boolean } | null {
  if (!raw) return null
  if (typeof raw === 'string') {
    return raw.trim() ? { text: raw.trim(), generated: false } : null
  }
  if (typeof raw === 'object') {
    const obj = raw as any
    const text = obj?.text
    if (typeof text !== 'string' || !text.trim()) return null
    return { text: text.trim(), generated: Boolean(obj?.generated) }
  }
  return null
}

function stringifyJson(value: unknown): string | null {
  if (!value) return null
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return null
  }
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((entry) => (typeof entry === 'string' ? entry.trim() : ''))
    .filter(Boolean)
}

function stringValue(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function uniqueStringValues(values: unknown[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const text = stringValue(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
  }
  return out
}

function requiredOutputsFromContract(value: unknown): string[] {
  const contract = safeRecord(value)
  if (!contract) return []
  const required = stringList(contract.required_outputs)
  return required.length ? required : stringList(contract.outputs)
}

function artifactTextCandidates(artifact: unknown): string[] {
  if (typeof artifact === 'string') return artifact.trim() ? [artifact.trim()] : []
  const record = safeRecord(artifact)
  if (!record) return []
  return uniqueStringValues([
    record.path,
    record.name,
    record.file_name,
    record.id,
    record.artifact_id,
    record.download_url,
    record.url,
  ])
}

function artifactDisplayInfo(artifact: unknown, index: number) {
  if (typeof artifact === 'string') {
    const text = artifact.trim()
    return {
      id: text || `artifact-${index + 1}`,
      name: text || `Artifact ${index + 1}`,
      kind: 'artifact',
      upstreamUrl: null,
    }
  }

  const record = safeRecord(artifact)
  if (!record) {
    return {
      id: `artifact-${index + 1}`,
      name: `Artifact ${index + 1}`,
      kind: 'artifact',
      upstreamUrl: null,
    }
  }

  const id =
    stringValue(record.id) ||
    stringValue(record.artifact_id) ||
    stringValue(record.path) ||
    stringValue(record.name) ||
    `artifact-${index + 1}`
  const name =
    stringValue(record.name) ||
    stringValue(record.file_name) ||
    stringValue(record.path) ||
    stringValue(record.download_url) ||
    stringValue(record.url) ||
    id

  return {
    id,
    name,
    kind: stringValue(record.type) || stringValue(record.mime_type) || 'artifact',
    upstreamUrl: stringValue(record.download_url) || stringValue(record.url) || null,
  }
}

function compactValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value.trim() || '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`
  if (typeof value === 'object') return `${Object.keys(value as Record<string, unknown>).length} keys`
  return String(value)
}

function formatStage(stage?: string): string {
  const normalized = typeof stage === 'string' ? stage.trim().toLowerCase() : ''
  switch (normalized) {
    case 'data_check':
      return 'Data check'
    case 'preprocess':
      return 'Preprocess'
    case 'model':
      return 'Model'
    case 'stats':
      return 'Stats'
    case 'report':
      return 'Report'
    case 'complete':
      return 'Complete'
    case 'error':
      return 'Error'
    default:
      return '—'
  }
}

type VaultAnalysisDetailPageProps = {
  params?: { analysisId?: string }
  readOnly?: boolean
  shareToken?: string
  readOnlyMode?: 'share' | 'read-only' | 'demo'
  demoId?: string
}

export default function VaultAnalysisDetailPage({
  params,
  readOnly,
  shareToken,
  readOnlyMode,
  demoId,
}: VaultAnalysisDetailPageProps) {
  const analysisId = params?.analysisId ?? ''
  const { enabled: advancedMode } = useAdvancedMode()
  const router = useRouter()
  const searchParams = useSearchParams()
  const readOnlyFromQuery = (() => {
    const mode = searchParams.get('mode') || ''
    const flag = searchParams.get('readonly') || searchParams.get('readOnly') || ''
    return mode.toLowerCase() === 'share' || flag === '1' || flag.toLowerCase() === 'true'
  })()
  const shareTokenValue = typeof shareToken === 'string' && shareToken.trim() ? shareToken.trim() : null
  const isReadOnly = Boolean(readOnly) || readOnlyFromQuery || Boolean(shareTokenValue)
  const viewMode: 'share' | 'demo' | 'read-only' | null = shareTokenValue
    ? 'share'
    : readOnlyMode === 'demo'
      ? 'demo'
      : isReadOnly
        ? 'read-only'
        : null
  const dataEndpoint = shareTokenValue
    ? `/api/share/${encodeURIComponent(shareTokenValue)}`
    : `/api/analyses/${encodeURIComponent(analysisId)}`
  const streamEndpoint = shareTokenValue
    ? null
    : `/api/analyses/${encodeURIComponent(analysisId)}/stream`

  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null)
  const [jobProgress, setJobProgress] = useState<JobProgress | null>(null)
  const [milestone, setMilestone] = useState<Milestone | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorAction, setErrorAction] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [shareModalOpen, setShareModalOpen] = useState(false)
  const [demoBundle, setDemoBundle] = useState<DemoBundle | null>(null)
  const [demoBundleError, setDemoBundleError] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const load = async (signal?: AbortSignal) => {
    const res = await fetch(dataEndpoint, {
      cache: 'no-store',
      credentials: 'same-origin',
      signal,
    })
    if (!res.ok) {
      let body: any = null
      try {
        body = await res.clone().json()
      } catch {
        // ignore
      }
      const code = extractErrorCode(body)
      const plan = planForError(code)
      const detail = (body && (body.detail || body.error)) || res.statusText || 'Failed to load run'
      setError(detail)
      setErrorAction(plan.fallbackAction || null)
      setAnalysis(null)
      return
    }
    const data = await res.json()
    if (!safeRecord(data)) {
      setAnalysis(null)
      setError('Run not found')
      setErrorAction(null)
      return
    }
    setAnalysis(data as AnalysisDetail)
    setError(null)
    setErrorAction(null)
  }

  useEffect(() => {
    if (!shareTokenValue && !analysisId) return
    const controller = new AbortController()
    setLoading(true)
    setJobProgress(null)
    setMilestone(null)
    load(controller.signal)
      .catch((err: any) => {
        if (err.name !== 'AbortError') {
          setError(err.message || 'Failed to load run')
        }
      })
      .finally(() => setLoading(false))

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, dataEndpoint, shareTokenValue])

  useEffect(() => {
    if (viewMode !== 'demo' || !demoId) {
      setDemoBundle(null)
      setDemoBundleError(null)
      return
    }
    const controller = new AbortController()
    fetch(`/api/demo/bundles/${encodeURIComponent(demoId)}`, {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Failed to load demo bundle (${res.status})`)
        }
        const data = (await res.json()) as DemoBundle
        setDemoBundle(data)
        setDemoBundleError(null)
      })
      .catch((err: any) => {
        if (err.name === 'AbortError') return
        setDemoBundle(null)
        setDemoBundleError(err.message || 'Failed to load demo bundle')
      })
    return () => controller.abort()
  }, [viewMode, demoId])

  const persistedStatus = normalizeStatus(analysis?.status)
  const liveStatus = normalizeStatus(jobProgress?.status)
  const status = isTerminalStatus(persistedStatus)
    ? persistedStatus
    : liveStatus !== 'unknown'
      ? liveStatus
      : persistedStatus
  const progressPct = (() => {
    const p = jobProgress?.overall_progress
    if (typeof p === 'number' && Number.isFinite(p)) {
      return Math.max(0, Math.min(100, p))
    }
    return status === 'completed' ? 100 : status === 'running' ? 50 : 0
  })()

  const isLiveStatus =
    status === 'running' ||
    status === 'queued' ||
    status === 'pending' ||
    status === 'retrying' ||
    status === 'cancelling'

  const showStreamEvents =
    (viewMode === 'demo' || (!isReadOnly && advancedMode)) &&
    (isLiveStatus || viewMode === 'demo')

  useEffect(() => {
    if (!shareTokenValue && !analysisId) return
    if (!streamEndpoint) return
    if (!isLiveStatus && viewMode !== 'demo') {
      return
    }

    setStreaming(true)
    const eventSource = new EventSource(streamEndpoint)
    eventSourceRef.current = eventSource

    const handleProgress = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as JobProgress
        setJobProgress(data)
      } catch {
        // ignore
      }
    }

    const handleComplete = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as JobProgress
        setJobProgress(data)
      } catch {
        // ignore
      }
      eventSource.close()
      setStreaming(false)
      void load()
    }

    const handleMilestone = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as Milestone
        setMilestone(data)
      } catch {
        // ignore
      }
    }

    eventSource.addEventListener('progress_update', handleProgress)
    eventSource.addEventListener('job_complete', handleComplete)
    eventSource.addEventListener('milestone', handleMilestone)
    eventSource.onerror = () => {
      eventSource.close()
      setStreaming(false)
    }

    return () => {
      eventSource.removeEventListener('progress_update', handleProgress)
      eventSource.removeEventListener('job_complete', handleComplete)
      eventSource.removeEventListener('milestone', handleMilestone)
      eventSource.close()
      setStreaming(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId, shareTokenValue, isLiveStatus, viewMode, streamEndpoint])

  const artifacts = useMemo(() => coerceArtifacts(analysis?.artifacts), [analysis?.artifacts])
  const artifactPaths = useMemo(
    () => artifacts.flatMap((artifact: unknown) => artifactTextCandidates(artifact)),
    [artifacts],
  )
  const requiredOutputChecklist = useMemo(() => {
    const required = requiredOutputsFromContract(analysis?.artifact_contract)
    return required.map((output) => ({
      output,
      present: artifactPaths.some((path) => path === output || path.endsWith(`/${output}`)),
    }))
  }, [analysis?.artifact_contract, artifactPaths])
  const methods = useMemo(() => coerceMethods(analysis?.methods), [analysis?.methods])
  const parametersJson = useMemo(() => {
    if (!analysis?.parameters || Object.keys(analysis.parameters).length === 0) return null
    return stringifyJson(analysis.parameters)
  }, [analysis?.parameters])
  const artifactContractJson = useMemo(
    () => stringifyJson(analysis?.artifact_contract),
    [analysis?.artifact_contract],
  )
  const handoffPackJson = useMemo(
    () => stringifyJson(analysis?.handoff_pack),
    [analysis?.handoff_pack],
  )
  const launchTraceJson = useMemo(
    () => stringifyJson(analysis?.launch_trace),
    [analysis?.launch_trace],
  )
  const preflightChecks = Array.isArray(analysis?.preflight?.checks)
    ? analysis.preflight.checks.filter((check) => safeRecord(check) != null)
    : []
  const stepsSummary = Array.isArray(analysis?.steps_summary)
    ? analysis.steps_summary.filter((step) => safeRecord(step) != null)
    : []
  const logsSummary = Array.isArray(analysis?.logs_summary)
    ? analysis.logs_summary.filter((log) => safeRecord(log) != null)
    : []
  const warnings = stringList(analysis?.warnings)
  const currentAnalysisId = stringValue(analysis?.analysis_id) || analysisId
  const analysisTitle =
    stringValue(analysis?.title) ||
    (currentAnalysisId ? `Run ${currentAnalysisId.slice(0, 8)}` : 'Run')
  const shareLevel = useMemo(() => {
    if (viewMode !== 'share') return null
    const raw = String((analysis as any)?.share_level ?? '').trim().toLowerCase()
    return raw === 'full' ? 'full' : 'summary'
  }, [analysis, viewMode])
  const studioPlanHref = useMemo(
    () => (analysis ? buildStudioPlanHrefFromAnalysis(analysis, { readOnly: isReadOnly }) : null),
    [analysis, isReadOnly],
  )
  const codingAgentHref = useMemo(
    () => (analysis ? buildCodingAgentHandoffHrefFromAnalysis(analysis) : null),
    [analysis],
  )
  if (loading) {
    return (
      <NavigationWrapper>
        <div className="flex min-h-screen items-center justify-center bg-gray-50">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </NavigationWrapper>
    )
  }

  if (error || !analysis) {
    return (
      <NavigationWrapper>
        <div className="min-h-screen bg-gray-50">
          <div className="mx-auto max-w-4xl px-4 py-8">
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
              {error || 'Run not found'}
              {errorAction === 'retry' && (
                <div className="mt-3">
                  <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
                    Retry
                  </Button>
                </div>
              )}
              {errorAction === 'login' && (
                <div className="mt-3 text-sm">
                  <Link className="text-primary underline" href="/auth/login">
                    Login to continue
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>
      </NavigationWrapper>
    )
  }

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
          {!isReadOnly ? (
            <ShareModal
              analysisId={currentAnalysisId}
              open={shareModalOpen}
              onOpenChange={setShareModalOpen}
            />
          ) : null}
          {viewMode === 'share' ? (
            <Alert>
              <AlertTitle>Shared Result Package (read-only)</AlertTitle>
              <AlertDescription>
                This link is public to anyone with it.{' '}
                {shareLevel === 'full'
                  ? 'Includes all artifacts (may include logs).'
                  : 'Includes summary, charts, and methods (no raw logs by default).'}{' '}
                To review a plan or start a new run, go to{' '}
                <Link className="text-primary underline" href="/studio">
                  Studio
                </Link>
                .
              </AlertDescription>
            </Alert>
          ) : null}

          {viewMode === 'demo' ? (
            <Alert>
              <AlertTitle>Demo Result Package (read-only)</AlertTitle>
              <AlertDescription>
                This is a public demo result package. Review the evidence here, then open{' '}
                <Link className="text-primary underline" href="/studio">
                  Studio
                </Link>
                {studioPlanHref ? ' to review the plan or hand off a full run.' : '.'}
              </AlertDescription>
            </Alert>
          ) : null}

          {viewMode === 'read-only' ? (
            <Alert>
              <AlertTitle>Read-only view</AlertTitle>
              <AlertDescription>
                You are viewing this result package in read-only mode. To review the plan or create a new run, head to{' '}
                <Link className="text-primary underline" href="/studio">
                  Studio
                </Link>
                .
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <Link
                href={viewMode === 'demo' ? '/demos' : isReadOnly ? '/' : '/analyses'}
                className="text-sm text-muted-foreground hover:text-primary"
              >
                {viewMode === 'demo'
                  ? '← Back to Demos'
                  : isReadOnly
                    ? '← Back to Home'
                    : '← Back to Runs'}
              </Link>
              <h1 className="text-2xl font-semibold tracking-tight">
                {analysisTitle}
              </h1>
              {viewMode === 'demo' ? (
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  <Badge variant="secondary">Demo</Badge>
                  {demoBundle?.available && demoBundle.artifact_count > 0 ? (
                    <span>Evidence files: {demoBundle.artifact_count}</span>
                  ) : null}
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  <Badge className={statusColor(status)}>{status}</Badge>
                  {analysis.dataset?.name ? (
                    <span>Dataset: {analysis.dataset.name}</span>
                  ) : analysis.dataset?.dataset_id ? (
                    <span>Dataset: {analysis.dataset.dataset_id}</span>
                  ) : null}
                  {analysis.template?.template_id ? (
                    <span>Workflow: {analysis.template.template_id}</span>
                  ) : null}
                </div>
              )}
              <div className="text-xs text-muted-foreground">
                Result Package: evidence · diagnostics · reproducibility
              </div>
              {warnings.length ? (
                <div className="text-xs text-amber-700">
                  Diagnostics: {warnings.slice(0, 2).join(' · ')}
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-2">
              {studioPlanHref ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={studioPlanHref}>Review plan in Studio</Link>
                </Button>
              ) : null}
              {codingAgentHref ? (
                <Button size="sm" asChild>
                  <Link href={codingAgentHref}>
                    {shouldContinueViaMcp(status)
                      ? 'Continue via MCP recipe'
                      : 'Run via MCP in Codex/Cursor'}
                  </Link>
                </Button>
              ) : null}
              {!isReadOnly ? (
                <Button variant="outline" size="sm" onClick={() => setShareModalOpen(true)}>
                  Share
                </Button>
              ) : null}
              {!isReadOnly ? (
                <Button variant="outline" size="sm" asChild>
                  <a href={`/api/analyses/${encodeURIComponent(currentAnalysisId)}/export`}>
                    Export ZIP
                  </a>
                </Button>
              ) : null}
              {!isReadOnly && advancedMode ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={`/jobs/${encodeURIComponent(currentAnalysisId)}`}>Advanced job view</Link>
                </Button>
              ) : null}
            </div>
          </div>

          {!isReadOnly && analysis.thread_id ? (
            <div className="rounded-lg border bg-card p-4">
              <AttemptSwitcher
                threadId={analysis.thread_id}
                currentAnalysisId={currentAnalysisId}
                onSelect={(selectedId) => {
                  router.push(`/analyses/${encodeURIComponent(selectedId)}`)
                }}
              />
            </div>
          ) : null}

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">Execution status</div>
              <div className="text-xs text-muted-foreground">
                {streaming ? 'Live' : status === 'running' ? 'Disconnected' : '—'}
              </div>
            </div>
            <Progress value={progressPct} />
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>Stage: {formatStage(milestone?.stage)}</span>
              {milestone?.step?.name ? <span>• {milestone.step.name}</span> : null}
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-sm text-muted-foreground">
              <div>Created: {formatTimestamp(analysis.created_at)}</div>
              <div>Started: {formatTimestamp(analysis.started_at)}</div>
              <div>Finished: {formatTimestamp(analysis.finished_at)}</div>
            </div>
          </div>

          {showStreamEvents ? (
            <div className="rounded-lg border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Diagnostics stream</div>
                <div className="text-xs text-muted-foreground">Typed</div>
              </div>
              <AnalysisStreamEventsPanel analysisId={currentAnalysisId} />
            </div>
          ) : null}

          {viewMode === 'demo' ? (
            <div className="rounded-lg border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Evidence & trace bundle</div>
                <div className="text-xs text-muted-foreground">
                  {demoBundle?.available
                    ? `${demoBundle.artifact_count} artifacts`
                    : 'No bundle'}
                </div>
              </div>
              {demoBundleError ? (
                <div className="text-sm text-amber-700">{demoBundleError}</div>
              ) : null}
              {!demoBundleError && demoBundle?.available ? (
                <>
                  {demoBundle.generated_at ? (
                    <div className="text-xs text-muted-foreground">
                      Bundle generated: {demoBundle.generated_at}
                    </div>
                  ) : null}
                  {demoBundle.source_run_ids?.length ? (
                    <div className="text-xs text-muted-foreground">
                      Source runs: {demoBundle.source_run_ids.join(', ')}
                    </div>
                  ) : null}
                  {demoBundle.items?.length ? (
                    <div className="space-y-2">
                      {demoBundle.items.slice(0, 10).map((item) => (
                        <div
                          key={item.path}
                          className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm"
                        >
                          <div className="min-w-0">
                            <div className="truncate font-medium">{item.name}</div>
                            <div className="truncate text-xs text-muted-foreground">
                              {item.path}
                            </div>
                          </div>
                          <Button size="sm" variant="outline" asChild>
                            <a href={item.download_url} target="_blank" rel="noreferrer">
                              Open
                            </a>
                          </Button>
                        </div>
                      ))}
                      {demoBundle.items.length > 10 ? (
                        <div className="text-xs text-muted-foreground">
                          Showing first 10 of {demoBundle.items.length} artifacts.
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      Bundle is available, but no artifact links were found.
                    </div>
                  )}
                </>
              ) : null}
            </div>
          ) : null}

          {analysis.handoff_pack ||
          analysis.artifact_contract ||
          analysis.preflight ||
          analysis.launch_trace ||
          stepsSummary.length ||
          logsSummary.length ? (
            <div className="rounded-lg border bg-card p-4 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg font-medium">Run trace evidence</h2>
                <span className="text-xs text-muted-foreground">Launch contract</span>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {analysis.preflight ? (
                  <div className="rounded-md border p-3">
                    <div className="text-sm font-medium">Preflight snapshot</div>
                    <div className="mt-2 space-y-1 text-sm text-muted-foreground">
                      <div>Status: {analysis.preflight.status || 'captured'}</div>
                      {analysis.preflight.route ? <div>Route: {analysis.preflight.route}</div> : null}
                      {analysis.preflight.detail ? <div>{analysis.preflight.detail}</div> : null}
                      {preflightChecks.length ? (
                        <div>Checks: {preflightChecks.length}</div>
                      ) : null}
                    </div>
                    {preflightChecks.length ? (
                      <div className="mt-3 space-y-2">
                        {preflightChecks.slice(0, 5).map((check, index) => {
                          const id = compactValue(check.id || check.label || `check-${index + 1}`)
                          const statusText = compactValue(check.status)
                          const detail = compactValue(check.detail)
                          return (
                            <div key={`${id}-${index}`} className="rounded bg-muted/30 p-2 text-xs">
                              <div className="font-medium">{id}</div>
                              <div className="text-muted-foreground">{statusText}</div>
                              {detail !== '—' ? <div className="text-muted-foreground">{detail}</div> : null}
                            </div>
                          )
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {artifactContractJson ? (
                  <div className="rounded-md border p-3">
                    <div className="text-sm font-medium">Artifact contract</div>
                    <pre className="mt-2 max-h-56 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap font-mono">
                      {artifactContractJson}
                    </pre>
                  </div>
                ) : null}
              </div>

              {stepsSummary.length || logsSummary.length ? (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {stepsSummary.length ? (
                    <div className="rounded-md border p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">Steps summary</div>
                        <div className="text-xs text-muted-foreground">{stepsSummary.length} shown</div>
                      </div>
                      <div className="mt-2 divide-y">
                        {stepsSummary.map((step, index) => (
                          <div key={`${step.id || step.name}-${index}`} className="py-2 text-sm">
                            <div className="font-medium">{step.name}</div>
                            <div className="text-xs text-muted-foreground">
                              {[step.status, step.tool].filter(Boolean).join(' · ') || 'step'}
                            </div>
                            {step.detail ? (
                              <div className="mt-1 text-xs text-muted-foreground">{step.detail}</div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {logsSummary.length ? (
                    <div className="rounded-md border p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">Logs & trace files</div>
                        <div className="text-xs text-muted-foreground">{logsSummary.length} shown</div>
                      </div>
                      <div className="mt-2 divide-y">
                        {logsSummary.map((log, index) => {
                          const upstreamUrl = log.url || null
                          const href =
                            typeof upstreamUrl === 'string' && upstreamUrl.trim()
                              ? upstreamUrl.startsWith('/api/analyses/') ||
                                upstreamUrl.startsWith('/api/share/')
                                ? upstreamUrl
                                : shareTokenValue
                                  ? `/api/share/${encodeURIComponent(shareTokenValue)}/artifacts/download?url=${encodeURIComponent(
                                      upstreamUrl,
                                    )}`
                                  : `/api/analyses/${encodeURIComponent(currentAnalysisId)}/artifacts/download?url=${encodeURIComponent(
                                      upstreamUrl,
                                    )}`
                              : null
                          return (
                            <div key={`${log.path || log.name}-${index}`} className="flex items-center justify-between gap-3 py-2 text-sm">
                              <div className="min-w-0">
                                <div className="truncate font-medium">{log.name}</div>
                                <div className="truncate text-xs text-muted-foreground">
                                  {log.path || log.kind || 'log'}
                                </div>
                              </div>
                              {href ? (
                                <a className="text-sm text-primary underline" href={href}>
                                  Open
                                </a>
                              ) : null}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {handoffPackJson || launchTraceJson ? (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {handoffPackJson ? (
                    <div className="rounded-md border p-3">
                      <div className="text-sm font-medium">Handoff pack</div>
                      <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap font-mono">
                        {handoffPackJson}
                      </pre>
                    </div>
                  ) : null}
                  {launchTraceJson ? (
                    <div className="rounded-md border p-3">
                      <div className="text-sm font-medium">Launch trace</div>
                      <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted/30 p-2 text-xs whitespace-pre-wrap font-mono">
                        {launchTraceJson}
                      </pre>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-medium">{methods?.generated ? 'Methods (draft)' : 'Methods'}</h2>
              <span className="text-xs text-muted-foreground">Result Package</span>
            </div>
            {methods?.text ? (
              <pre className="max-h-80 overflow-auto rounded bg-muted/30 p-3 text-sm whitespace-pre-wrap">
                {methods.text}
              </pre>
            ) : (
              <div className="text-sm text-muted-foreground">
                No methods text yet. When available, a draft Methods section will appear here for reproducibility and writing.
              </div>
            )}
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-medium">Execution parameters</h2>
              <span className="text-xs text-muted-foreground">Result Package</span>
            </div>
            {parametersJson ? (
              <pre className="max-h-80 overflow-auto rounded bg-muted/30 p-3 text-xs whitespace-pre-wrap font-mono">
                {parametersJson}
              </pre>
            ) : (
              <div className="text-sm text-muted-foreground">
                No parameters captured yet. When the run is created, the execution parameters will appear here.
              </div>
            )}
          </div>

          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium">Evidence & outputs</h2>
              <span className="text-xs text-muted-foreground">{artifacts.length} items</span>
            </div>
            {requiredOutputChecklist.length ? (
              <div className="mt-3 rounded-md border bg-muted/20 p-3">
                <div className="text-sm font-medium">Required outputs</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {requiredOutputChecklist.map((item) => (
                    <Badge
                      key={item.output}
                      variant={item.present ? 'default' : 'secondary'}
                      className="max-w-full truncate"
                    >
                      {item.present ? 'ready' : 'missing'} · {item.output}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
            {artifacts.length === 0 ? (
              <div className="mt-3 text-sm text-muted-foreground">
                No evidence files yet. When the run completes, figures, tables, and outputs will appear here.
              </div>
            ) : (
              <div className="mt-3 divide-y">
                {artifacts.slice(0, 50).map((artifact: unknown, index) => {
                  const { id, name, upstreamUrl, kind } = artifactDisplayInfo(artifact, index)
                  const downloadUrl =
                    typeof upstreamUrl === 'string' && upstreamUrl.trim()
                      ? upstreamUrl.startsWith('/api/analyses/') ||
                        upstreamUrl.startsWith('/api/share/')
                        ? upstreamUrl
                        : shareTokenValue
                          ? `/api/share/${encodeURIComponent(shareTokenValue)}/artifacts/download?url=${encodeURIComponent(
                              upstreamUrl,
                            )}`
                          : `/api/analyses/${encodeURIComponent(currentAnalysisId)}/artifacts/download?url=${encodeURIComponent(
                              upstreamUrl,
                            )}`
                      : null
                  return (
                    <div key={`${id}-${index}`} className="flex items-center justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <div className="font-medium truncate">{name}</div>
                        <div className="text-xs text-muted-foreground truncate">{kind}</div>
                      </div>
                      {downloadUrl ? (
                        <a className="text-sm text-primary underline" href={downloadUrl}>
                          Download
                        </a>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </NavigationWrapper>
  )
}
