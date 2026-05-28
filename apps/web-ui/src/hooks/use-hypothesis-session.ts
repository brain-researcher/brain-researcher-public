'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'

import type {
  AgentName,
  AgentTrace,
  AgentTraceStatus,
  BatchRunSummary,
  BatchRunStatus,
  CandidateGroundingStatus,
  EvidenceAnchor,
  HypothesisArtifactEnvelope,
  HypothesisCandidate,
  HypothesisCanvas,
  HypothesisChatMessage,
  HypothesisContext,
  HypothesisEvidenceItem,
  HypothesisEvidenceKind,
  HypothesisRunEvent,
  HypothesisRunStartResponse,
  HypothesisRunState,
  HypothesisScore,
  HypothesisSession,
  HypothesisStatus,
  MDEPlan,
  OpenQuestion,
  OpenQuestionStatus,
  ProgressEvent,
  ProgressStage,
  ResearchPreview,
  ValidationReport,
  WorkflowPlan,
} from '@/types/hypothesis'

type SessionQuery = {
  sessionId?: string
  runId?: string
  datasetId?: string
  conceptId?: string
  taskId?: string
  threadId?: string
}

type ExploreParams = {
  openQuestionId?: string
  nCandidates?: number
  constraints?: Record<string, unknown>
}

type DeepResearchParams = ExploreParams & {
  queryTerm?: string
  finalize?: boolean
}

type SendChatParams = {
  message: string
  selectedHypothesisId?: string | null
}

type RunBatchParams = {
  hypothesisIds: string[]
  budget?: Record<string, unknown>
}

type JsonRecord = Record<string, unknown>
type ArtifactCandidate = {
  id: string
  title: string
  summary: string
  source: 'session' | 'workflow'
  grounding_status: CandidateGroundingStatus
  confidence: number | null
  semantic_alignment: number | null
  anchor_quality: {
    primary: number
    secondary: number
    tertiary: number
  } | null
  anchor_dim: string | null
  anchor_source: 'kg' | 'evidence' | 'kg_compare' | 'hybrid' | null
  anchor_evidence_ids: string[]
  diversity_retry_count: number
  pattern_id: string | null
  pattern_label: string | null
  claim: string | null
  evidence_anchors: EvidenceAnchor[]
  fallback_reasons: string[]
  share_allowed: boolean
  independent_variable: string | null
  dependent_variable: string | null
  expected_signal: string | null
  likely_data_source: string | null
  novelty_gap: string | null
  risk_note: string | null
  minimal_discriminating_test: string | null
  falsifier_hint: string | null
  taste_axis: string | null
}

type KgCompareArtifact = {
  prior_art_match: string[]
  novelty_gap: string[]
  feasibility_constraints: string[]
  novelty_taste: {
    structural_leverage: string[]
    contradiction_motifs: string[]
    ood_hypotheses: string[]
    topology_shifts: string[]
  }
}

type CandidateArtifactSummary = {
  grounded_count: number
  weak_count: number
  draft_count: number
  total_count: number
}

type CandidateArtifactDiagnostics = {
  deep_research_used: boolean
  deep_research_pending: boolean
  kg_first_used: boolean
  kg_timeout_applied: boolean
  workflow_id: string | null
  candidate_lane_mode: string | null
  mcp_fallback_used: boolean
  kg_injection_tokens_est: number
  degenerate_evidence: boolean
  degenerate_mode: 'soft_keep_top1' | 'none'
  kg_used: boolean
  fallback_used: boolean
  generation_mode: 'evidence_first' | 'template_fallback' | 'template_diversified'
  fact_count: number
  cluster_count: number
  selected_cluster_count: number
  anchor_pool_size: number
  unique_anchor_dims: number
  pattern_reuse_count: number
  diversity_resample_count: number
  diversity_exhausted_slots: number
  qualifying_evidence_count: number
  distinct_qualifying_docs: number
  overlap_threshold: number
  primary_anchor_required: boolean
  evidence_quality_counts: {
    primary: number
    secondary: number
    tertiary: number
  }
  reasons: string[]
}

type CandidateEvidenceTrace = {
  facts: Array<{
    id: string
    evidence_id: string
    text: string
    relevance: number
    quality_tier: 'primary' | 'secondary' | 'tertiary'
    source_channel: NonNullable<HypothesisEvidenceItem['source_channel']>
  }>
  clusters: Array<{
    id: string
    fact_ids: string[]
    evidence_ids: string[]
    key_terms: string[]
    score: number
  }>
}

type EvidenceArtifactMeta = {
  is_fallback: boolean
  grounding_quality: 'grounded' | 'partial' | 'draft_unverified' | 'pending'
  deep_research_status: 'pending' | 'ready' | 'failed'
  deep_research_report_available: boolean
  deep_research_report_artifact_id: string | null
  research_coverage_stats: {
    scanned_sources: number
    qualifying_sources: number
    unique_after_dedupe: number
    final_citable_sources: number
    discarded_sources: number
  }
  kg_injected: boolean
  kg_injection_summary: string | null
  kg_injection_truncated: boolean
  degenerate_evidence: boolean
  degenerate_reason: string | null
  dedupe_stats: {
    before: number
    after: number
    collapsed_groups: number
  }
  pending_message: string | null
  source_stats: {
    total: number
    by_kind: Record<string, number>
    by_channel: Record<string, number>
    by_quality: Record<string, number>
  }
  warnings: string[]
}

type DeepResearchReportArtifact = {
  query: string
  status: string
  interaction_id: string | null
  idempotency_key: string | null
  summary: string
  synthesis_full_text: string
  synthesis_generated_by: 'upstream' | 'llm_fallback' | 'fallback_rule'
  synthesis_source_count: number
  search_trails: Array<{
    stage: 'start' | 'poll' | 'sync_fallback'
    tool: string
    status: string
    detail: string | null
  }>
  historical_trails_available: boolean
  source_inventory: Array<{
    id: string
    label: string
    display_title: string | null
    summary: string | null
    url: string | null
    raw_url: string | null
    final_url: string | null
    source_host: string | null
    kind: HypothesisEvidenceKind
    source_type: 'paper' | 'dataset' | 'other' | null
    quality_tier: 'primary' | 'secondary' | 'tertiary' | null
    traceability_score: number | null
  }>
  discarded_sources: Array<{
    id: string
    label: string
    display_title: string | null
    summary: string | null
    url: string | null
    raw_url: string | null
    final_url: string | null
    source_host: string | null
    kind: HypothesisEvidenceKind
    source_type: 'paper' | 'dataset' | 'other' | null
    quality_tier: 'primary' | 'secondary' | 'tertiary' | null
    traceability_score: number | null
    reason_code:
      | 'redirect_unresolved'
      | 'duplicate_cluster'
      | 'duplicate_similarity'
      | 'synthetic_summary'
      | 'top_n_trim'
      | 'missing_url_or_label'
      | 'unknown'
    reason_detail: string | null
    reason_meta: {
      attempted: boolean
      resolver: 'none' | 'query_param' | 'head' | 'get'
      http_status: number | null
      error: string | null
      skipped_by_budget: boolean
    } | null
  }>
  discarded_aggregates: Array<{
    reason_code:
      | 'redirect_unresolved'
      | 'duplicate_cluster'
      | 'duplicate_similarity'
      | 'synthetic_summary'
      | 'top_n_trim'
      | 'missing_url_or_label'
      | 'unknown'
    count: number
    detail: string
    stats: Record<string, number>
  }>
  search_stats: {
    scanned_count: number
    qualifying_count: number
    unique_after_dedupe_count: number
    final_citable_count: number
    discarded_count: number
  }
  generated_at: string
}

type HotLoadTrajectoryArtifact = {
  trajectory_version: 'v1'
  trigger_kind: 'free_text_query'
  query: string
  query_normalized: string
  captured_at: string
  workflow: {
    workflow_id: string | null
    candidate_lane_mode: string | null
    mcp_fallback_used: boolean
    verification_source: 'mcp_workflow' | 'local_fallback'
  }
  resolved_anchor_bundle: Array<{
    kg_id: string
    label: string | null
    node_type: string | null
    matched_queries: string[]
    score: number | null
    rank: number | null
  }>
  candidate_cards: {
    total_count: number
    grounded_count: number
    weak_count: number
    draft_count: number
    verdict_counts: Record<string, number>
    evidence_source_scope_counts: Record<string, number>
    deep_research_status_counts: Record<string, number>
  }
  evidence: {
    total_count: number
    grounding_quality: 'grounded' | 'partial' | 'draft_unverified' | 'pending'
    deep_research_status: 'pending' | 'ready' | 'failed'
    source_channel_counts: Record<string, number>
    quality_counts: Record<string, number>
  }
  deep_research: {
    used: boolean
    pending: boolean
    report_available: boolean
    report_artifact_id: string | null
    warning: string | null
  }
  warnings: string[]
}

type HypothesisArtifactState = {
  canvas: HypothesisCanvas | null
  preview: ResearchPreview | null
  candidates: ArtifactCandidate[]
  candidateSummary: CandidateArtifactSummary | null
  candidateDiagnostics: CandidateArtifactDiagnostics | null
  candidateTrace: CandidateEvidenceTrace | null
  evidence: HypothesisEvidenceItem[]
  evidenceMeta: EvidenceArtifactMeta | null
  deepResearchReport: DeepResearchReportArtifact | null
  hotLoadTrajectory: HotLoadTrajectoryArtifact | null
  plan: WorkflowPlan | null
  validation: ValidationReport | null
  kgCompare: KgCompareArtifact | null
}

const TERMINAL_RUN_STATUSES: BatchRunStatus[] = [
  'completed',
  'failed',
  'cancelled',
  'review_blocked',
]

const INITIAL_ASSISTANT_NOTE =
  'Assistant: Share a broad research question. I will clarify intent, run deep research, and stream artifacts here.'

const asString = (value: unknown): string => (typeof value === 'string' ? value : '')

const asNullableString = (value: unknown): string | null => {
  const normalized = asString(value).trim()
  return normalized || null
}

const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

const asBoolean = (value: unknown, fallback = false): boolean => {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true') return true
    if (normalized === 'false') return false
  }
  return fallback
}

const asStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

const asRecord = (value: unknown): JsonRecord | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as JsonRecord
}

const statusFrom = <T extends string>(
  value: unknown,
  allowed: readonly T[],
  fallback: T,
): T => {
  const normalized = asString(value).trim().toLowerCase() as T
  return allowed.includes(normalized) ? normalized : fallback
}

function normalizeScore(raw: unknown): HypothesisScore {
  const source = (raw ?? {}) as JsonRecord
  return {
    total_score: asNumber(source.total_score ?? source.totalScore),
    novelty: asNumber(source.novelty),
    coherence: asNumber(source.coherence),
    leverage: asNumber(source.leverage),
    feasibility: asNumber(source.feasibility),
    risk: asNumber(source.risk),
  }
}

function normalizeAgentTrace(raw: unknown): AgentTrace {
  const source = (raw ?? {}) as JsonRecord
  const agent = statusFrom<AgentName>(
    source.agent,
    ['explorer', 'critic', 'verifier', 'ranker'] as const,
    'explorer',
  )
  const status = statusFrom<AgentTraceStatus>(
    source.status,
    ['ok', 'warning', 'error', 'pending'] as const,
    'pending',
  )
  const details = asStringArray(source.details)
  return {
    agent,
    status,
    summary: asString(source.summary) || `${agent} update pending`,
    details,
    updated_at: asNullableString(source.updated_at ?? source.updatedAt),
  }
}

function normalizeEvidence(raw: unknown): HypothesisEvidenceItem {
  const source = (raw ?? {}) as JsonRecord
  const kind = statusFrom<HypothesisEvidenceKind>(
    source.kind,
    ['paper', 'dataset', 'experiment', 'note', 'other'] as const,
    'other',
  )
  const id =
    asString(source.id).trim() ||
    asString(source.evidence_id ?? source.evidenceId).trim() ||
    `evidence-${Math.random().toString(36).slice(2, 10)}`

  return {
    id,
    label: asString(source.label) || asString(source.title) || 'Untitled evidence',
    kind,
    summary: asNullableString(source.summary),
    synthetic_summary: asBoolean(source.synthetic_summary ?? source.syntheticSummary, false),
    url: asNullableString(source.url),
    raw_url: asNullableString(source.raw_url ?? source.rawUrl),
    display_url: asNullableString(source.display_url ?? source.displayUrl),
    source_host: asNullableString(source.source_host ?? source.sourceHost),
    source_channel: statusFrom<
      NonNullable<HypothesisEvidenceItem['source_channel']>
    >(
      source.source_channel ?? source.sourceChannel,
      [
        'graph',
        'deep_research_live',
        'deep_research_pending',
        'file_search_live',
        'workflow_fallback',
        'other',
      ] as const,
      'other',
    ),
    path_type: asNullableString(source.path_type ?? source.pathType),
    support_count: asNumber(source.support_count ?? source.supportCount),
    freshness_ts: asNullableString(source.freshness_ts ?? source.freshnessTs),
    confidence: asNumber(source.confidence),
    source_type: statusFrom<'paper' | 'dataset' | 'other'>(
      source.source_type ?? source.sourceType,
      ['paper', 'dataset', 'other'] as const,
      'other',
    ),
    quality_tier: statusFrom<'primary' | 'secondary' | 'tertiary'>(
      source.quality_tier ?? source.qualityTier,
      ['primary', 'secondary', 'tertiary'] as const,
      'tertiary',
    ),
    traceability_score: asNumber(source.traceability_score ?? source.traceabilityScore),
  }
}

function normalizeMde(raw: unknown): MDEPlan | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as JsonRecord
  const id =
    asString(source.id).trim() ||
    asString(source.mde_id ?? source.mdeId).trim() ||
    `mde-${Math.random().toString(36).slice(2, 10)}`

  return {
    id,
    objective: asString(source.objective) || asString(source.question) || 'Define discriminating objective',
    minimal_test:
      asString(source.minimal_test ?? source.minimalTest) ||
      asString(source.test) ||
      'Design minimum discriminating test',
    falsifier: asString(source.falsifier) || 'Specify what result would falsify this hypothesis',
    expected_signals: asStringArray(source.expected_signals ?? source.expectedSignals),
    confounds: asStringArray(source.confounds),
    cost_estimate: asNullableString(source.cost_estimate ?? source.costEstimate),
    status: statusFrom<any>(
      source.status,
      ['queued', 'running', 'completed', 'failed', 'cancelled', 'draft', 'ready'] as const,
      'draft',
    ),
  }
}

function normalizeCandidate(raw: unknown): HypothesisCandidate {
  const source = (raw ?? {}) as JsonRecord
  const id =
    asString(source.id).trim() ||
    asString(source.hypothesis_id ?? source.hypothesisId).trim() ||
    `hyp-${Math.random().toString(36).slice(2, 10)}`

  const tracesRaw = Array.isArray(source.traces)
    ? source.traces
    : Array.isArray(source.agent_traces)
      ? source.agent_traces
      : []

  const evidenceRaw = Array.isArray(source.evidence) ? source.evidence : []

  return {
    id,
    title: asString(source.title) || asString(source.name) || 'Untitled hypothesis',
    statement: asString(source.statement) || asString(source.hypothesis) || 'No statement provided.',
    status: statusFrom<HypothesisStatus>(
      source.status,
      ['open', 'provisional', 'selected', 'rejected', 'verified'] as const,
      'open',
    ),
    tags: asStringArray(source.tags),
    open_question_id: asNullableString(source.open_question_id ?? source.openQuestionId),
    rationale: asNullableString(source.rationale),
    score: normalizeScore(source.score),
    traces: tracesRaw.map(normalizeAgentTrace),
    mde: normalizeMde(source.mde),
    evidence: evidenceRaw.map(normalizeEvidence),
    created_at: asNullableString(source.created_at ?? source.createdAt),
    updated_at: asNullableString(source.updated_at ?? source.updatedAt),
  }
}

function normalizeOpenQuestion(raw: unknown): OpenQuestion {
  const source = (raw ?? {}) as JsonRecord
  const id =
    asString(source.id).trim() ||
    asString(source.question_id ?? source.questionId).trim() ||
    `q-${Math.random().toString(36).slice(2, 10)}`

  return {
    id,
    title: asString(source.title) || asString(source.question) || 'Untitled question',
    description: asString(source.description) || '',
    status: statusFrom<OpenQuestionStatus>(
      source.status,
      ['open', 'in_progress', 'resolved'] as const,
      'open',
    ),
    priority: statusFrom<any>(source.priority, ['high', 'medium', 'low'] as const, 'medium'),
    leverage_hint: asNullableString(source.leverage_hint ?? source.leverageHint),
  }
}

function normalizeContext(raw: unknown): HypothesisContext {
  const source = (raw ?? {}) as JsonRecord
  return {
    session_id: asNullableString(source.session_id ?? source.sessionId),
    dataset_id: asNullableString(source.dataset_id ?? source.datasetId),
    concept_id: asNullableString(source.concept_id ?? source.conceptId),
    task_id: asNullableString(source.task_id ?? source.taskId),
    thread_id: asNullableString(source.thread_id ?? source.threadId),
  }
}

function normalizeSession(raw: unknown, query: SessionQuery): HypothesisSession {
  const source = (raw ?? {}) as JsonRecord
  const openQuestionsRaw = Array.isArray(source.open_questions)
    ? source.open_questions
    : Array.isArray(source.openQuestions)
      ? source.openQuestions
      : []
  const candidatesRaw = Array.isArray(source.candidates)
    ? source.candidates
    : Array.isArray(source.hypotheses)
      ? source.hypotheses
      : []
  const messagesRaw = Array.isArray(source.messages) ? source.messages : []

  const sessionId =
    asString(source.session_id).trim() ||
    asString(source.sessionId).trim() ||
    query.sessionId ||
    `session-${Math.random().toString(36).slice(2, 10)}`

  const baseContext = normalizeContext(source.context)

  return {
    session_id: sessionId,
    context: {
      session_id: sessionId,
      dataset_id: baseContext.dataset_id ?? query.datasetId ?? null,
      concept_id: baseContext.concept_id ?? query.conceptId ?? null,
      task_id: baseContext.task_id ?? query.taskId ?? null,
      thread_id: baseContext.thread_id ?? query.threadId ?? null,
    },
    open_questions: openQuestionsRaw.map(normalizeOpenQuestion),
    candidates: candidatesRaw.map(normalizeCandidate),
    messages: messagesRaw
      .map((item) => normalizeChatMessage(item))
      .filter((item): item is HypothesisChatMessage => Boolean(item)),
    selected_hypothesis_id: asNullableString(
      source.selected_hypothesis_id ?? source.selectedHypothesisId,
    ),
    leaderboard_url: asNullableString(source.leaderboard_url ?? source.leaderboardUrl),
    updated_at: asNullableString(source.updated_at ?? source.updatedAt),
  }
}

function normalizeBatchRun(raw: unknown): BatchRunSummary {
  const source = (raw ?? {}) as JsonRecord
  return {
    run_id: asString(source.run_id) || asString(source.id) || asString(source.runId),
    status: statusFrom<BatchRunStatus>(
      source.status,
      ['queued', 'running', 'completed', 'failed', 'cancelled'] as const,
      'queued',
    ),
    queued_count: asNumber(source.queued_count ?? source.queuedCount) ?? undefined,
    started_at: asNullableString(source.started_at ?? source.startedAt),
    updated_at: asNullableString(source.updated_at ?? source.updatedAt),
    leaderboard_url: asNullableString(source.leaderboard_url ?? source.leaderboardUrl),
  }
}

function extractRunId(raw: unknown): string | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as JsonRecord
  const runId = asString(source.run_id ?? source.runId ?? source.id).trim()
  return runId || null
}

function extractLatestRunId(raw: unknown): string | null {
  if (!Array.isArray(raw)) return null
  for (const item of raw) {
    const runId = extractRunId(item)
    if (runId) return runId
  }
  return null
}

function normalizeChatMessage(raw: unknown): HypothesisChatMessage | null {
  const source = (raw ?? {}) as JsonRecord
  const content = asString(source.content).trim()
  if (!content) return null

  const role = statusFrom<HypothesisChatMessage['role']>(
    source.role,
    ['user', 'assistant', 'system'] as const,
    'assistant',
  )

  return {
    id: asString(source.id).trim() || `msg-${Math.random().toString(36).slice(2, 10)}`,
    role,
    content,
    timestamp: asString(source.timestamp).trim() || new Date().toISOString(),
  }
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => '')
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

function mergeCandidates(
  previous: HypothesisCandidate[],
  incoming: HypothesisCandidate[],
): HypothesisCandidate[] {
  const byId = new Map<string, HypothesisCandidate>()
  previous.forEach((candidate) => byId.set(candidate.id, candidate))
  incoming.forEach((candidate) => byId.set(candidate.id, candidate))
  return Array.from(byId.values())
}

const EMPTY_ARTIFACTS: HypothesisArtifactState = {
  canvas: null,
  preview: null,
  candidates: [],
  candidateSummary: null,
  candidateDiagnostics: null,
  candidateTrace: null,
  evidence: [],
  evidenceMeta: null,
  deepResearchReport: null,
  hotLoadTrajectory: null,
  plan: null,
  validation: null,
  kgCompare: null,
}

const HYPOTHESIS_ARTIFACT_KINDS: ReadonlyArray<HypothesisArtifactEnvelope['kind']> = [
  'hypothesis_canvas',
  'evidence_pack',
  'deep_research_report',
  'kg_compare',
  'candidate_cards',
  'hot_load_trajectory',
  'workflow_plan',
  'validation_report',
]

const STREAM_RECOVERY_POLL_MS = 2000
const STREAM_RECOVERY_MAX_ATTEMPTS = 120

function toProgressStage(state: HypothesisRunState): ProgressStage {
  switch (state) {
    case 'completed':
      return 'completed'
    case 'failed':
      return 'failed'
    case 'running':
      return 'running'
    case 'clarifying':
    default:
      return 'clarifying'
  }
}

function normalizeRunStartResponse(raw: unknown): HypothesisRunStartResponse | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as JsonRecord
  const runId = asString(source.run_id ?? source.runId).trim()
  const sessionId = asString(source.session_id ?? source.sessionId).trim()
  const state = statusFrom<HypothesisRunState>(
    source.state,
    ['clarifying', 'running', 'completed', 'failed'] as const,
    'clarifying',
  )
  if (!runId || !sessionId) return null
  return {
    run_id: runId,
    session_id: sessionId,
    state,
    intent_ready: Boolean(source.intent_ready ?? source.intentReady),
    intent_summary:
      (source.intent_summary as HypothesisRunStartResponse['intent_summary']) ?? {
        term: null,
        intent_ready: false,
        missing_fields: [],
      },
    assistant_message: asNullableString(source.assistant_message ?? source.assistantMessage),
  }
}

function normalizeKgCompare(payload: JsonRecord): KgCompareArtifact {
  const noveltyTasteRaw = (payload.novelty_taste ?? payload.noveltyTaste) as JsonRecord | undefined
  return {
    prior_art_match: asStringArray(payload.prior_art_match ?? payload.priorArtMatch),
    novelty_gap: asStringArray(payload.novelty_gap ?? payload.noveltyGap),
    feasibility_constraints: asStringArray(
      payload.feasibility_constraints ?? payload.feasibilityConstraints,
    ),
    novelty_taste: {
      structural_leverage: asStringArray(
        noveltyTasteRaw?.structural_leverage ?? noveltyTasteRaw?.structuralLeverage,
      ),
      contradiction_motifs: asStringArray(
        noveltyTasteRaw?.contradiction_motifs ?? noveltyTasteRaw?.contradictionMotifs,
      ),
      ood_hypotheses: asStringArray(
        noveltyTasteRaw?.ood_hypotheses ?? noveltyTasteRaw?.oodHypotheses,
      ),
      topology_shifts: asStringArray(
        noveltyTasteRaw?.topology_shifts ?? noveltyTasteRaw?.topologyShifts,
      ),
    },
  }
}

function normalizeCandidateSummary(payload: JsonRecord): CandidateArtifactSummary | null {
  const summary = (payload.summary ?? payload.stats) as JsonRecord | undefined
  if (!summary || typeof summary !== 'object') return null
  const grounded = asNumber(summary.grounded_count ?? summary.groundedCount)
  const weak = asNumber(summary.weak_count ?? summary.weakCount)
  const draft = asNumber(summary.draft_count ?? summary.draftCount)
  const total = asNumber(summary.total_count ?? summary.totalCount)
  if (grounded === null || draft === null || total === null) return null
  return {
    grounded_count: grounded,
    weak_count: weak ?? 0,
    draft_count: draft,
    total_count: total,
  }
}

function normalizeCandidateDiagnostics(payload: JsonRecord): CandidateArtifactDiagnostics | null {
  const diagnostics = payload.diagnostics as JsonRecord | undefined
  if (!diagnostics || typeof diagnostics !== 'object') return null
  const qualityCountsRaw = (diagnostics.evidence_quality_counts ??
    diagnostics.evidenceQualityCounts) as JsonRecord | undefined
  return {
    deep_research_used: asBoolean(
      diagnostics.deep_research_used ?? diagnostics.deepResearchUsed,
      false,
    ),
    deep_research_pending: asBoolean(
      diagnostics.deep_research_pending ?? diagnostics.deepResearchPending,
      false,
    ),
    kg_first_used: asBoolean(diagnostics.kg_first_used ?? diagnostics.kgFirstUsed, true),
    kg_timeout_applied: asBoolean(
      diagnostics.kg_timeout_applied ?? diagnostics.kgTimeoutApplied,
      false,
    ),
    workflow_id: asNullableString(diagnostics.workflow_id ?? diagnostics.workflowId),
    candidate_lane_mode: asNullableString(
      diagnostics.candidate_lane_mode ?? diagnostics.candidateLaneMode,
    ),
    mcp_fallback_used: asBoolean(
      diagnostics.mcp_fallback_used ?? diagnostics.mcpFallbackUsed,
      false,
    ),
    kg_injection_tokens_est:
      asNumber(diagnostics.kg_injection_tokens_est ?? diagnostics.kgInjectionTokensEst) ?? 0,
    degenerate_evidence: asBoolean(
      diagnostics.degenerate_evidence ?? diagnostics.degenerateEvidence,
      false,
    ),
    degenerate_mode: statusFrom<'soft_keep_top1' | 'none'>(
      diagnostics.degenerate_mode ?? diagnostics.degenerateMode,
      ['soft_keep_top1', 'none'] as const,
      'none',
    ),
    kg_used: asBoolean(diagnostics.kg_used ?? diagnostics.kgUsed, false),
    fallback_used: asBoolean(diagnostics.fallback_used ?? diagnostics.fallbackUsed, false),
    generation_mode: statusFrom<
      'evidence_first' | 'template_fallback' | 'template_diversified'
    >(
      diagnostics.generation_mode ?? diagnostics.generationMode,
      ['evidence_first', 'template_fallback', 'template_diversified'] as const,
      'template_fallback',
    ),
    fact_count: asNumber(diagnostics.fact_count ?? diagnostics.factCount) ?? 0,
    cluster_count: asNumber(diagnostics.cluster_count ?? diagnostics.clusterCount) ?? 0,
    selected_cluster_count:
      asNumber(diagnostics.selected_cluster_count ?? diagnostics.selectedClusterCount) ?? 0,
    anchor_pool_size:
      asNumber(diagnostics.anchor_pool_size ?? diagnostics.anchorPoolSize) ?? 0,
    unique_anchor_dims:
      asNumber(diagnostics.unique_anchor_dims ?? diagnostics.uniqueAnchorDims) ?? 0,
    pattern_reuse_count:
      asNumber(diagnostics.pattern_reuse_count ?? diagnostics.patternReuseCount) ?? 0,
    diversity_resample_count:
      asNumber(
        diagnostics.diversity_resample_count ?? diagnostics.diversityResampleCount,
      ) ?? 0,
    diversity_exhausted_slots:
      asNumber(
        diagnostics.diversity_exhausted_slots ?? diagnostics.diversityExhaustedSlots,
      ) ?? 0,
    qualifying_evidence_count:
      asNumber(
        diagnostics.qualifying_evidence_count ?? diagnostics.qualifyingEvidenceCount,
      ) ?? 0,
    distinct_qualifying_docs:
      asNumber(
        diagnostics.distinct_qualifying_docs ?? diagnostics.distinctQualifyingDocs,
      ) ?? 0,
    overlap_threshold: asNumber(
      diagnostics.overlap_threshold ?? diagnostics.overlapThreshold,
    ) ?? 0.15,
    primary_anchor_required: asBoolean(
      diagnostics.primary_anchor_required ?? diagnostics.primaryAnchorRequired,
      true,
    ),
    evidence_quality_counts: {
      primary: asNumber(qualityCountsRaw?.primary) ?? 0,
      secondary: asNumber(qualityCountsRaw?.secondary) ?? 0,
      tertiary: asNumber(qualityCountsRaw?.tertiary) ?? 0,
    },
    reasons: asStringArray(diagnostics.reasons),
  }
}

function normalizeCandidateTrace(payload: JsonRecord): CandidateEvidenceTrace | null {
  const trace = (payload.evidence_trace ?? payload.evidenceTrace) as JsonRecord | undefined
  if (!trace || typeof trace !== 'object') return null

  const factsRaw = Array.isArray(trace.facts) ? trace.facts : []
  const clustersRaw = Array.isArray(trace.clusters) ? trace.clusters : []
  const facts = factsRaw
    .map((raw) => {
      const fact = (raw ?? {}) as JsonRecord
      const id = asString(fact.id).trim()
      const evidenceId = asString(fact.evidence_id ?? fact.evidenceId).trim()
      if (!id || !evidenceId) return null
      return {
        id,
        evidence_id: evidenceId,
        text: asString(fact.text),
        relevance: asNumber(fact.relevance) ?? 0,
        quality_tier: statusFrom<'primary' | 'secondary' | 'tertiary'>(
          fact.quality_tier ?? fact.qualityTier,
          ['primary', 'secondary', 'tertiary'] as const,
          'tertiary',
        ),
        source_channel: statusFrom<NonNullable<HypothesisEvidenceItem['source_channel']>>(
          fact.source_channel ?? fact.sourceChannel,
          [
            'graph',
            'deep_research_live',
            'deep_research_pending',
            'file_search_live',
            'workflow_fallback',
            'other',
          ] as const,
          'other',
        ),
      }
    })
    .filter(
      (
        item,
      ): item is {
        id: string
        evidence_id: string
        text: string
        relevance: number
        quality_tier: 'primary' | 'secondary' | 'tertiary'
        source_channel: NonNullable<HypothesisEvidenceItem['source_channel']>
      } => Boolean(item),
    )

  const clusters = clustersRaw
    .map((raw) => {
      const cluster = (raw ?? {}) as JsonRecord
      const id = asString(cluster.id).trim()
      if (!id) return null
      return {
        id,
        fact_ids: asStringArray(cluster.fact_ids ?? cluster.factIds),
        evidence_ids: asStringArray(cluster.evidence_ids ?? cluster.evidenceIds),
        key_terms: asStringArray(cluster.key_terms ?? cluster.keyTerms),
        score: asNumber(cluster.score) ?? 0,
      }
    })
    .filter(
      (
        item,
      ): item is {
        id: string
        fact_ids: string[]
        evidence_ids: string[]
        key_terms: string[]
        score: number
      } => Boolean(item),
    )

  if (!facts.length && !clusters.length) return null
  return { facts, clusters }
}

function normalizeEvidenceMeta(payload: JsonRecord): EvidenceArtifactMeta | null {
  const sourceStats = (payload.source_stats ?? payload.sourceStats) as JsonRecord | undefined
  const byKind = (sourceStats?.by_kind ?? sourceStats?.byKind) as JsonRecord | undefined
  const byChannel = (sourceStats?.by_channel ?? sourceStats?.byChannel) as JsonRecord | undefined
  const byQuality = (sourceStats?.by_quality ?? sourceStats?.byQuality) as JsonRecord | undefined
  const dedupeStats = (payload.dedupe_stats ?? payload.dedupeStats) as JsonRecord | undefined
  const coverageStats = (payload.research_coverage_stats ??
    payload.researchCoverageStats) as JsonRecord | undefined

  const parseCounterMap = (value: JsonRecord | undefined): Record<string, number> => {
    if (!value || typeof value !== 'object') return {}
    const next: Record<string, number> = {}
    for (const [key, raw] of Object.entries(value)) {
      const parsed = asNumber(raw)
      if (parsed !== null) next[key] = parsed
    }
    return next
  }

  const total = asNumber(sourceStats?.total)
  if (
    total === null &&
    !Object.keys(parseCounterMap(byKind)).length &&
    !Object.keys(parseCounterMap(byChannel)).length &&
    !Object.keys(parseCounterMap(byQuality)).length
  ) {
    return null
  }

  return {
    is_fallback: asBoolean(payload.is_fallback ?? payload.isFallback, false),
    grounding_quality: statusFrom<'grounded' | 'partial' | 'draft_unverified' | 'pending'>(
      payload.grounding_quality ?? payload.groundingQuality,
      ['grounded', 'partial', 'draft_unverified', 'pending'] as const,
      'draft_unverified',
    ),
    deep_research_status: statusFrom<'pending' | 'ready' | 'failed'>(
      payload.deep_research_status ?? payload.deepResearchStatus,
      ['pending', 'ready', 'failed'] as const,
      'ready',
    ),
    deep_research_report_available: asBoolean(
      payload.deep_research_report_available ?? payload.deepResearchReportAvailable,
      false,
    ),
    deep_research_report_artifact_id: asNullableString(
      payload.deep_research_report_artifact_id ?? payload.deepResearchReportArtifactId,
    ),
    research_coverage_stats: {
      scanned_sources:
        asNumber(coverageStats?.scanned_sources ?? coverageStats?.scannedSources) ?? 0,
      qualifying_sources:
        asNumber(coverageStats?.qualifying_sources ?? coverageStats?.qualifyingSources) ?? 0,
      unique_after_dedupe:
        asNumber(coverageStats?.unique_after_dedupe ?? coverageStats?.uniqueAfterDedupe) ??
        0,
      final_citable_sources:
        asNumber(
          coverageStats?.final_citable_sources ?? coverageStats?.finalCitableSources,
        ) ?? 0,
      discarded_sources:
        asNumber(coverageStats?.discarded_sources ?? coverageStats?.discardedSources) ?? 0,
    },
    kg_injected: asBoolean(payload.kg_injected ?? payload.kgInjected, false),
    kg_injection_summary: asNullableString(
      payload.kg_injection_summary ?? payload.kgInjectionSummary,
    ),
    kg_injection_truncated: asBoolean(
      payload.kg_injection_truncated ?? payload.kgInjectionTruncated,
      false,
    ),
    degenerate_evidence: asBoolean(
      payload.degenerate_evidence ?? payload.degenerateEvidence,
      false,
    ),
    degenerate_reason: asNullableString(payload.degenerate_reason ?? payload.degenerateReason),
    dedupe_stats: {
      before: asNumber(dedupeStats?.before) ?? 0,
      after: asNumber(dedupeStats?.after) ?? 0,
      collapsed_groups:
        asNumber(dedupeStats?.collapsed_groups ?? dedupeStats?.collapsedGroups) ?? 0,
    },
    pending_message: asNullableString(payload.pending_message ?? payload.pendingMessage),
    source_stats: {
      total: total ?? 0,
      by_kind: parseCounterMap(byKind),
      by_channel: parseCounterMap(byChannel),
      by_quality: parseCounterMap(byQuality),
    },
    warnings: asStringArray(payload.warnings),
  }
}

function normalizeHotLoadTrajectory(payload: JsonRecord): HotLoadTrajectoryArtifact | null {
  const workflow = asRecord(payload.workflow)
  const candidateCards = asRecord(payload.candidate_cards ?? payload.candidateCards)
  const evidence = asRecord(payload.evidence)
  const deepResearch = asRecord(payload.deep_research ?? payload.deepResearch)
  if (!workflow || !candidateCards || !evidence || !deepResearch) return null

  const parseCounterMap = (value: unknown): Record<string, number> => {
    const source = asRecord(value)
    if (!source) return {}
    const next: Record<string, number> = {}
    for (const [key, raw] of Object.entries(source)) {
      const parsed = asNumber(raw)
      if (parsed !== null) next[key] = parsed
    }
    return next
  }

  const resolvedAnchorBundleRaw = Array.isArray(
    payload.resolved_anchor_bundle ?? payload.resolvedAnchorBundle,
  )
    ? ((payload.resolved_anchor_bundle ?? payload.resolvedAnchorBundle) as unknown[])
    : []

  return {
    trajectory_version: 'v1',
    trigger_kind: 'free_text_query',
    query: asString(payload.query),
    query_normalized: asString(payload.query_normalized ?? payload.queryNormalized),
    captured_at:
      asNullableString(payload.captured_at ?? payload.capturedAt) || new Date().toISOString(),
    workflow: {
      workflow_id: asNullableString(workflow.workflow_id ?? workflow.workflowId),
      candidate_lane_mode: asNullableString(
        workflow.candidate_lane_mode ?? workflow.candidateLaneMode,
      ),
      mcp_fallback_used: asBoolean(
        workflow.mcp_fallback_used ?? workflow.mcpFallbackUsed,
        false,
      ),
      verification_source: statusFrom<'mcp_workflow' | 'local_fallback'>(
        workflow.verification_source ?? workflow.verificationSource,
        ['mcp_workflow', 'local_fallback'] as const,
        'mcp_workflow',
      ),
    },
    resolved_anchor_bundle: resolvedAnchorBundleRaw
      .map((raw) => {
        const item = asRecord(raw)
        const kgId = asString(item?.kg_id ?? item?.kgId).trim()
        if (!kgId) return null
        return {
          kg_id: kgId,
          label: asNullableString(item?.label),
          node_type: asNullableString(item?.node_type ?? item?.nodeType),
          matched_queries: asStringArray(item?.matched_queries ?? item?.matchedQueries),
          score: asNumber(item?.score),
          rank: asNumber(item?.rank),
        }
      })
      .filter(
        (
          item,
        ): item is {
          kg_id: string
          label: string | null
          node_type: string | null
          matched_queries: string[]
          score: number | null
          rank: number | null
        } => Boolean(item),
      ),
    candidate_cards: {
      total_count: asNumber(candidateCards.total_count ?? candidateCards.totalCount) ?? 0,
      grounded_count:
        asNumber(candidateCards.grounded_count ?? candidateCards.groundedCount) ?? 0,
      weak_count: asNumber(candidateCards.weak_count ?? candidateCards.weakCount) ?? 0,
      draft_count: asNumber(candidateCards.draft_count ?? candidateCards.draftCount) ?? 0,
      verdict_counts: parseCounterMap(
        candidateCards.verdict_counts ?? candidateCards.verdictCounts,
      ),
      evidence_source_scope_counts: parseCounterMap(
        candidateCards.evidence_source_scope_counts ??
          candidateCards.evidenceSourceScopeCounts,
      ),
      deep_research_status_counts: parseCounterMap(
        candidateCards.deep_research_status_counts ??
          candidateCards.deepResearchStatusCounts,
      ),
    },
    evidence: {
      total_count: asNumber(evidence.total_count ?? evidence.totalCount) ?? 0,
      grounding_quality: statusFrom<'grounded' | 'partial' | 'draft_unverified' | 'pending'>(
        evidence.grounding_quality ?? evidence.groundingQuality,
        ['grounded', 'partial', 'draft_unverified', 'pending'] as const,
        'draft_unverified',
      ),
      deep_research_status: statusFrom<'pending' | 'ready' | 'failed'>(
        evidence.deep_research_status ?? evidence.deepResearchStatus,
        ['pending', 'ready', 'failed'] as const,
        'ready',
      ),
      source_channel_counts: parseCounterMap(
        evidence.source_channel_counts ?? evidence.sourceChannelCounts,
      ),
      quality_counts: parseCounterMap(evidence.quality_counts ?? evidence.qualityCounts),
    },
    deep_research: {
      used: asBoolean(deepResearch.used, false),
      pending: asBoolean(deepResearch.pending, false),
      report_available: asBoolean(
        deepResearch.report_available ?? deepResearch.reportAvailable,
        false,
      ),
      report_artifact_id: asNullableString(
        deepResearch.report_artifact_id ?? deepResearch.reportArtifactId,
      ),
      warning: asNullableString(deepResearch.warning),
    },
    warnings: asStringArray(payload.warnings),
  }
}

function normalizeDeepResearchReport(payload: JsonRecord): DeepResearchReportArtifact | null {
  const query = asString(payload.query).trim()
  const summary = asString(payload.summary).trim()
  const synthesis = asString(
    payload.synthesis_full_text ?? payload.synthesisFullText,
  ).trim()
  if (!query && !summary && !synthesis) return null

  const trailsRaw: unknown[] = Array.isArray(payload.search_trails ?? payload.searchTrails)
    ? ((payload.search_trails ?? payload.searchTrails) as unknown[])
    : []
  const sourceInventoryRaw: unknown[] = Array.isArray(
    payload.source_inventory ?? payload.sourceInventory,
  )
    ? ((payload.source_inventory ?? payload.sourceInventory) as unknown[])
    : []
  const discardedSourcesRaw: unknown[] = Array.isArray(
    payload.discarded_sources ?? payload.discardedSources,
  )
    ? ((payload.discarded_sources ?? payload.discardedSources) as unknown[])
    : []
  const discardedAggregatesRaw: unknown[] = Array.isArray(
    payload.discarded_aggregates ?? payload.discardedAggregates,
  )
    ? ((payload.discarded_aggregates ?? payload.discardedAggregates) as unknown[])
    : []
  const searchStatsRaw = (payload.search_stats ?? payload.searchStats) as JsonRecord | undefined

  return {
    query,
    status: asString(payload.status) || 'unknown',
    interaction_id: asNullableString(payload.interaction_id ?? payload.interactionId),
    idempotency_key: asNullableString(payload.idempotency_key ?? payload.idempotencyKey),
    summary,
    synthesis_full_text: synthesis || summary,
    synthesis_generated_by: statusFrom<'upstream' | 'llm_fallback' | 'fallback_rule'>(
      payload.synthesis_generated_by ?? payload.synthesisGeneratedBy,
      ['upstream', 'llm_fallback', 'fallback_rule'] as const,
      'upstream',
    ),
    synthesis_source_count:
      asNumber(payload.synthesis_source_count ?? payload.synthesisSourceCount) ?? 0,
    search_trails: trailsRaw
      .map((raw) => {
        const trail = (raw ?? {}) as JsonRecord
        return {
          stage: statusFrom<'start' | 'poll' | 'sync_fallback'>(
            trail.stage,
            ['start', 'poll', 'sync_fallback'] as const,
            'poll',
          ),
          tool: asString(trail.tool),
          status: asString(trail.status) || 'unknown',
          detail: asNullableString(trail.detail),
        }
      })
      .filter((item) => Boolean(item.tool)),
    historical_trails_available: asBoolean(
      payload.historical_trails_available ?? payload.historicalTrailsAvailable,
      true,
    ),
    source_inventory: sourceInventoryRaw
      .map((raw, idx) => {
        const source = (raw ?? {}) as JsonRecord
        return {
          id: asString(source.id) || `source-${idx + 1}`,
          label: asString(source.label) || `Source ${idx + 1}`,
          display_title: asNullableString(source.display_title ?? source.displayTitle),
          summary: asNullableString(source.summary),
          url: asNullableString(source.url),
          raw_url: asNullableString(source.raw_url ?? source.rawUrl),
          final_url: asNullableString(source.final_url ?? source.finalUrl),
          source_host: asNullableString(source.source_host ?? source.sourceHost),
          kind: statusFrom<HypothesisEvidenceKind>(
            source.kind,
            ['paper', 'dataset', 'experiment', 'note', 'other'] as const,
            'other',
          ),
          source_type: statusFrom<'paper' | 'dataset' | 'other'>(
            source.source_type ?? source.sourceType,
            ['paper', 'dataset', 'other'] as const,
            'other',
          ),
          quality_tier: statusFrom<'primary' | 'secondary' | 'tertiary'>(
            source.quality_tier ?? source.qualityTier,
            ['primary', 'secondary', 'tertiary'] as const,
            'tertiary',
          ),
          traceability_score: asNumber(
            source.traceability_score ?? source.traceabilityScore,
          ),
        }
      })
      .filter((item) => Boolean(item.id)),
    discarded_sources: discardedSourcesRaw
      .map((raw, idx) => {
        const source = (raw ?? {}) as JsonRecord
        return {
          id: asString(source.id) || `discarded-${idx + 1}`,
          label: asString(source.label) || `Discarded ${idx + 1}`,
          display_title: asNullableString(source.display_title ?? source.displayTitle),
          summary: asNullableString(source.summary),
          url: asNullableString(source.url),
          raw_url: asNullableString(source.raw_url ?? source.rawUrl),
          final_url: asNullableString(source.final_url ?? source.finalUrl),
          source_host: asNullableString(source.source_host ?? source.sourceHost),
          kind: statusFrom<HypothesisEvidenceKind>(
            source.kind,
            ['paper', 'dataset', 'experiment', 'note', 'other'] as const,
            'other',
          ),
          source_type: statusFrom<'paper' | 'dataset' | 'other'>(
            source.source_type ?? source.sourceType,
            ['paper', 'dataset', 'other'] as const,
            'other',
          ),
          quality_tier: statusFrom<'primary' | 'secondary' | 'tertiary'>(
            source.quality_tier ?? source.qualityTier,
            ['primary', 'secondary', 'tertiary'] as const,
            'tertiary',
          ),
          traceability_score: asNumber(
            source.traceability_score ?? source.traceabilityScore,
          ),
          reason_code: statusFrom<
            | 'redirect_unresolved'
            | 'duplicate_cluster'
            | 'duplicate_similarity'
            | 'synthetic_summary'
            | 'top_n_trim'
            | 'missing_url_or_label'
            | 'unknown'
          >(
            source.reason_code ?? source.reasonCode,
            [
              'redirect_unresolved',
              'duplicate_cluster',
              'duplicate_similarity',
              'synthetic_summary',
              'top_n_trim',
              'missing_url_or_label',
              'unknown',
            ] as const,
            'unknown',
          ),
          reason_detail: asNullableString(source.reason_detail ?? source.reasonDetail),
          reason_meta: (() => {
            const meta = asRecord(source.reason_meta ?? source.reasonMeta)
            if (!meta) return null
            return {
              attempted: asBoolean(meta.attempted, false),
              resolver: statusFrom<'none' | 'query_param' | 'head' | 'get'>(
                meta.resolver,
                ['none', 'query_param', 'head', 'get'] as const,
                'none',
              ),
              http_status: asNumber(meta.http_status ?? meta.httpStatus),
              error: asNullableString(meta.error),
              skipped_by_budget: asBoolean(meta.skipped_by_budget ?? meta.skippedByBudget, false),
            }
          })(),
        }
      })
      .filter((item) => Boolean(item.id)),
    discarded_aggregates: discardedAggregatesRaw
      .map((raw) => {
        const aggregate = (raw ?? {}) as JsonRecord
        const statsRaw = asRecord(aggregate.stats)
        const stats: Record<string, number> = {}
        if (statsRaw) {
          for (const [key, value] of Object.entries(statsRaw)) {
            const parsed = asNumber(value)
            if (parsed !== null) stats[key] = parsed
          }
        }
        return {
          reason_code: statusFrom<
            | 'redirect_unresolved'
            | 'duplicate_cluster'
            | 'duplicate_similarity'
            | 'synthetic_summary'
            | 'top_n_trim'
            | 'missing_url_or_label'
            | 'unknown'
          >(
            aggregate.reason_code ?? aggregate.reasonCode,
            [
              'redirect_unresolved',
              'duplicate_cluster',
              'duplicate_similarity',
              'synthetic_summary',
              'top_n_trim',
              'missing_url_or_label',
              'unknown',
            ] as const,
            'unknown',
          ),
          count: asNumber(aggregate.count) ?? 0,
          detail: asString(aggregate.detail) || '',
          stats,
        }
      })
      .filter((item) => item.count > 0),
    search_stats: {
      scanned_count:
        asNumber(searchStatsRaw?.scanned_count ?? searchStatsRaw?.scannedCount) ?? 0,
      qualifying_count:
        asNumber(searchStatsRaw?.qualifying_count ?? searchStatsRaw?.qualifyingCount) ?? 0,
      unique_after_dedupe_count:
        asNumber(
          searchStatsRaw?.unique_after_dedupe_count ??
            searchStatsRaw?.uniqueAfterDedupeCount,
        ) ?? 0,
      final_citable_count:
        asNumber(
          searchStatsRaw?.final_citable_count ?? searchStatsRaw?.finalCitableCount,
        ) ?? 0,
      discarded_count:
        asNumber(searchStatsRaw?.discarded_count ?? searchStatsRaw?.discardedCount) ?? 0,
    },
    generated_at:
      asString(payload.generated_at ?? payload.generatedAt).trim() || new Date().toISOString(),
  }
}

function normalizeWorkflowPlan(payload: JsonRecord): WorkflowPlan | null {
  const planRaw = (payload.plan ?? payload) as JsonRecord
  if (!planRaw || typeof planRaw !== 'object') return null
  const id = asString(planRaw.id).trim()
  if (!id) return null
  return {
    id,
    mvp_steps: asStringArray(planRaw.mvp_steps ?? planRaw.mvpSteps),
    full_steps: asStringArray(planRaw.full_steps ?? planRaw.fullSteps),
    falsifier: asString(planRaw.falsifier),
    success_criteria: asStringArray(planRaw.success_criteria ?? planRaw.successCriteria),
    assumptions: asStringArray(planRaw.assumptions),
  }
}

function normalizeResearchPreview(payload: JsonRecord): ResearchPreview | null {
  const previewRaw = (payload.preview ?? payload) as JsonRecord
  if (!previewRaw || typeof previewRaw !== 'object') return null
  const estimatedMinutes = asNumber(previewRaw.estimated_minutes ?? previewRaw.estimatedMinutes)
  const estimatedCredits = asNumber(previewRaw.estimated_credits ?? previewRaw.estimatedCredits)
  if (estimatedMinutes === null || estimatedCredits === null) return null
  return {
    coverage_scope: asStringArray(previewRaw.coverage_scope ?? previewRaw.coverageScope),
    estimated_minutes: estimatedMinutes,
    estimated_credits: estimatedCredits,
    risk_level: statusFrom<'low' | 'medium' | 'high'>(
      previewRaw.risk_level ?? previewRaw.riskLevel,
      ['low', 'medium', 'high'] as const,
      'medium',
    ),
    known_gaps: asStringArray(previewRaw.known_gaps ?? previewRaw.knownGaps),
  }
}

function normalizeValidationReport(payload: JsonRecord): ValidationReport | null {
  const validationRaw = (payload.validation ?? payload) as JsonRecord
  if (!validationRaw || typeof validationRaw !== 'object') return null
  const status = statusFrom<'pass' | 'warn' | 'fail'>(
    validationRaw.status,
    ['pass', 'warn', 'fail'] as const,
    'warn',
  )
  const triageRaw = (validationRaw.triage ?? {}) as JsonRecord
  return {
    status,
    triage: {
      status: statusFrom<'fixable' | 'non_fixable' | 'unknown'>(
        triageRaw.status,
        ['fixable', 'non_fixable', 'unknown'] as const,
        'unknown',
      ),
      reason_codes: asStringArray(
        triageRaw.reason_codes ?? triageRaw.reasonCodes,
      ) as ValidationReport['triage']['reason_codes'],
      user_actions: asStringArray(triageRaw.user_actions ?? triageRaw.userActions),
    },
    checks: Array.isArray(validationRaw.checks)
      ? validationRaw.checks.map((raw, index) => {
          const check = (raw ?? {}) as JsonRecord
          return {
            id: asString(check.id) || `check-${index + 1}`,
            label: asString(check.label) || 'Validation check',
            status: statusFrom<'pass' | 'warn' | 'fail'>(
              check.status,
              ['pass', 'warn', 'fail'] as const,
              'warn',
            ),
            detail: asString(check.detail),
          }
        })
      : [],
    blocked_report: (() => {
      const blocked = validationRaw.blocked_report as JsonRecord | undefined
      if (!blocked || typeof blocked !== 'object') return null
      return {
        why_not: asString(blocked.why_not ?? blocked.whyNot),
        alternatives: asStringArray(blocked.alternatives),
        required_inputs: asStringArray(blocked.required_inputs ?? blocked.requiredInputs),
      }
    })(),
  }
}

export function useHypothesisSession(query: SessionQuery) {
  const router = useRouter()
  const pathname = usePathname()

  const querySnapshot = useMemo(
    () => ({
      sessionId: query.sessionId,
      runId: query.runId,
      datasetId: query.datasetId,
      conceptId: query.conceptId,
      taskId: query.taskId,
      threadId: query.threadId,
    }),
    [query.conceptId, query.datasetId, query.runId, query.sessionId, query.taskId, query.threadId],
  )

  const [session, setSession] = useState<HypothesisSession | null>(null)
  const [messages, setMessages] = useState<HypothesisChatMessage[]>([
    {
      id: 'assistant-bootstrap',
      role: 'assistant',
      content: INITIAL_ASSISTANT_NOTE,
      timestamp: new Date().toISOString(),
    },
  ])

  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [isExploring, setIsExploring] = useState(false)
  const [isSendingChat, setIsSendingChat] = useState(false)
  const [isRunningBatch, setIsRunningBatch] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastBatchRun, setLastBatchRun] = useState<BatchRunSummary | null>(null)
  const [progressFeed, setProgressFeed] = useState<ProgressEvent[]>([])
  const [currentStage, setCurrentStage] = useState<ProgressStage>('clarifying')
  const [artifacts, setArtifacts] = useState<HypothesisArtifactState>(EMPTY_ARTIFACTS)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const currentSessionId = session?.session_id || querySnapshot.sessionId || null
  const pollingRef = useRef<number | null>(null)
  const runStreamRef = useRef<EventSource | null>(null)
  const runStreamTerminalRef = useRef(false)
  const runStreamRecoveringRef = useRef(false)
  const lastDeepResearchParamsRef = useRef<DeepResearchParams | null>(null)
  const lastAssistantMessageRef = useRef<string>('')

  const queryString = useMemo(() => {
    const params = new URLSearchParams()
    if (querySnapshot.sessionId) params.set('sessionId', querySnapshot.sessionId)
    if (querySnapshot.runId) params.set('runId', querySnapshot.runId)
    if (querySnapshot.datasetId) params.set('datasetId', querySnapshot.datasetId)
    if (querySnapshot.conceptId) params.set('conceptId', querySnapshot.conceptId)
    if (querySnapshot.taskId) params.set('taskId', querySnapshot.taskId)
    if (querySnapshot.threadId) params.set('threadId', querySnapshot.threadId)
    return params.toString()
  }, [
    querySnapshot.conceptId,
    querySnapshot.datasetId,
    querySnapshot.runId,
    querySnapshot.sessionId,
    querySnapshot.taskId,
    querySnapshot.threadId,
  ])

  const syncSessionIdToUrl = useCallback(
    (nextSessionId: string | null) => {
      const normalized = (nextSessionId || '').trim()
      if (!normalized || !pathname) return
      if (querySnapshot.sessionId && querySnapshot.sessionId === normalized) return

      const params = new URLSearchParams(window.location.search)
      if (params.get('sessionId') === normalized) return
      params.set('sessionId', normalized)
      const target = params.toString() ? `${pathname}?${params.toString()}` : pathname
      router.replace(target, { scroll: false })
    },
    [pathname, querySnapshot.sessionId, router],
  )

  const syncRunIdToUrl = useCallback(
    (nextRunId: string | null) => {
      if (!pathname) return
      const normalized = (nextRunId || '').trim()
      const params = new URLSearchParams(window.location.search)
      if (!normalized) {
        if (!params.has('runId') && !params.has('run')) return
        params.delete('runId')
        params.delete('run')
        const target = params.toString() ? `${pathname}?${params.toString()}` : pathname
        router.replace(target, { scroll: false })
        return
      }

      if (params.get('runId') === normalized && !params.has('run')) return
      params.set('runId', normalized)
      params.delete('run')
      const target = params.toString() ? `${pathname}?${params.toString()}` : pathname
      router.replace(target, { scroll: false })
    },
    [pathname, router],
  )

  const appendProgress = useCallback(
    (event: Omit<ProgressEvent, 'ts'>) => {
      const nextEvent: ProgressEvent = {
        ...event,
        ts: new Date().toISOString(),
      }

      setCurrentStage(event.stage)
      setProgressFeed((previous) => {
        const last = previous[previous.length - 1]
        if (last && last.stage === nextEvent.stage && last.message === nextEvent.message) {
          return previous
        }
        const next = [...previous, nextEvent]
        return next.length > 24 ? next.slice(next.length - 24) : next
      })
    },
    [],
  )

  const beginClarifying = useCallback(
    (message?: string) => {
      appendProgress({
        stage: 'clarifying',
        message: message || 'Intent updated. Continue clarifying query scope.',
      })
    },
    [appendProgress],
  )

  const resetProgress = useCallback(() => {
    setProgressFeed([])
    setCurrentStage('clarifying')
  }, [])

  const closeRunStream = useCallback(() => {
    if (runStreamRef.current) {
      runStreamRef.current.close()
      runStreamRef.current = null
    }
    runStreamRecoveringRef.current = false
  }, [])

  const appendAssistantMessage = useCallback((content: string) => {
    const normalized = content.trim()
    if (!normalized || lastAssistantMessageRef.current === normalized) return
    lastAssistantMessageRef.current = normalized
    setMessages((previous) => [
      ...previous,
      {
        id: `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        role: 'assistant',
        content: normalized,
        timestamp: new Date().toISOString(),
      },
    ])
  }, [])

  const applyArtifact = useCallback((artifact: HypothesisArtifactEnvelope) => {
    const payload = (artifact.payload ?? {}) as JsonRecord

    setArtifacts((previous) => {
      const next: HypothesisArtifactState = { ...previous }

      switch (artifact.kind) {
        case 'hypothesis_canvas': {
          next.canvas = payload as unknown as HypothesisCanvas
          break
        }
        case 'evidence_pack': {
          const evidenceRaw = Array.isArray(payload.evidence) ? payload.evidence : []
          next.evidence = evidenceRaw.map(normalizeEvidence)
          next.evidenceMeta = normalizeEvidenceMeta(payload)
          break
        }
        case 'deep_research_report': {
          next.deepResearchReport = normalizeDeepResearchReport(payload)
          break
        }
        case 'hot_load_trajectory': {
          next.hotLoadTrajectory = normalizeHotLoadTrajectory(payload)
          break
        }
        case 'kg_compare': {
          next.kgCompare = normalizeKgCompare(payload)
          break
        }
        case 'candidate_cards': {
          const itemsRaw = Array.isArray(payload.items)
            ? payload.items
            : Array.isArray(payload.candidates)
              ? payload.candidates
              : []
          next.candidates = itemsRaw.map((raw, index) => {
            const item = (raw ?? {}) as JsonRecord
            return {
              id: asString(item.id) || `candidate-${index + 1}`,
              title: asString(item.title) || `Candidate ${index + 1}`,
              summary: asString(item.summary),
              source: statusFrom<'session' | 'workflow'>(
                item.source,
                ['session', 'workflow'] as const,
                'workflow',
              ),
              grounding_status: statusFrom<CandidateGroundingStatus>(
                item.grounding_status ?? item.groundingStatus,
                ['grounded', 'weak_grounded', 'draft_unverified'] as const,
                'draft_unverified',
              ),
              confidence: asNumber(item.confidence),
              pattern_id: asNullableString(item.pattern_id ?? item.patternId),
              pattern_label: asNullableString(item.pattern_label ?? item.patternLabel),
              claim: asNullableString(item.claim ?? item.hypothesis),
              evidence_anchors: Array.isArray(item.evidence_anchors ?? item.evidenceAnchors)
                ? ((item.evidence_anchors ?? item.evidenceAnchors) as unknown[])
                    .map((anchorRaw) => {
                      const anchor = (anchorRaw ?? {}) as JsonRecord
                      const evidenceId = asString(
                        anchor.evidence_id ?? anchor.evidenceId,
                      ).trim()
                      if (!evidenceId) return null
                      return {
                        evidence_id: evidenceId,
                        label: asString(anchor.label) || evidenceId,
                        kind: statusFrom<HypothesisEvidenceKind>(
                          anchor.kind,
                          ['paper', 'dataset', 'experiment', 'note', 'other'] as const,
                          'other',
                        ),
                        reason: asNullableString(anchor.reason),
                        source_channel: statusFrom<
                          NonNullable<HypothesisEvidenceItem['source_channel']>
                        >(
                          anchor.source_channel ?? anchor.sourceChannel,
                        [
                          'graph',
                          'deep_research_live',
                          'deep_research_pending',
                          'file_search_live',
                          'workflow_fallback',
                          'other',
                          ] as const,
                          'other',
                        ),
                        confidence: asNumber(anchor.confidence),
                        overlap_score: asNumber(anchor.overlap_score ?? anchor.overlapScore),
                        quality_tier: statusFrom<'primary' | 'secondary' | 'tertiary'>(
                          anchor.quality_tier ?? anchor.qualityTier,
                          ['primary', 'secondary', 'tertiary'] as const,
                          'tertiary',
                        ),
                        traceability_score: asNumber(
                          anchor.traceability_score ?? anchor.traceabilityScore,
                        ),
                      } as EvidenceAnchor
                    })
                    .filter((anchor): anchor is EvidenceAnchor => Boolean(anchor))
                : [],
              semantic_alignment: asNumber(
                item.semantic_alignment ?? item.semanticAlignment,
              ),
              anchor_quality:
                item.anchor_quality && typeof item.anchor_quality === 'object'
                  ? {
                      primary: asNumber((item.anchor_quality as JsonRecord).primary) ?? 0,
                      secondary: asNumber((item.anchor_quality as JsonRecord).secondary) ?? 0,
                      tertiary: asNumber((item.anchor_quality as JsonRecord).tertiary) ?? 0,
                    }
                  : item.anchorQuality && typeof item.anchorQuality === 'object'
                    ? {
                        primary: asNumber((item.anchorQuality as JsonRecord).primary) ?? 0,
                        secondary: asNumber((item.anchorQuality as JsonRecord).secondary) ?? 0,
                        tertiary: asNumber((item.anchorQuality as JsonRecord).tertiary) ?? 0,
                      }
                    : null,
              anchor_dim: asNullableString(item.anchor_dim ?? item.anchorDim),
              anchor_source: statusFrom<'kg' | 'evidence' | 'kg_compare' | 'hybrid'>(
                item.anchor_source ?? item.anchorSource,
                ['kg', 'evidence', 'kg_compare', 'hybrid'] as const,
                'hybrid',
              ),
              anchor_evidence_ids: asStringArray(
                item.anchor_evidence_ids ?? item.anchorEvidenceIds,
              ),
              diversity_retry_count:
                asNumber(item.diversity_retry_count ?? item.diversityRetryCount) ?? 0,
              fallback_reasons: asStringArray(item.fallback_reasons ?? item.fallbackReasons),
              share_allowed: asBoolean(item.share_allowed ?? item.shareAllowed, false),
              independent_variable: asNullableString(
                item.independent_variable ?? item.independentVariable,
              ),
              dependent_variable: asNullableString(
                item.dependent_variable ?? item.dependentVariable,
              ),
              expected_signal: asNullableString(item.expected_signal ?? item.expectedSignal),
              likely_data_source: asNullableString(
                item.likely_data_source ?? item.likelyDataSource,
              ),
              novelty_gap: asNullableString(item.novelty_gap ?? item.noveltyGap),
              risk_note: asNullableString(item.risk_note ?? item.riskNote),
              minimal_discriminating_test: asNullableString(
                item.minimal_discriminating_test ?? item.minimalDiscriminatingTest,
              ),
              falsifier_hint: asNullableString(
                item.falsifier_hint ?? item.falsifierHint,
              ),
              taste_axis: asNullableString(item.taste_axis ?? item.tasteAxis),
            }
          })
          next.candidateSummary = normalizeCandidateSummary(payload)
          next.candidateDiagnostics = normalizeCandidateDiagnostics(payload)
          next.candidateTrace = normalizeCandidateTrace(payload)
          break
        }
        case 'workflow_plan': {
          next.preview = normalizeResearchPreview(payload)
          next.plan = normalizeWorkflowPlan(payload)
          break
        }
        case 'validation_report': {
          next.validation = normalizeValidationReport(payload)
          break
        }
      }

      return next
    })
  }, [])

  const reconcileRunFromSnapshot = useCallback(
    async (runId: string): Promise<'completed' | 'failed' | 'running' | 'missing'> => {
      const response = await fetch(`/api/hypothesis/run/${encodeURIComponent(runId)}`, {
        cache: 'no-store',
      }).catch(() => null)
      if (!response || !response.ok) return 'missing'

      const payload = (await parseJsonResponse(response)) as JsonRecord | null
      const runPayload = (payload?.run && typeof payload.run === 'object'
        ? (payload.run as JsonRecord)
        : payload) as JsonRecord | null
      if (!runPayload || typeof runPayload !== 'object') return 'missing'

      const state = statusFrom<HypothesisRunState>(
        runPayload.state,
        ['clarifying', 'running', 'completed', 'failed'] as const,
        'running',
      )

      const artifactsRaw = Array.isArray(runPayload.artifacts) ? runPayload.artifacts : []
      for (const rawArtifact of artifactsRaw) {
        const artifact = (rawArtifact ?? {}) as JsonRecord
        const kind = asString(artifact.kind) as HypothesisArtifactEnvelope['kind']
        if (!HYPOTHESIS_ARTIFACT_KINDS.includes(kind)) continue
        const payloadRecord =
          artifact.payload && typeof artifact.payload === 'object' ? (artifact.payload as JsonRecord) : {}

        applyArtifact({
          id: asString(artifact.id) || `${kind}-${Date.now().toString(36)}`,
          kind,
          payload: payloadRecord,
          updated_at:
            asNullableString(artifact.updated_at ?? artifact.updatedAt) || new Date().toISOString(),
        })
      }

      setCurrentStage(toProgressStage(state))

      if (state === 'completed') {
        setError(null)
        appendProgress({
          stage: 'completed',
          message: 'Run completed. Recovered final state after stream reconnect.',
        })
        setIsExploring(false)
        runStreamTerminalRef.current = true
        return 'completed'
      }

      if (state === 'failed') {
        const failureMessage =
          asNullableString(runPayload.error_message ?? runPayload.errorMessage) ||
          'Hypothesis run failed.'
        setError(failureMessage)
        appendProgress({
          stage: 'failed',
          message: failureMessage,
        })
        setIsExploring(false)
        runStreamTerminalRef.current = true
        return 'failed'
      }

      return 'running'
    },
    [appendProgress, applyArtifact],
  )

  const startRunStream = useCallback(
    (runId: string) => {
      closeRunStream()
      runStreamTerminalRef.current = false
      runStreamRecoveringRef.current = false
      setActiveRunId(runId)
      setIsExploring(true)

      const source = new EventSource(`/api/hypothesis/run/${encodeURIComponent(runId)}/stream`)
      runStreamRef.current = source

      const parseEvent = (event: Event): HypothesisRunEvent | null => {
        const message = event as MessageEvent<string>
        if (!message.data) return null
        try {
          return JSON.parse(message.data) as HypothesisRunEvent
        } catch {
          return null
        }
      }

      source.addEventListener('snapshot', (event: Event) => {
        const message = event as MessageEvent<string>
        if (!message.data) return
        try {
          const snapshot = JSON.parse(message.data) as {
            state?: HypothesisRunState
            run_id?: string
          }
          if (snapshot.state) {
            setCurrentStage(toProgressStage(snapshot.state))
          }
          if (snapshot.run_id) {
            setActiveRunId(snapshot.run_id)
          }
        } catch {
          // Ignore malformed snapshot events.
        }
      })

      source.addEventListener('run_state', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'run_state') return
        const stage = toProgressStage(parsed.payload.state)
        appendProgress({
          stage,
          message: parsed.payload.message || `Run state: ${parsed.payload.state}`,
        })
      })

      source.addEventListener('assistant_message', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'assistant_message') return
        appendAssistantMessage(parsed.payload.content)
      })

      source.addEventListener('stage', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'stage') return
        const stage: ProgressStage =
          parsed.payload.stage_name === 'clarify' ? 'clarifying' : 'running'
        const metrics =
          typeof parsed.payload.progress === 'number'
            ? { progress: Number((parsed.payload.progress * 100).toFixed(0)) }
            : undefined
        appendProgress({
          stage,
          message: parsed.payload.message,
          metrics,
        })
      })

      source.addEventListener('metric', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'metric') return
        appendProgress({
          stage: 'running',
          message: `Metric: ${parsed.payload.name}`,
          metrics: {
            [parsed.payload.name]: parsed.payload.value,
          },
        })
      })

      source.addEventListener('artifact_upsert', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'artifact_upsert') return
        applyArtifact(parsed.payload.artifact)
      })

      source.addEventListener('error', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'error') return
        setError(parsed.payload.message)
        appendProgress({
          stage: 'failed',
          message: parsed.payload.message,
        })
      })

      source.addEventListener('done', (event: Event) => {
        const parsed = parseEvent(event)
        if (!parsed || parsed.type !== 'done') return
        const finalStage = toProgressStage(parsed.payload.final_state)
        appendProgress({
          stage: finalStage,
          message: parsed.payload.summary,
        })
        runStreamTerminalRef.current = true
        runStreamRecoveringRef.current = false
        setIsExploring(false)
        closeRunStream()
      })

      source.onerror = () => {
        if (runStreamTerminalRef.current) {
          closeRunStream()
          return
        }
        if (runStreamRecoveringRef.current) return
        runStreamRecoveringRef.current = true

        appendProgress({
          stage: 'running',
          message: 'Live stream disconnected. Switching to snapshot sync...',
        })

        void (async () => {
          try {
            for (let attempt = 0; attempt < STREAM_RECOVERY_MAX_ATTEMPTS; attempt += 1) {
              const recovered = await reconcileRunFromSnapshot(runId)
              if (recovered === 'completed' || recovered === 'failed') {
                closeRunStream()
                return
              }
              await new Promise((resolve) => setTimeout(resolve, STREAM_RECOVERY_POLL_MS))
            }

            setIsExploring(false)
            setError('Live stream unavailable. Run is still processing; click Refresh to sync.')
            appendProgress({
              stage: 'running',
              message:
                'Live stream unavailable. Background run may still be active; refresh to sync latest artifacts.',
            })
            closeRunStream()
          } finally {
            runStreamRecoveringRef.current = false
          }
        })()
      }
    },
    [
      appendAssistantMessage,
      appendProgress,
      applyArtifact,
      closeRunStream,
      reconcileRunFromSnapshot,
    ],
  )

  const refreshSession = useCallback(async () => {
    setIsLoadingSession(true)
    setError(null)

    try {
      const response = await fetch(`/api/hypothesis/session${queryString ? `?${queryString}` : ''}`, {
        method: 'GET',
        cache: 'no-store',
      })

      const payload = await parseJsonResponse(response)
      if (!response.ok) {
        const message =
          asString((payload as JsonRecord | null)?.message) ||
          asString((payload as JsonRecord | null)?.error) ||
          `Failed to load session (${response.status})`
        throw new Error(message)
      }

      const normalized = normalizeSession(payload, querySnapshot)
      setSession(normalized)
      syncSessionIdToUrl(normalized.session_id)

      const runsRaw = (payload as JsonRecord | null)?.runs
      const latestRunId = extractLatestRunId(runsRaw)
      const requestedRunId = querySnapshot.runId?.trim() || null
      const targetRunId = requestedRunId || latestRunId

      if (targetRunId) {
        if (activeRunId !== targetRunId) {
          setActiveRunId(targetRunId)
        }
        syncRunIdToUrl(targetRunId)
        void reconcileRunFromSnapshot(targetRunId)
      } else {
        setActiveRunId(null)
        syncRunIdToUrl(null)
        setArtifacts(EMPTY_ARTIFACTS)
      }

      setMessages((previous) => {
        const restored = (normalized.messages || []).filter((message) => message.content.trim())
        if (!restored.length) {
          return [
            {
              id: 'assistant-bootstrap',
              role: 'assistant',
              content: INITIAL_ASSISTANT_NOTE,
              timestamp: new Date().toISOString(),
            },
          ]
        }
        return restored
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load hypothesis session.'
      setError(message)
      setSession((previous) =>
        previous || {
          session_id: querySnapshot.sessionId || `session-${Math.random().toString(36).slice(2, 10)}`,
          context: {
            session_id: querySnapshot.sessionId || null,
            dataset_id: querySnapshot.datasetId || null,
            concept_id: querySnapshot.conceptId || null,
            task_id: querySnapshot.taskId || null,
            thread_id: querySnapshot.threadId || null,
          },
          open_questions: [],
          candidates: [],
          messages: [],
          selected_hypothesis_id: null,
          leaderboard_url: null,
          updated_at: null,
        },
      )
    } finally {
      setIsLoadingSession(false)
    }
  }, [activeRunId, querySnapshot, queryString, reconcileRunFromSnapshot, syncRunIdToUrl, syncSessionIdToUrl])

  useEffect(() => {
    void refreshSession()
  }, [refreshSession])

  const lastSessionIdRef = useRef<string | null>(querySnapshot.sessionId?.trim() || null)
  useEffect(() => {
    const currentSessionId = querySnapshot.sessionId?.trim() || null
    const previousSessionId = lastSessionIdRef.current
    if (previousSessionId === currentSessionId) return

    lastSessionIdRef.current = currentSessionId
    closeRunStream()
    setActiveRunId(querySnapshot.runId?.trim() || null)
    setArtifacts(EMPTY_ARTIFACTS)
    setProgressFeed([])
    setCurrentStage('clarifying')
    setMessages([
      {
        id: 'assistant-bootstrap',
        role: 'assistant',
        content: INITIAL_ASSISTANT_NOTE,
        timestamp: new Date().toISOString(),
      },
    ])
    lastAssistantMessageRef.current = ''
  }, [closeRunStream, querySnapshot.runId, querySnapshot.sessionId])

  useEffect(() => {
    const runId = querySnapshot.runId?.trim()
    if (!runId) return

    setActiveRunId(runId)
    void reconcileRunFromSnapshot(runId)
  }, [querySnapshot.runId, reconcileRunFromSnapshot])

  useEffect(() => {
    return () => {
      closeRunStream()
    }
  }, [closeRunStream])

  const exploreIdeas = useCallback(
    async (params: ExploreParams = {}) => {
      if (!currentSessionId) {
        throw new Error('Session not ready. Try again in a moment.')
      }

      setIsExploring(true)
      setError(null)

      try {
        const response = await fetch('/api/hypothesis/explore', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            session_id: currentSessionId,
            open_question_id: params.openQuestionId,
            n_candidates: params.nCandidates,
            constraints: params.constraints,
          }),
        })

        const payload = (await parseJsonResponse(response)) as JsonRecord | null

        if (!response.ok) {
          const message =
            asString(payload?.message) || asString(payload?.error) || 'Explore request failed.'
          throw new Error(message)
        }

        const incomingRaw = Array.isArray(payload?.candidates)
          ? payload?.candidates
          : Array.isArray(payload?.items)
            ? payload?.items
            : []
        const incoming = incomingRaw.map(normalizeCandidate)

        if (payload?.session && typeof payload.session === 'object') {
          setSession(normalizeSession(payload.session, querySnapshot))
        } else {
          setSession((previous) => {
            if (!previous) return previous
            return {
              ...previous,
              candidates: mergeCandidates(previous.candidates, incoming),
              updated_at: new Date().toISOString(),
            }
          })
        }

        return incoming
      } finally {
        setIsExploring(false)
      }
    },
    [currentSessionId, querySnapshot],
  )

  const startDeepResearch = useCallback(
    async (params: DeepResearchParams = {}) => {
      const { queryTerm, finalize = true, ...exploreParams } = params
      lastDeepResearchParamsRef.current = params

      appendProgress({
        stage: 'running',
        message: queryTerm
          ? `Querying BR-KG for "${queryTerm}"...`
          : 'Querying BR-KG...',
      })

      try {
        const generated = await exploreIdeas({
          openQuestionId: exploreParams.openQuestionId,
          nCandidates: exploreParams.nCandidates,
          constraints: exploreParams.constraints,
        })

        appendProgress({
          stage: 'running',
          message: 'Synthesizing evidence and ranking candidates...',
          metrics: {
            candidate_count: generated.length,
          },
        })

        if (finalize) {
          appendProgress({
            stage: 'completed',
            message: 'Deep research completed.',
            metrics: {
              candidate_count: generated.length,
            },
          })
        }

        return generated
      } catch (err) {
        appendProgress({
          stage: 'failed',
          message: err instanceof Error ? err.message : 'Deep research failed.',
        })
        throw err
      }
    },
    [appendProgress, exploreIdeas],
  )

  const retryLastRun = useCallback(async () => {
    const previous = lastDeepResearchParamsRef.current
    if (!previous) {
      throw new Error('No previous deep research run to retry.')
    }
    return startDeepResearch(previous)
  }, [startDeepResearch])

  const sendChat = useCallback(
    async ({ message, selectedHypothesisId }: SendChatParams) => {
      const trimmed = message.trim()
      if (!trimmed) return null
      if (!currentSessionId) {
        throw new Error('Session not ready. Try again in a moment.')
      }

      const now = new Date().toISOString()
      setMessages((previous) => [
        ...previous,
        {
          id: `user-${Date.now()}`,
          role: 'user',
          content: trimmed,
          timestamp: now,
        },
      ])

      setIsSendingChat(true)
      setError(null)

      try {
        const response = await fetch('/api/hypothesis/run', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            session_id: currentSessionId,
            message: trimmed,
            selected_hypothesis_id: selectedHypothesisId,
            dataset_id: session?.context.dataset_id ?? querySnapshot.datasetId ?? null,
            concept_id: session?.context.concept_id ?? querySnapshot.conceptId ?? null,
            task_id: session?.context.task_id ?? querySnapshot.taskId ?? null,
            thread_id: session?.context.thread_id ?? querySnapshot.threadId ?? null,
          }),
        })

        const payload = (await parseJsonResponse(response)) as JsonRecord | null

        if (!response.ok) {
          const messageText =
            asString(payload?.message) || asString(payload?.error) || 'Run request failed.'
          throw new Error(messageText)
        }

        const runStart = normalizeRunStartResponse(payload)
        if (!runStart) {
          throw new Error('Run request did not return a valid run_id/session_id pair.')
        }

        if (runStart.state === 'running') {
          setArtifacts(EMPTY_ARTIFACTS)
          setProgressFeed([])
        }
        setCurrentStage(toProgressStage(runStart.state))
        lastAssistantMessageRef.current = ''
        startRunStream(runStart.run_id)

        return runStart.assistant_message || null
      } finally {
        setIsSendingChat(false)
      }
    },
    [currentSessionId, querySnapshot, session, startRunStream],
  )

  const runBatch = useCallback(
    async ({ hypothesisIds, budget }: RunBatchParams) => {
      if (!currentSessionId) {
        throw new Error('Session not ready. Try again in a moment.')
      }
      if (!hypothesisIds.length) {
        throw new Error('Please select at least one hypothesis to run.')
      }

      setIsRunningBatch(true)
      setError(null)

      try {
        const response = await fetch('/api/hypothesis/run-batch', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            session_id: currentSessionId,
            hypothesis_ids: hypothesisIds,
            budget,
          }),
        })

        const payload = (await parseJsonResponse(response)) as JsonRecord | null

        if (!response.ok) {
          const message = asString(payload?.message) || asString(payload?.error) || 'Run batch failed.'
          throw new Error(message)
        }

        const run = normalizeBatchRun(payload?.run ?? payload)
        setLastBatchRun(run)

        if (payload?.session && typeof payload.session === 'object') {
          setSession(normalizeSession(payload.session, querySnapshot))
        }

        return run
      } finally {
        setIsRunningBatch(false)
      }
    },
    [currentSessionId, querySnapshot],
  )

  useEffect(() => {
    const runId = lastBatchRun?.run_id
    const status = lastBatchRun?.status

    if (!runId || !status || TERMINAL_RUN_STATUSES.includes(status)) {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      return
    }

    const poll = async () => {
      try {
        const response = await fetch(`/api/hypothesis/run/${encodeURIComponent(runId)}`, {
          cache: 'no-store',
        })
        const payload = (await parseJsonResponse(response)) as JsonRecord | null
        if (!response.ok) return

        const run = normalizeBatchRun(payload?.run ?? payload)
        if (run.run_id) {
          setLastBatchRun(run)
        }

        if (payload?.session && typeof payload.session === 'object') {
          setSession(normalizeSession(payload.session, querySnapshot))
        }
      } catch {
        // Ignore polling failures and continue with next interval.
      }
    }

    void poll()
    pollingRef.current = window.setInterval(poll, 4_000)

    return () => {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [lastBatchRun, querySnapshot])

  return {
    session,
    messages,
    error,
    lastBatchRun,
    activeRunId,
    artifacts,
    progressFeed,
    currentStage,
    isLoadingSession,
    isExploring,
    isSendingChat,
    isRunningBatch,
    appendProgress,
    beginClarifying,
    resetProgress,
    refreshSession,
    exploreIdeas,
    startDeepResearch,
    retryLastRun,
    sendChat,
    runBatch,
  }
}
