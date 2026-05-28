import { NextRequest, NextResponse } from 'next/server'

import {
  getLocalHypothesisSessionPersisted,
  getOrCreateLocalHypothesisSessionPersisted,
  upsertLocalHypothesisSessionFromRemote,
} from '@/lib/server/hypothesis-local-store'
import { proxyHypothesis, shouldFallbackToLocalHypothesis } from '@/lib/server/hypothesis-proxy'
import { getRunSnapshotsForSessionPersisted } from '@/lib/server/hypothesis-run-store'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function resolveSessionId(req: NextRequest): string {
  const direct = req.nextUrl.searchParams.get('sessionId') || req.nextUrl.searchParams.get('session_id')
  return typeof direct === 'string' ? direct.trim() : ''
}

function normalizeRunId(raw: unknown): string {
  if (!raw || typeof raw !== 'object') return ''
  const source = raw as Record<string, unknown>
  const runId = source.run_id ?? source.runId ?? source.id
  return typeof runId === 'string' ? runId.trim() : ''
}

function asNullableString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized || null
}

function normalizeEntityId(raw: unknown): string {
  if (!raw || typeof raw !== 'object') return ''
  const source = raw as Record<string, unknown>
  return (
    asNullableString(source.id) ||
    asNullableString(source.question_id) ||
    asNullableString(source.questionId) ||
    asNullableString(source.hypothesis_id) ||
    asNullableString(source.hypothesisId) ||
    ''
  )
}

function mergeByEntityId(upstreamItems: unknown, localItems: unknown): unknown[] {
  const upstream = Array.isArray(upstreamItems) ? upstreamItems : []
  const local = Array.isArray(localItems) ? localItems : []
  const merged = new Map<string, unknown>()

  for (const item of local) {
    const id = normalizeEntityId(item)
    if (!id) continue
    merged.set(id, item)
  }

  for (const item of upstream) {
    const id = normalizeEntityId(item)
    if (!id) continue
    merged.set(id, item)
  }

  return Array.from(merged.values())
}

function mergeMessages(upstreamMessages: unknown, localMessages: unknown): unknown[] {
  const upstream = Array.isArray(upstreamMessages) ? upstreamMessages : []
  const local = Array.isArray(localMessages) ? localMessages : []
  const merged = new Map<string, unknown>()

  const put = (value: unknown) => {
    if (!value || typeof value !== 'object') return
    const source = value as Record<string, unknown>
    const id = asNullableString(source.id)
    const role = asNullableString(source.role) || 'assistant'
    const content = asNullableString(source.content) || ''
    const timestamp =
      asNullableString(source.timestamp) ||
      asNullableString(source.updated_at) ||
      asNullableString(source.updatedAt) ||
      new Date(0).toISOString()
    const key = id || `${role}:${timestamp}:${content}`
    merged.set(key, value)
  }

  local.forEach(put)
  upstream.forEach(put)

  return Array.from(merged.values()).sort((left, right) => {
    const l = left as Record<string, unknown>
    const r = right as Record<string, unknown>
    const lTime = Date.parse(asNullableString(l.timestamp) || '')
    const rTime = Date.parse(asNullableString(r.timestamp) || '')
    return (Number.isFinite(lTime) ? lTime : 0) - (Number.isFinite(rTime) ? rTime : 0)
  })
}

function mergeContext(upstreamContext: unknown, localContext: unknown, sessionId: string): Record<string, unknown> {
  const upstream = upstreamContext && typeof upstreamContext === 'object'
    ? (upstreamContext as Record<string, unknown>)
    : {}
  const local = localContext && typeof localContext === 'object'
    ? (localContext as Record<string, unknown>)
    : {}
  return {
    session_id:
      asNullableString(upstream.session_id) ||
      asNullableString(upstream.sessionId) ||
      asNullableString(local.session_id) ||
      sessionId,
    dataset_id:
      asNullableString(upstream.dataset_id) ||
      asNullableString(upstream.datasetId) ||
      asNullableString(local.dataset_id) ||
      null,
    concept_id:
      asNullableString(upstream.concept_id) ||
      asNullableString(upstream.conceptId) ||
      asNullableString(local.concept_id) ||
      null,
    task_id:
      asNullableString(upstream.task_id) ||
      asNullableString(upstream.taskId) ||
      asNullableString(local.task_id) ||
      null,
    thread_id:
      asNullableString(upstream.thread_id) ||
      asNullableString(upstream.threadId) ||
      asNullableString(local.thread_id) ||
      null,
  }
}

function mergeSessionPayload(
  payload: Record<string, unknown>,
  localSession: Record<string, unknown> | null,
): Record<string, unknown> {
  if (!localSession) return payload

  const sessionId =
    asNullableString(payload.session_id) ||
    asNullableString(payload.sessionId) ||
    asNullableString(localSession.session_id) ||
    asNullableString(localSession.sessionId) ||
    ''

  const mergedOpenQuestions = mergeByEntityId(
    payload.open_questions ?? payload.openQuestions,
    localSession.open_questions ?? localSession.openQuestions,
  )
  const mergedCandidates = mergeByEntityId(
    payload.candidates ?? payload.hypotheses,
    localSession.candidates ?? localSession.hypotheses,
  )
  const mergedMessages = mergeMessages(payload.messages, localSession.messages)

  return {
    ...payload,
    session_id: sessionId || payload.session_id || payload.sessionId,
    context: mergeContext(payload.context, localSession.context, sessionId),
    open_questions: mergedOpenQuestions,
    candidates: mergedCandidates,
    messages: mergedMessages,
    selected_hypothesis_id:
      asNullableString(payload.selected_hypothesis_id) ||
      asNullableString(payload.selectedHypothesisId) ||
      asNullableString(localSession.selected_hypothesis_id) ||
      asNullableString(localSession.selectedHypothesisId),
    leaderboard_url:
      asNullableString(payload.leaderboard_url) ||
      asNullableString(payload.leaderboardUrl) ||
      asNullableString(localSession.leaderboard_url) ||
      asNullableString(localSession.leaderboardUrl),
    updated_at:
      asNullableString(payload.updated_at) ||
      asNullableString(payload.updatedAt) ||
      asNullableString(localSession.updated_at) ||
      asNullableString(localSession.updatedAt),
  }
}

function mergeRuns(upstreamRuns: unknown, localRuns: unknown[]): unknown[] {
  const normalizedUpstream = Array.isArray(upstreamRuns) ? upstreamRuns : []
  const seen = new Set<string>()
  const merged: unknown[] = []

  for (const run of normalizedUpstream) {
    const runId = normalizeRunId(run)
    if (!runId || seen.has(runId)) continue
    seen.add(runId)
    merged.push(run)
  }

  for (const run of localRuns) {
    const runId = normalizeRunId(run)
    if (!runId || seen.has(runId)) continue
    seen.add(runId)
    merged.push(run)
  }

  merged.sort((left, right) => {
    const l = left as Record<string, unknown>
    const r = right as Record<string, unknown>
    const lTime = Date.parse(
      (typeof l.updated_at === 'string' && l.updated_at) ||
        (typeof l.started_at === 'string' && l.started_at) ||
        '',
    )
    const rTime = Date.parse(
      (typeof r.updated_at === 'string' && r.updated_at) ||
        (typeof r.started_at === 'string' && r.started_at) ||
        '',
    )
    return (Number.isFinite(rTime) ? rTime : 0) - (Number.isFinite(lTime) ? lTime : 0)
  })

  return merged
}

export async function GET(req: NextRequest) {
  const sessionId = resolveSessionId(req)
  const localSession = sessionId ? await getLocalHypothesisSessionPersisted(sessionId) : null
  const localRuns = sessionId
    ? await getRunSnapshotsForSessionPersisted({ sessionId, limit: 30 })
    : []

  const params = new URLSearchParams(req.nextUrl.searchParams)
  const upstream = await proxyHypothesis(req, {
    method: 'GET',
    pathname: '/session',
    searchParams: params,
  })

  if (upstream.ok) {
    const payload = await upstream.clone().json().catch(() => null)
    if (!payload || typeof payload !== 'object') {
      return upstream
    }

    const source = payload as Record<string, unknown>
    const mirrored = await upsertLocalHypothesisSessionFromRemote({
      sessionId:
        sessionId ||
        asNullableString(source.session_id) ||
        asNullableString(source.sessionId) ||
        undefined,
      session: payload,
      openQuestions: source.open_questions ?? source.openQuestions,
      candidates: source.candidates ?? source.hypotheses,
      messages: source.messages,
      selectedHypothesisId: source.selected_hypothesis_id ?? source.selectedHypothesisId,
      leaderboardUrl: source.leaderboard_url ?? source.leaderboardUrl,
    })
    const mergedPayload = mergeSessionPayload(
      source,
      (mirrored || localSession) as unknown as Record<string, unknown> | null,
    )
    mergedPayload.runs = mergeRuns(source.runs, localRuns as unknown[])
    return NextResponse.json(mergedPayload)
  }

  if (!shouldFallbackToLocalHypothesis(upstream.status)) {
    return upstream
  }

  const session = await getOrCreateLocalHypothesisSessionPersisted({
    sessionId: req.nextUrl.searchParams.get('sessionId') || req.nextUrl.searchParams.get('session_id'),
    datasetId: req.nextUrl.searchParams.get('datasetId'),
    conceptId: req.nextUrl.searchParams.get('conceptId'),
    taskId: req.nextUrl.searchParams.get('taskId'),
    threadId: req.nextUrl.searchParams.get('threadId'),
  })

  return NextResponse.json({
    ...session,
    runs: mergeRuns([], localRuns as unknown[]),
  })
}
