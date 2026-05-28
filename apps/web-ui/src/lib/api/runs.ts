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
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
  error_message: string | null
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

function normalizeSource(value: unknown): RunSidebarSource {
  if (value === 'internal') return 'internal'
  if (value === 'external') return 'external'
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
  const plan = pickRecord(record.plan) || {}
  const workflowFromPlan =
    stringOrNull((plan as Record<string, unknown>).workflow_id) ||
    stringOrNull((plan as Record<string, unknown>).template_id) ||
    stringOrNull((plan as Record<string, unknown>).pipeline)
  const datasetFromPlan =
    stringOrNull((plan as Record<string, unknown>).dataset_id) ||
    stringOrNull((plan as Record<string, unknown>).dataset)
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
    created_at: stringOrNull(record.created_at),
    updated_at:
      stringOrNull(record.updated_at) ||
      stringOrNull(record.finished_at) ||
      stringOrNull(record.started_at) ||
      stringOrNull(record.created_at),
    finished_at: stringOrNull(record.finished_at),
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
    items.sort((a, b) => {
      const aMs = a.updated_at ? Date.parse(a.updated_at) : 0
      const bMs = b.updated_at ? Date.parse(b.updated_at) : 0
      return bMs - aMs
    })
    return items
  })()
  _inflightExpiresAt = now + DEDUP_WINDOW_MS
  try {
    return await _inflight
  } finally {
    _inflight = null
  }
}
