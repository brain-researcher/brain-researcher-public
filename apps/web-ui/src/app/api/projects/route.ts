import { NextRequest, NextResponse } from 'next/server'

import {
  forwardAuthHeaders,
  resolveAgentBaseUrl,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import type { AnalysisStatus } from '@/types/analysis'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const DEFAULT_PROJECT_RUNS_LIMIT = 200

type ProjectAnalysis = {
  analysis_id?: string
  job_id?: string
  run_id?: string
  state?: string
  status?: string
  created_at?: number | string
  project_id?: string | null
}

type OrchestratorAnalysesListResponse = {
  items?: ProjectAnalysis[]
  count?: number
}

type AgentProject = {
  project_id?: string
  name?: string
  description?: string | null
  created_at?: number | string
  updated_at?: number | string
  is_archived?: boolean | number
}

type AgentProjectsListResponse = {
  projects?: AgentProject[]
  count?: number
}

type ProjectSummary = {
  project_id: string
  name: string
  description: string | null
  is_archived: boolean
  run_count: number
  latest_run_id: string | null
  latest_status: AnalysisStatus
  latest_created_at: number | null
  status_counts: Record<'running' | 'completed' | 'failed' | 'other', number>
}

type ProjectsListResponse = {
  items: ProjectSummary[]
  count: number
  sampled_runs: number
  upstream_total_runs: number | null
  truncated: boolean
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max)

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function toEpochSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e11 ? Math.floor(value / 1000) : value
  }
  if (typeof value !== 'string' || !value.trim()) return null
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return null
  return Math.floor(ms / 1000)
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

function statusBucket(status: AnalysisStatus): 'running' | 'completed' | 'failed' | 'other' {
  if (status === 'running' || status === 'queued' || status === 'pending' || status === 'retrying') {
    return 'running'
  }
  if (status === 'completed') return 'completed'
  if (status === 'failed' || status === 'timeout' || status === 'cancelled') return 'failed'
  return 'other'
}

function emptyProject(projectId: string): ProjectSummary {
  return {
    project_id: projectId,
    name: projectId === 'default' ? 'Default Project' : projectId,
    description: null,
    is_archived: false,
    run_count: 0,
    latest_run_id: null,
    latest_status: 'unknown',
    latest_created_at: null,
    status_counts: {
      running: 0,
      completed: 0,
      failed: 0,
      other: 0,
    },
  }
}

async function passthrough(
  upstream: Response,
): Promise<Response> {
  const raw = await upstream.text()
  return new NextResponse(raw, {
    status: upstream.status,
    headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' },
  })
}

export async function GET(req: NextRequest) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  const runsLimit = clamp(
    Number(req.nextUrl.searchParams.get('runs_limit')) || DEFAULT_PROJECT_RUNS_LIMIT,
    1,
    DEFAULT_PROJECT_RUNS_LIMIT,
  )
  const headers = forwardAuthHeaders(req)

  let analysesUpstream: Response
  let projectsUpstream: Response | null = null
  try {
    ;[projectsUpstream, analysesUpstream] = await Promise.all([
      fetch(`${resolveAgentBaseUrl()}/api/projects`, {
        method: 'GET',
        headers,
        cache: 'no-store',
      }),
      fetch(`${resolveOrchestratorBaseUrl()}/api/analyses?limit=${runsLimit}`, {
        method: 'GET',
        headers,
        cache: 'no-store',
      }),
    ])
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to list projects' },
      { status: 503 },
    )
  }

  if (!analysesUpstream.ok) {
    return passthrough(analysesUpstream)
  }

  const analysesRaw = await analysesUpstream.text()

  let analysesParsed: OrchestratorAnalysesListResponse
  try {
    analysesParsed = JSON.parse(analysesRaw) as OrchestratorAnalysesListResponse
  } catch {
    return NextResponse.json(
      { error: 'E-UPSTREAM-PARSE', detail: 'Upstream returned invalid JSON for analyses' },
      { status: 502 },
    )
  }

  let projectsParsed: AgentProjectsListResponse | null = null
  if (projectsUpstream?.ok) {
    try {
      const projectsRaw = await projectsUpstream.text()
      projectsParsed = JSON.parse(projectsRaw) as AgentProjectsListResponse
    } catch {
      projectsParsed = null
    }
  }

  const byProject = new Map<string, ProjectSummary>()
  const projects = Array.isArray(projectsParsed?.projects) ? projectsParsed.projects : []
  for (const project of projects) {
    const projectId = normalizeId(project.project_id)
    if (!projectId) continue
    const base = emptyProject(projectId)
    base.name = normalizeId(project.name) || base.name
    base.description =
      typeof project.description === 'string'
        ? project.description
        : project.description == null
          ? null
          : String(project.description)
    base.is_archived = Boolean(project.is_archived)
    byProject.set(projectId, base)
  }

  const analyses = Array.isArray(analysesParsed.items) ? analysesParsed.items : []
  for (const analysis of analyses) {
    const projectId = normalizeId(analysis.project_id) || 'default'
    const summary = byProject.get(projectId) ?? emptyProject(projectId)
    summary.run_count += 1

    const status = normalizeStatus(analysis.state ?? analysis.status)
    const bucket = statusBucket(status)
    summary.status_counts[bucket] += 1

    const createdAt = toEpochSeconds(analysis.created_at)
    if (createdAt && (!summary.latest_created_at || createdAt > summary.latest_created_at)) {
      summary.latest_created_at = createdAt
      summary.latest_run_id =
        normalizeId(analysis.run_id) ||
        normalizeId(analysis.analysis_id) ||
        normalizeId(analysis.job_id) ||
        null
      summary.latest_status = status
    }

    byProject.set(projectId, summary)
  }

  if (!byProject.has('default')) {
    byProject.set('default', emptyProject('default'))
  }

  const items = Array.from(byProject.values()).sort((a, b) => {
    const aTs = a.latest_created_at ?? 0
    const bTs = b.latest_created_at ?? 0
    if (aTs !== bTs) return bTs - aTs
    if (a.project_id === 'default') return -1
    if (b.project_id === 'default') return 1
    return a.project_id.localeCompare(b.project_id)
  })

  const upstreamTotal =
    typeof analysesParsed.count === 'number' && Number.isFinite(analysesParsed.count)
      ? analysesParsed.count
      : null

  const response: ProjectsListResponse = {
    items,
    count: items.length,
    sampled_runs: analyses.length,
    upstream_total_runs: upstreamTotal,
    truncated: upstreamTotal != null ? analyses.length < upstreamTotal : analyses.length >= runsLimit,
  }

  return NextResponse.json(response)
}

export async function POST(req: NextRequest) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON payload.' }, { status: 400 })
  }

  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  let upstream: Response
  try {
    upstream = await fetch(`${resolveAgentBaseUrl()}/api/projects`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to create project' },
      { status: 503 },
    )
  }

  return passthrough(upstream)
}
