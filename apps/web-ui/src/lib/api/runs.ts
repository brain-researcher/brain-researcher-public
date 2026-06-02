/**
 * Client-side helpers for the Runs sidebar.
 *
 * Wraps the Next.js BFF at /api/runs which proxies to the orchestrator's
 * `/api/runs` (Agent JobService). Adds a tiny request-dedup window so the
 * sidebar's 15s polling cycle does not fire duplicate fetches when multiple
 * subscribers mount at once.
 */

export type RunSidebarStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'retrying'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | 'skipped'
  | 'paused'
  | 'unknown'

export type RunSidebarSource = 'internal' | 'external' | 'unknown'

export interface RunSidebarItem {
  run_id: string
  status: RunSidebarStatus
  source: RunSidebarSource
  project_id: string | null
  workflow_id: string | null
  dataset_id: string | null
  thread_id: string | null
  // Compact human-readable summary of what the run did (from plan.metadata.intent
  // / plan name) plus counts derived from the plan already in the payload.
  intent: string | null
  // Human-readable display facets recovered from the plan payload (the parameters
  // written by the from-dataset flow). All optional; null when the plan lacks them.
  title: string | null
  task: string | null
  dataset_label: string | null
  workflow_label: string | null
  artifact_count: number | null
  step_count: number | null
  // Timestamps may arrive as ISO strings or Unix epoch (seconds/ms) integers.
  created_at: string | number | null
  updated_at: string | number | null
  finished_at: string | number | null
  error_message: string | null
}

// Preserve timestamps that arrive as Unix epoch numbers (stringOrNull would drop
// them); keep finite numbers and non-empty strings, else null.
function timeOrNull(value: unknown): string | number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  return stringOrNull(value)
}

// Normalize an ISO string or Unix epoch (seconds/ms) value to milliseconds for
// sorting; returns 0 when missing/unparseable.
function sortEpochMs(value: string | number | null): number {
  if (value === null) return 0
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 0
    return value < 1e12 ? value * 1000 : value
  }
  const trimmed = value.trim()
  if (!trimmed) return 0
  if (/^\d+$/.test(trimmed)) {
    const n = Number(trimmed)
    return n < 1e12 ? n * 1000 : n
  }
  const parsed = Date.parse(trimmed)
  return Number.isFinite(parsed) ? parsed : 0
}

interface RawRunPayload {
  runs?: unknown
  count?: unknown
}

function normalizeStatus(value: unknown): RunSidebarStatus {
  if (typeof value !== 'string') return 'unknown'
  const v = value.trim().toLowerCase()
  if (v === 'succeeded') return 'completed'
  if (v === 'claimed') return 'running'
  const allowed: RunSidebarStatus[] = [
    'pending',
    'queued',
    'running',
    'retrying',
    'cancelling',
    'completed',
    'failed',
    'cancelled',
    'timeout',
    'skipped',
    'paused',
    'unknown',
  ]
  return (allowed as string[]).includes(v) ? (v as RunSidebarStatus) : 'unknown'
}

// Map the backend `source` literal (preferred) or a raw async-run `origin`
// to a sidebar source. The backend's _to_api_format now emits 'internal' |
// 'external' | 'unknown' directly; the origin cases are defense-in-depth for
// payloads that surface the raw origin instead of the derived source.
// Studio sync runs are internal; agent-submitted async runs are external.
function normalizeSource(value: unknown): RunSidebarSource {
  if (typeof value !== 'string') return 'unknown'
  const v = value.trim().toLowerCase()
  if (v === 'internal') return 'internal'
  if (
    v === 'external' ||
    v === 'mcp_pipeline_execute' ||
    v === 'api_tools_run' ||
    v === 'tools_run_compat' ||
    v === 'direct'
  ) {
    return 'external'
  }
  return 'unknown'
}

function stringOrNull(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function pickRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeRun(raw: unknown): RunSidebarItem | null {
  const record = pickRecord(raw)
  if (!record) return null
  const runId = stringOrNull(record.run_id) || stringOrNull(record.job_id)
  if (!runId) return null
  const plan = (pickRecord(record.plan) || {}) as Record<string, unknown>
  const planMeta = (pickRecord(plan.metadata) || {}) as Record<string, unknown>
  const workflowFromPlan =
    stringOrNull(plan.workflow_id) ||
    stringOrNull(plan.template_id) ||
    stringOrNull(plan.pipeline)
  // dataset is usually under plan.metadata.dataset_id (the top-level plan.dataset_id
  // is typically absent), which is why the drawer showed no dataset before.
  const datasetFromPlan =
    stringOrNull(plan.dataset_id) ||
    stringOrNull(plan.dataset) ||
    stringOrNull(planMeta.dataset_id) ||
    stringOrNull(planMeta.dataset)
  // Human-readable summary of what the run did + counts already in the payload.
  const intentSummary =
    stringOrNull(planMeta.intent) ||
    stringOrNull(plan.plan_summary) ||
    stringOrNull(plan.name) ||
    stringOrNull(record.intent)
  const artifactCount = Array.isArray(plan.artifacts)
    ? plan.artifacts.length
    : null
  const stepCount = Array.isArray(plan.steps) ? plan.steps.length : null
  // Human-readable labels live under plan.parameters (written by the
  // /api/runs/from-dataset flow): dataset_label, dataset_tasks, analysis_label,
  // pipeline_label, task_id. Recover them so rows show meaningful names instead
  // of raw ids. Falls back to plan.metadata / plan.pipeline when absent.
  const params = (pickRecord(plan.parameters) || {}) as Record<string, unknown>
  const datasetLabel =
    stringOrNull(params.dataset_label) || stringOrNull(planMeta.dataset_label)
  const workflowLabel =
    stringOrNull(params.pipeline_label) ||
    stringOrNull(params.analysis_label) ||
    stringOrNull(plan.pipeline) ||
    workflowFromPlan
  const datasetTasks = params.dataset_tasks
  const task =
    stringOrNull(params.task_id) ||
    stringOrNull(params.task) ||
    stringOrNull(params.task_name) ||
    (Array.isArray(datasetTasks) && datasetTasks.length > 0
      ? stringOrNull(datasetTasks[0])
      : null)
  const title = intentSummary || workflowLabel || datasetLabel || null
  return {
    run_id: runId,
    status: normalizeStatus(record.status),
    source: normalizeSource(record.source),
    project_id: stringOrNull(record.project_id),
    workflow_id:
      stringOrNull(record.workflow_id) ||
      stringOrNull(record.pipeline) ||
      workflowFromPlan,
    dataset_id: stringOrNull(record.dataset_id) || datasetFromPlan,
    thread_id: stringOrNull(record.thread_id),
    intent: intentSummary,
    title,
    task,
    dataset_label: datasetLabel,
    workflow_label: workflowLabel,
    artifact_count: artifactCount,
    step_count: stepCount,
    created_at: timeOrNull(record.created_at),
    updated_at:
      timeOrNull(record.updated_at) ??
      timeOrNull(record.finished_at) ??
      timeOrNull(record.started_at) ??
      timeOrNull(record.created_at),
    finished_at: timeOrNull(record.finished_at),
    error_message: stringOrNull(record.error_message),
  }
}

const ACTIVE_STATUSES = new Set<RunSidebarStatus>([
  'pending',
  'queued',
  'running',
  'retrying',
  'cancelling',
  'paused',
])

const FAILED_STATUSES = new Set<RunSidebarStatus>([
  'failed',
  'cancelled',
  'timeout',
])

export type RunSidebarTab = 'all' | 'active' | 'recent' | 'failed'

export function filterRunsForTab(
  runs: RunSidebarItem[],
  tab: RunSidebarTab,
): RunSidebarItem[] {
  switch (tab) {
    case 'active':
      return runs.filter((r) => ACTIVE_STATUSES.has(r.status))
    case 'failed':
      return runs.filter((r) => FAILED_STATUSES.has(r.status))
    case 'recent':
      return runs.filter((r) => !ACTIVE_STATUSES.has(r.status)).slice(0, 25)
    case 'all':
    default:
      return runs
  }
}

export function countActiveRuns(runs: RunSidebarItem[]): number {
  return runs.reduce((n, r) => (ACTIVE_STATUSES.has(r.status) ? n + 1 : n), 0)
}

let _inflight: Promise<RunSidebarItem[]> | null = null
let _inflightExpiresAt = 0
const DEDUP_WINDOW_MS = 1500

export interface FetchRunsOptions {
  signal?: AbortSignal
  limit?: number
}

export async function fetchSidebarRuns(
  options: FetchRunsOptions = {},
): Promise<RunSidebarItem[]> {
  const now = Date.now()
  if (_inflight && now < _inflightExpiresAt) {
    return _inflight
  }
  const limit = Math.min(Math.max(options.limit ?? 50, 1), 250)
  _inflight = (async () => {
    const params = new URLSearchParams({ limit: String(limit) })
    const response = await fetch(`/api/runs?${params.toString()}`, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal,
    })
    if (!response.ok) {
      throw new Error(`Failed to load runs (${response.status})`)
    }
    const payload = (await response.json()) as RawRunPayload
    const rawList = Array.isArray(payload?.runs) ? payload.runs : []
    const items: RunSidebarItem[] = []
    for (const raw of rawList) {
      const normalized = normalizeRun(raw)
      if (normalized) items.push(normalized)
    }
    items.sort((a, b) => sortEpochMs(b.updated_at) - sortEpochMs(a.updated_at))
    return items
  })()
  _inflightExpiresAt = now + DEDUP_WINDOW_MS
  try {
    return await _inflight
  } finally {
    _inflight = null
  }
}
