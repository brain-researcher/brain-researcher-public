import { NextRequest, NextResponse } from 'next/server'

import { executeHypothesisRun } from '@/lib/server/hypothesis-runner'
import {
  appendLocalHypothesisMessage,
  getOrCreateLocalHypothesisSessionPersisted,
} from '@/lib/server/hypothesis-local-store'
import { forwardAuthHeaders } from '@/lib/server/downstream'
import {
  createRun,
  emitAssistantMessage,
  emitRunState,
  markRunClarifying,
  updateIntentSummaryPersisted,
} from '@/lib/server/hypothesis-run-store'
import type { HypothesisRunStartResponse } from '@/types/hypothesis'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function asOptionalNumber(value: unknown): number | null | undefined {
  if (value === null) return null
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function asOptionalBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['1', 'true', 'yes', 'on'].includes(normalized)) return true
    if (['0', 'false', 'no', 'off'].includes(normalized)) return false
  }
  return undefined
}

function asNonNegativeInt(value: unknown): number | undefined {
  const parsed = asOptionalNumber(value)
  if (parsed === null || parsed === undefined) return undefined
  if (!Number.isFinite(parsed)) return undefined
  const normalized = Math.trunc(parsed)
  if (normalized < 0) return undefined
  return normalized
}

function asPositiveInt(value: unknown): number | undefined {
  const parsed = asOptionalNumber(value)
  if (parsed === null || parsed === undefined) return undefined
  if (!Number.isFinite(parsed)) return undefined
  const normalized = Math.trunc(parsed)
  if (normalized <= 0) return undefined
  return normalized
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const sessionId =
    typeof (body as any).session_id === 'string'
      ? (body as any).session_id.trim()
      : typeof (body as any).sessionId === 'string'
        ? (body as any).sessionId.trim()
        : ''

  const message =
    typeof (body as any).message === 'string'
      ? (body as any).message.trim()
      : ''

  if (!sessionId) {
    return NextResponse.json(
      { error: 'missing_session_id', message: 'session_id is required.' },
      { status: 400 },
    )
  }

  if (!message) {
    return NextResponse.json(
      { error: 'missing_message', message: 'message is required.' },
      { status: 400 },
    )
  }

  const session = await getOrCreateLocalHypothesisSessionPersisted({
    sessionId,
    datasetId:
      typeof (body as any).dataset_id === 'string'
        ? (body as any).dataset_id
        : typeof (body as any).datasetId === 'string'
          ? (body as any).datasetId
          : null,
    conceptId:
      typeof (body as any).concept_id === 'string'
        ? (body as any).concept_id
        : typeof (body as any).conceptId === 'string'
          ? (body as any).conceptId
          : null,
    taskId:
      typeof (body as any).task_id === 'string'
        ? (body as any).task_id
        : typeof (body as any).taskId === 'string'
          ? (body as any).taskId
          : null,
    threadId:
      typeof (body as any).thread_id === 'string'
        ? (body as any).thread_id
        : typeof (body as any).threadId === 'string'
          ? (body as any).threadId
          : null,
  })

  const { summary, assistantMessage } = await updateIntentSummaryPersisted({
    sessionId: session.session_id,
    message,
    hasDataset: Boolean(session.context.dataset_id),
  })

  appendLocalHypothesisMessage({
    sessionId: session.session_id,
    role: 'user',
    content: message,
  })

  const deepResearchFileStores = asStringArray(
    (body as any).file_search_store_names ?? (body as any).fileSearchStoreNames,
  )
  const deepResearchExcludeDomains = asStringArray(
    (body as any).exclude_domains ?? (body as any).excludeDomains,
  )
  const deepResearchRecencyDays = asOptionalNumber(
    (body as any).recency_days ?? (body as any).recencyDays,
  )
  const deepResearchLanguage =
    typeof (body as any).language === 'string' ? (body as any).language.trim() : ''
  const deepResearchPollIntervalMs = asPositiveInt(
    (body as any).deep_research_poll_interval_ms ??
      (body as any).deepResearchPollIntervalMs ??
      process.env.HYPOTHESIS_DEEP_RESEARCH_POLL_INTERVAL_MS,
  )
  const deepResearchMaxPolls = asNonNegativeInt(
    (body as any).deep_research_max_polls ??
      (body as any).deepResearchMaxPolls ??
      process.env.HYPOTHESIS_DEEP_RESEARCH_MAX_POLLS,
  )
  const deepResearchStartGracePolls = asNonNegativeInt(
    (body as any).deep_research_start_grace_polls ??
      (body as any).deepResearchStartGracePolls ??
      process.env.HYPOTHESIS_DEEP_RESEARCH_START_GRACE_POLLS,
  )
  const deepResearchUiWaitSec = asNonNegativeInt(
    (body as any).deep_research_ui_wait_sec ??
      (body as any).deepResearchUiWaitSec ??
      process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC,
  )
  const deepResearchBackgroundCapSec = asPositiveInt(
    (body as any).deep_research_background_cap_sec ??
      (body as any).deepResearchBackgroundCapSec ??
      process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC,
  )
  const kgNoSeedSoftFail = asOptionalBoolean(
    (body as any).kg_no_seed_soft_fail ??
      (body as any).kgNoSeedSoftFail ??
      process.env.HYPOTHESIS_KG_NO_SEED_SOFT_FAIL,
  )
  const kgFirst = asOptionalBoolean(
    (body as any).kg_first ?? (body as any).kgFirst ?? process.env.HYPOTHESIS_KG_FIRST,
  )
  const kgTimeoutSec = asOptionalNumber(
    (body as any).kg_timeout_sec ?? (body as any).kgTimeoutSec ?? process.env.HYPOTHESIS_KG_TIMEOUT_SEC,
  )
  const kgPromptTopK = asPositiveInt(
    (body as any).kg_prompt_topk ??
      (body as any).kgPromptTopK ??
      process.env.HYPOTHESIS_KG_PROMPT_TOPK,
  )
  const kgPromptMaxChars = asPositiveInt(
    (body as any).kg_prompt_max_chars ??
      (body as any).kgPromptMaxChars ??
      process.env.HYPOTHESIS_KG_PROMPT_MAX_CHARS,
  )
  const kgMaxSeedRetries = asNonNegativeInt(
    (body as any).kg_max_seed_retries ??
      (body as any).kgMaxSeedRetries ??
      process.env.HYPOTHESIS_KG_MAX_SEED_RETRIES,
  )
  const nCandidates = asPositiveInt(
    (body as any).n_candidates ??
      (body as any).nCandidates ??
      process.env.HYPOTHESIS_CANDIDATE_COUNT,
  )
  const authHeaders = forwardAuthHeaders(req)

  const run = createRun({
    sessionId: session.session_id,
    state: summary.intent_ready ? 'running' : 'clarifying',
    intentSummary: summary,
  })

  emitRunState(
    run.run_id,
    summary.intent_ready ? 'running' : 'clarifying',
    summary.intent_ready ? 'Intent is ready. Starting run.' : 'Intent still needs clarification.',
  )
  emitAssistantMessage(run.run_id, assistantMessage)
  appendLocalHypothesisMessage({
    sessionId: session.session_id,
    role: 'assistant',
    content: assistantMessage,
  })

  if (summary.intent_ready) {
    void executeHypothesisRun({
      runId: run.run_id,
      sessionId: session.session_id,
      intentSummary: summary,
      authHeaders,
      deepResearchOptions: {
        fileSearchStoreNames: deepResearchFileStores,
        excludeDomains: deepResearchExcludeDomains,
        recencyDays: deepResearchRecencyDays,
        language: deepResearchLanguage || undefined,
        pollIntervalMs: deepResearchPollIntervalMs,
        maxPolls: deepResearchMaxPolls,
        startGracePolls: deepResearchStartGracePolls,
        uiWaitSec: deepResearchUiWaitSec,
        backgroundCapSec: deepResearchBackgroundCapSec,
      },
      kgCompareOptions: {
        softenNoSeedError: kgNoSeedSoftFail,
        maxSeedRetries: kgMaxSeedRetries,
      },
      kgOrchestrationOptions: {
        kgFirst,
        timeoutSec: kgTimeoutSec,
        promptTopK: kgPromptTopK,
        promptMaxChars: kgPromptMaxChars,
      },
      nCandidates,
    })
  } else {
    markRunClarifying(run.run_id, 'Waiting for more intent details before execution.')
  }

  const response: HypothesisRunStartResponse = {
    run_id: run.run_id,
    session_id: session.session_id,
    state: run.state,
    intent_ready: summary.intent_ready,
    intent_summary: summary,
    assistant_message: assistantMessage,
  }

  return NextResponse.json(response)
}
