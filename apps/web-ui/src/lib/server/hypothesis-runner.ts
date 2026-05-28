import {
  buildGroundedDirectionCandidates,
  buildGroundedDirectionCandidatesWithTrace,
  buildResearchPreview,
  buildSuggestedCanvas,
  buildWorkflowPlan,
  evaluateWorkflowPlan,
} from '@/lib/hypothesis-workflow'
import {
  getOrCreateLocalHypothesisSessionPersisted,
} from '@/lib/server/hypothesis-local-store'
import {
  DEEP_RESEARCH_ERROR_CODES,
  type DeepResearchDegenerateEvidenceDiagnostics,
  type DeepResearchReportPayload,
  type HypothesisCandidateCardPayload,
  type HypothesisResolvedAnchorBundleItem,
  type DeepResearchRuntimeOptions,
  type KgCompareRuntimeOptions,
  getDeepResearchErrorCode,
  runDeepResearch,
  runKgHypothesisCandidateCards,
  runKgCompare,
} from '@/lib/server/hypothesis-research-adapter'
import {
  emitMetric,
  emitRunState,
  emitStage,
  markRunCompleted,
  markRunFailed,
  upsertArtifact,
} from '@/lib/server/hypothesis-run-store'
import type {
  DirectionCandidate,
  HypothesisEvidenceItem,
  HypothesisIntentSummary,
} from '@/types/hypothesis'

const WAIT_MS = 220
const DEFAULT_DEEP_RESEARCH_UI_WAIT_SEC = 300
const DEFAULT_DEEP_RESEARCH_BACKGROUND_CAP_SEC = 21_600
const DEFAULT_KG_COMPARE_TIMEOUT_SEC = 90
const DEFAULT_KG_PROMPT_TOPK = 6
const DEFAULT_KG_PROMPT_MAX_CHARS = 1200
const DEFAULT_CANDIDATE_COUNT = 10
const MAX_CANDIDATE_COUNT = 16
const NO_SEED_ENTITIES_PATTERN = /\b(no seed entities found|sparse seed anchors)\b/i

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function normalizeNonNegativeInt(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  const normalized = Math.trunc(value)
  return normalized < 0 ? fallback : normalized
}

function normalizePositiveInt(value: unknown, fallback: number): number {
  const normalized = normalizeNonNegativeInt(value, fallback)
  return normalized > 0 ? normalized : fallback
}

function formatDuration(seconds: number): string {
  if (seconds >= 60) {
    const mins = Math.trunc(seconds / 60)
    return `${mins} minute${mins === 1 ? '' : 's'}`
  }
  return `${seconds} second${seconds === 1 ? '' : 's'}`
}

function clampText(value: string, max: number): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (trimmed.length <= max) return trimmed
  return `${trimmed.slice(0, Math.max(0, max - 3)).trim()}...`
}

function resolveCandidateCount(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(1, Math.min(MAX_CANDIDATE_COUNT, Math.trunc(value)))
  }
  return DEFAULT_CANDIDATE_COUNT
}

function buildDeepResearchQuery(args: {
  term: string
  goal?: string | null
  modality?: string | null
  population?: string | null
  kgPriorsPrompt?: string | null
}): string {
  const parts = [
    args.term.trim(),
    args.goal?.replace(/_/g, ' ') || null,
    args.modality?.replace(/_/g, ' ') || null,
    args.population || null,
  ].filter((value): value is string => Boolean(value && value.trim()))

  const baseQuery = `Recent research evidence for ${parts.join(' | ')}`
  const kgPriorsPrompt = normalizeSummaryValue(args.kgPriorsPrompt, '')
  if (!kgPriorsPrompt) {
    return baseQuery
  }
  return [
    baseQuery,
    '',
    'BR-KG priors from deterministic graph traversal (validate/refute with citeable sources):',
    kgPriorsPrompt,
    '',
    'Prefer peer-reviewed papers, preprints, and datasets. Return citeable URLs.',
  ].join('\n')
}

function defaultEvidence(term: string): HypothesisEvidenceItem[] {
  const stamp = Date.now().toString(36)
  return [
    {
      id: `ev-${stamp}-fallback-1`,
      label: 'Workflow fallback: draft-only evidence scaffold',
      kind: 'note',
      summary: `No verified external evidence was available yet for "${term}". Candidate generation remains draft until live sources resolve.`,
      source_channel: 'workflow_fallback',
    },
    {
      id: `ev-${stamp}-fallback-2`,
      label: 'Workflow fallback: no citeable artifacts',
      kind: 'note',
      summary:
        'No papers/datasets are injected in fallback mode. Re-run with narrower scope to collect citeable evidence anchors.',
      source_channel: 'workflow_fallback',
    },
  ]
}

function pendingDeepResearchEvidence(term: string): HypothesisEvidenceItem[] {
  const stamp = Date.now().toString(36)
  return [
    {
      id: `ev-${stamp}-pending-1`,
      label: 'Deep research in progress',
      kind: 'note',
      summary: `Live evidence retrieval for "${term}" is still running. This run finalized intermediate artifacts and will update evidence when deep research completes.`,
      source_channel: 'deep_research_pending',
    },
  ]
}

function normalizeSummaryValue(value?: string | null, fallback = ''): string {
  const normalized = typeof value === 'string' ? value.trim() : ''
  return normalized || fallback
}

type EvidencePackPayload = {
  summary: string
  evidence: HypothesisEvidenceItem[]
  is_fallback: boolean
  grounding_quality: 'grounded' | 'partial' | 'draft_unverified' | 'pending'
  deep_research_status: 'pending' | 'ready' | 'failed'
  degenerate_evidence: boolean
  degenerate_reason: string | null
  dedupe_stats: {
    before: number
    after: number
    collapsed_groups: number
  }
  pending_message?: string | null
  kg_injected: boolean
  kg_injection_summary: string | null
  kg_injection_truncated: boolean
  source_stats: {
    total: number
    by_kind: Record<string, number>
    by_channel: Record<string, number>
    by_quality: Record<string, number>
  }
  deep_research_report_available: boolean
  deep_research_report_artifact_id: string | null
  research_coverage_stats: {
    scanned_sources: number
    qualifying_sources: number
    unique_after_dedupe: number
    final_citable_sources: number
    discarded_sources: number
  }
  warnings: string[]
}

type KgComparePayload = {
  prior_art_match: string[]
  novelty_gap: string[]
  feasibility_constraints: string[]
  novelty_taste: {
    structural_leverage: string[]
    contradiction_motifs: string[]
    ood_hypotheses: string[]
    topology_shifts: string[]
  }
  concepts: string[]
  warnings: string[]
  multihop_attempts: number
}

type KgPromptInjection = {
  injected: boolean
  prompt: string | null
  summary: string | null
  truncated: boolean
  tokensEstimate: number
}

type CandidateCardsArtifactPayload = {
  items: Array<Record<string, unknown>>
  summary: {
    grounded_count: number
    weak_count: number
    draft_count: number
    total_count: number
  }
  diagnostics: {
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
    ephemeral_weighted_subgraph_available: boolean
    ephemeral_weighted_subgraph_node_count: number
    ephemeral_weighted_subgraph_edge_count: number
    ephemeral_weighted_subgraph_card_count: number
    reasons: string[]
  }
  evidence_trace?: {
    facts: Array<{
      id: string
      evidence_id: string
      text: string
      relevance: number
      quality_tier: string
      source_channel: string
    }>
    clusters: Array<{
      id: string
      fact_ids: string[]
      evidence_ids: string[]
      key_terms: string[]
      score: number
    }>
  }
}

type HotLoadTrajectoryArtifactPayload = {
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
    grounding_quality: EvidencePackPayload['grounding_quality']
    deep_research_status: EvidencePackPayload['deep_research_status']
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
  ephemeral_weighted_subgraph: {
    available: boolean
    node_count: number
    edge_count: number
    card_subgraph_count: number
  }
  warnings: string[]
}

function normalizeEvidenceChannels(
  evidence: HypothesisEvidenceItem[],
  fallbackChannel: HypothesisEvidenceItem['source_channel'],
): HypothesisEvidenceItem[] {
  const freshness = new Date().toISOString()
  return evidence.map((item) => ({
    ...item,
    source_channel: item.source_channel || fallbackChannel || 'other',
    freshness_ts: item.freshness_ts || freshness,
  }))
}

function estimatePromptTokens(text: string): number {
  const normalized = text.trim()
  if (!normalized) return 0
  return Math.max(1, Math.ceil(normalized.length / 4))
}

function resolveKgTimeoutMs(value: unknown): number | null {
  if (value === null) return null
  if (typeof value === 'number' && Number.isFinite(value)) {
    const seconds = Math.trunc(value)
    return seconds > 0 ? seconds * 1000 : null
  }
  return DEFAULT_KG_COMPARE_TIMEOUT_SEC * 1000
}

async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number | null,
  timeoutMessage: string,
): Promise<T> {
  if (!timeoutMs || timeoutMs <= 0) {
    return operation
  }
  let timeoutId: ReturnType<typeof setTimeout> | null = null
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(timeoutMessage))
    }, timeoutMs)
  })
  try {
    return await Promise.race([operation, timeoutPromise])
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
  }
}

function buildKgPromptInjection(args: {
  term: string
  kgCompare: KgComparePayload
  topK: number
  maxChars: number
}): KgPromptInjection {
  const topK = Math.max(1, Math.trunc(args.topK || DEFAULT_KG_PROMPT_TOPK))
  const maxChars = Math.max(256, Math.trunc(args.maxChars || DEFAULT_KG_PROMPT_MAX_CHARS))
  const rawLines: string[] = []

  if (args.kgCompare.concepts.length) {
    rawLines.push(`Mapped concepts: ${args.kgCompare.concepts.slice(0, 8).join(', ')}`)
  }
  rawLines.push(
    ...args.kgCompare.prior_art_match.map((line) => `Prior art: ${clampText(line, 220)}`),
  )
  rawLines.push(...args.kgCompare.novelty_gap.map((line) => `Novelty gap: ${clampText(line, 220)}`))
  rawLines.push(
    ...args.kgCompare.feasibility_constraints.map(
      (line) => `Feasibility: ${clampText(line, 220)}`,
    ),
  )
  rawLines.push(
    ...args.kgCompare.novelty_taste.structural_leverage.map(
      (line) => `Structural leverage: ${clampText(line, 220)}`,
    ),
  )
  rawLines.push(
    ...args.kgCompare.novelty_taste.contradiction_motifs.map(
      (line) => `Contradiction motif: ${clampText(line, 220)}`,
    ),
  )
  rawLines.push(
    ...args.kgCompare.novelty_taste.ood_hypotheses.map(
      (line) => `OOD hypothesis: ${clampText(line, 220)}`,
    ),
  )
  rawLines.push(
    ...args.kgCompare.novelty_taste.topology_shifts.map(
      (line) => `Topology shift: ${clampText(line, 220)}`,
    ),
  )
  rawLines.push(...args.kgCompare.warnings.map((line) => `Warning: ${clampText(line, 180)}`))

  const deduped: string[] = []
  const seen = new Set<string>()
  for (const line of rawLines) {
    const normalized = normalizeSummaryValue(line, '')
    if (!normalized) continue
    const key = normalized.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(normalized)
    if (deduped.length >= topK) break
  }

  if (!deduped.length) {
    return {
      injected: false,
      prompt: null,
      summary: null,
      truncated: false,
      tokensEstimate: 0,
    }
  }

  const header = `Term: ${args.term}`
  let prompt = [header, ...deduped.map((line) => `- ${line}`)].join('\n')
  const truncated = prompt.length > maxChars
  if (truncated) {
    prompt = clampText(prompt, maxChars)
  }

  return {
    injected: true,
    prompt,
    summary: clampText(deduped.slice(0, 2).join(' | '), 260) || null,
    truncated,
    tokensEstimate: estimatePromptTokens(prompt),
  }
}

function buildEvidencePack(args: {
  summary: string
  evidence: HypothesisEvidenceItem[]
  isFallback: boolean
  deepResearchStatus: EvidencePackPayload['deep_research_status']
  degenerateEvidence?: DeepResearchDegenerateEvidenceDiagnostics | null
  deepResearchReport?: DeepResearchReportPayload | null
  reportArtifactId?: string | null
  pendingMessage?: string | null
  kgInjection?: KgPromptInjection
  warnings?: string[]
}): EvidencePackPayload {
  const byKind: Record<string, number> = {}
  const byChannel: Record<string, number> = {}
  const byQuality: Record<string, number> = {}
  for (const item of args.evidence) {
    byKind[item.kind] = (byKind[item.kind] || 0) + 1
    const channel = item.source_channel || 'other'
    byChannel[channel] = (byChannel[channel] || 0) + 1
    const quality = item.quality_tier || 'tertiary'
    byQuality[quality] = (byQuality[quality] || 0) + 1
  }

  const nonFallbackCount = Object.entries(byChannel)
    .filter(([channel]) => channel !== 'workflow_fallback')
    .reduce((acc, [, count]) => acc + count, 0)
  const fallbackCount = byChannel.workflow_fallback || 0
  const isDegenerate = Boolean(args.degenerateEvidence?.degenerate)
  let groundingQuality: EvidencePackPayload['grounding_quality'] =
    args.deepResearchStatus === 'pending'
      ? 'pending'
      : nonFallbackCount > 0 && fallbackCount === 0
        ? 'grounded'
        : nonFallbackCount > 0
          ? 'partial'
          : 'draft_unverified'
  if (isDegenerate && groundingQuality === 'grounded') {
    groundingQuality = nonFallbackCount > 0 ? 'partial' : 'draft_unverified'
  }

  const warnings = [...(args.warnings || [])]
  if (isDegenerate) {
    if (args.degenerateEvidence?.reason) {
      warnings.push(`Degenerate evidence detected: ${args.degenerateEvidence.reason}`)
    }
    warnings.push('Grounded status is disabled for this run due to degenerate evidence.')
  }
  const uniqueWarnings = Array.from(
    new Set(warnings.map((line) => line.trim()).filter(Boolean)),
  )
  const reportAvailable = Boolean(args.deepResearchReport && args.reportArtifactId)
  const searchStats = args.deepResearchReport?.search_stats

  return {
    summary: normalizeSummaryValue(args.summary, 'No evidence summary available.'),
    evidence: args.evidence,
    is_fallback: args.isFallback,
    grounding_quality: groundingQuality,
    deep_research_status: args.deepResearchStatus,
    degenerate_evidence: isDegenerate,
    degenerate_reason: args.degenerateEvidence?.reason || null,
    dedupe_stats: {
      before: args.degenerateEvidence?.dedupeStats.before || 0,
      after: args.degenerateEvidence?.dedupeStats.after || 0,
      collapsed_groups: args.degenerateEvidence?.dedupeStats.collapsedGroups || 0,
    },
    pending_message:
      args.deepResearchStatus === 'pending'
        ? (typeof args.pendingMessage === 'string' ? args.pendingMessage.trim() : '') || null
        : null,
    kg_injected: Boolean(args.kgInjection?.injected),
    kg_injection_summary: args.kgInjection?.summary || null,
    kg_injection_truncated: Boolean(args.kgInjection?.truncated),
    source_stats: {
      total: args.evidence.length,
      by_kind: byKind,
      by_channel: byChannel,
      by_quality: byQuality,
    },
    deep_research_report_available: reportAvailable,
    deep_research_report_artifact_id: reportAvailable ? args.reportArtifactId || null : null,
    research_coverage_stats: {
      scanned_sources: searchStats?.scanned_count ?? 0,
      qualifying_sources: searchStats?.qualifying_count ?? 0,
      unique_after_dedupe: searchStats?.unique_after_dedupe_count ?? 0,
      final_citable_sources: searchStats?.final_citable_count ?? args.evidence.length,
      discarded_sources: searchStats?.discarded_count ?? 0,
    },
    warnings: uniqueWarnings,
  }
}

function alignEvidenceGroundingQuality(args: {
  evidencePayload: EvidencePackPayload
  candidateSummary: CandidateCardsArtifactPayload['summary']
}): EvidencePackPayload {
  if (args.evidencePayload.deep_research_status === 'pending') {
    return args.evidencePayload
  }

  let nextGroundingQuality: EvidencePackPayload['grounding_quality'] =
    args.candidateSummary.grounded_count > 0
      ? 'grounded'
      : args.candidateSummary.weak_count > 0
        ? 'partial'
        : 'draft_unverified'
  if (args.evidencePayload.degenerate_evidence && nextGroundingQuality === 'grounded') {
    nextGroundingQuality = 'partial'
  }

  if (nextGroundingQuality === args.evidencePayload.grounding_quality) {
    return args.evidencePayload
  }

  const downgradeWarning =
    'Evidence grounding quality aligned to candidate-level evidence anchors (semantic threshold + quality gate).'

  return {
    ...args.evidencePayload,
    grounding_quality: nextGroundingQuality,
    warnings: args.evidencePayload.warnings.includes(downgradeWarning)
      ? args.evidencePayload.warnings
      : [...args.evidencePayload.warnings, downgradeWarning],
  }
}

function normalizeMcpGroundingStatus(args: {
  card: HypothesisCandidateCardPayload
}): 'grounded' | 'weak_grounded' | 'draft_unverified' {
  const rawStatus = normalizeSummaryValue(args.card.grounding_status, '').toLowerCase()
  if (rawStatus === 'grounded') return 'grounded'
  if (rawStatus === 'weak_grounded') return 'weak_grounded'
  if (rawStatus === 'draft_unverified') return 'draft_unverified'
  return 'draft_unverified'
}

function buildDirectionCandidateFromMcpCard(args: {
  canvas: ReturnType<typeof buildSuggestedCanvas>
  card: HypothesisCandidateCardPayload
  evidencePayload: EvidencePackPayload
}): DirectionCandidate {
  const groundingStatus = normalizeMcpGroundingStatus({
    card: args.card,
  })
  const verification = args.card.kg_verification || {}
  const confidence =
    typeof verification.confidence === 'number' ? verification.confidence : null
  const provenance = args.card.provenance || {}
  const relationHint = normalizeSummaryValue(
    typeof provenance.relation_hint === 'string' ? provenance.relation_hint : '',
    '',
  )
  const noveltyGap = normalizeSummaryValue(
    typeof provenance.selection_reason === 'string' ? provenance.selection_reason : '',
    '',
  )
  const riskParts = [
    args.card.deep_research_error ? `Deep research: ${args.card.deep_research_error}` : null,
    relationHint ? `Relation hint: ${relationHint}` : null,
  ].filter((value): value is string => Boolean(value))

  return {
    id: args.card.card_id,
    title: args.card.title,
    hypothesis: args.card.hypothesis,
    independent_variable: args.canvas.term,
    dependent_variable: args.canvas.primary_outcome,
    expected_signal: relationHint || 'directional shift',
    likely_data_source: args.canvas.modality,
    novelty_gap: noveltyGap || 'KG workflow surfaced this as a candidate direction.',
    risk_note:
      riskParts.join(' | ') ||
      'Evidence remains provisional until a discriminating test confirms the bridge.',
    minimal_discriminating_test: args.card.minimal_discriminating_test,
    falsifier_hint: args.card.falsifier_hint,
    taste_axis: args.card.taste_axis,
    claim: args.card.hypothesis,
    evidence_anchors: [],
    grounding_status: groundingStatus,
    confidence,
    semantic_alignment: null,
    anchor_quality: null,
    anchor_dim: relationHint || null,
    anchor_source: 'kg',
    anchor_evidence_ids: [],
    diversity_retry_count: 0,
    fallback_reasons: args.card.deep_research_error ? [args.card.deep_research_error] : [],
    share_allowed: false,
  }
}

function buildCandidateCardsArtifactFromMcp(args: {
  canvas: ReturnType<typeof buildSuggestedCanvas>
  mcpCards: HypothesisCandidateCardPayload[]
  ephemeralWeightedSubgraph: Record<string, unknown> | null
  evidencePayload: EvidencePackPayload
  workflowId: string | null
  candidateLaneMode: string | null
  deepResearchUsed: boolean
  deepResearchPending: boolean
  kgFirstUsed: boolean
  kgTimeoutApplied: boolean
  kgInjectionTokensEst: number
  kgUsed: boolean
  deepResearchWarning: string | null
  kgWarning: string | null
  warnings?: string[]
}): {
  generatedCandidates: DirectionCandidate[]
  payload: CandidateCardsArtifactPayload
} {
  const subgraphSummary =
    args.ephemeralWeightedSubgraph &&
    typeof args.ephemeralWeightedSubgraph.summary === 'object' &&
    args.ephemeralWeightedSubgraph.summary !== null
      ? (args.ephemeralWeightedSubgraph.summary as Record<string, unknown>)
      : null
  const generatedCandidates = args.mcpCards.map((card) =>
    buildDirectionCandidateFromMcpCard({
      canvas: args.canvas,
      card,
      evidencePayload: args.evidencePayload,
    }),
  )

  const items = generatedCandidates.map((candidate, index) => ({
    id: candidate.id,
    title: candidate.title,
    summary: candidate.hypothesis,
    source: 'workflow' as const,
    grounding_status: candidate.grounding_status,
    confidence: candidate.confidence,
    pattern_id: candidate.pattern_id ?? null,
    pattern_label: candidate.pattern_label ?? null,
    claim: candidate.claim ?? null,
    evidence_anchors: candidate.evidence_anchors ?? [],
    semantic_alignment: candidate.semantic_alignment ?? null,
    anchor_quality: candidate.anchor_quality ?? null,
    anchor_dim: candidate.anchor_dim ?? null,
    anchor_source: candidate.anchor_source ?? null,
    anchor_evidence_ids: candidate.anchor_evidence_ids ?? [],
    diversity_retry_count: candidate.diversity_retry_count ?? 0,
    fallback_reasons: candidate.fallback_reasons ?? [],
    share_allowed: candidate.share_allowed ?? false,
    independent_variable: candidate.independent_variable,
    dependent_variable: candidate.dependent_variable,
    expected_signal: candidate.expected_signal,
    likely_data_source: candidate.likely_data_source,
    novelty_gap: candidate.novelty_gap,
    risk_note: candidate.risk_note,
    minimal_discriminating_test: candidate.minimal_discriminating_test,
    falsifier_hint: candidate.falsifier_hint,
    taste_axis: candidate.taste_axis,
    contradiction_probe: args.mcpCards[index]?.contradiction_probe ?? null,
    topology_shift_probe: args.mcpCards[index]?.topology_shift_probe ?? null,
    novelty_signals: args.mcpCards[index]?.novelty_signals ?? null,
    topology_subgraph: args.mcpCards[index]?.topology_subgraph ?? null,
  }))

  const groundedCount = items.filter((item) => item.grounding_status === 'grounded').length
  const weakCount = items.filter((item) => item.grounding_status === 'weak_grounded').length
  const draftCount = items.length - groundedCount - weakCount

  return {
    generatedCandidates,
    payload: {
      items,
      summary: {
        grounded_count: groundedCount,
        weak_count: weakCount,
        draft_count: draftCount,
        total_count: items.length,
      },
      diagnostics: {
        deep_research_used: args.deepResearchUsed,
        deep_research_pending: args.deepResearchPending,
        kg_first_used: args.kgFirstUsed,
        kg_timeout_applied: args.kgTimeoutApplied,
        workflow_id: args.workflowId,
        candidate_lane_mode: args.candidateLaneMode,
        mcp_fallback_used: false,
        kg_injection_tokens_est: args.kgInjectionTokensEst,
        degenerate_evidence: args.evidencePayload.degenerate_evidence,
        degenerate_mode: args.evidencePayload.degenerate_evidence ? 'soft_keep_top1' : 'none',
        kg_used: args.kgUsed,
        fallback_used: !args.deepResearchUsed && !args.deepResearchPending,
        generation_mode: args.deepResearchUsed ? 'evidence_first' : 'template_fallback',
        fact_count: 0,
        cluster_count: 0,
        selected_cluster_count: 0,
        anchor_pool_size: 0,
        unique_anchor_dims: 0,
        pattern_reuse_count: 0,
        diversity_resample_count: 0,
        diversity_exhausted_slots: 0,
        qualifying_evidence_count: 0,
        distinct_qualifying_docs: 0,
        overlap_threshold: 0,
        primary_anchor_required: false,
        evidence_quality_counts: {
          primary: args.evidencePayload.source_stats.by_quality.primary || 0,
          secondary: args.evidencePayload.source_stats.by_quality.secondary || 0,
          tertiary: args.evidencePayload.source_stats.by_quality.tertiary || 0,
        },
        ephemeral_weighted_subgraph_available: Boolean(args.ephemeralWeightedSubgraph),
        ephemeral_weighted_subgraph_node_count:
          typeof subgraphSummary?.node_count === 'number' ? subgraphSummary.node_count : 0,
        ephemeral_weighted_subgraph_edge_count:
          typeof subgraphSummary?.edge_count === 'number' ? subgraphSummary.edge_count : 0,
        ephemeral_weighted_subgraph_card_count:
          typeof subgraphSummary?.card_subgraph_count === 'number'
            ? subgraphSummary.card_subgraph_count
            : 0,
        reasons: [
          args.deepResearchWarning,
          args.kgWarning,
          ...(args.warnings || []),
        ].filter((value): value is string => Boolean(value)),
      },
      evidence_trace: {
        facts: [],
        clusters: [],
      },
    },
  }
}

function buildCandidateCardsArtifact(args: {
  canvas: ReturnType<typeof buildSuggestedCanvas>
  evidencePayload: EvidencePackPayload
  kgComparePayload: KgComparePayload
  workflowId?: string | null
  candidateLaneMode?: string | null
  mcpFallbackUsed?: boolean
  deepResearchUsed: boolean
  deepResearchPending: boolean
  kgFirstUsed: boolean
  kgTimeoutApplied: boolean
  kgInjectionTokensEst: number
  kgUsed: boolean
  deepResearchWarning: string | null
  kgWarning: string | null
  nCandidates?: number
}): {
  generatedCandidates: ReturnType<typeof buildGroundedDirectionCandidates>
  payload: CandidateCardsArtifactPayload
} {
  const overlapThresholdEnv = Number(process.env.HYPOTHESIS_CLAIM_EVIDENCE_OVERLAP_THRESHOLD)
  const overlapThreshold = Number.isFinite(overlapThresholdEnv) ? overlapThresholdEnv : 0.15
  const candidateEvidence = args.evidencePayload.evidence.filter(
    (item) =>
      item.source_channel !== 'workflow_fallback' &&
      item.source_channel !== 'deep_research_pending',
  )

  const evidenceQualityCounts = {
    primary: 0,
    secondary: 0,
    tertiary: 0,
  }
  for (const item of candidateEvidence) {
    const tier =
      item.quality_tier === 'primary' || item.quality_tier === 'secondary'
        ? item.quality_tier
        : 'tertiary'
    evidenceQualityCounts[tier] += 1
  }

  const generated = buildGroundedDirectionCandidatesWithTrace(
    args.canvas,
    {
      evidence: candidateEvidence,
      kgCompare: {
        prior_art_match: args.kgComparePayload.prior_art_match,
        novelty_gap: args.kgComparePayload.novelty_gap,
        feasibility_constraints: args.kgComparePayload.feasibility_constraints,
        novelty_taste: args.kgComparePayload.novelty_taste,
        warnings: args.kgComparePayload.warnings,
      },
      kgConcepts: args.kgComparePayload.concepts,
      deepResearchSummary: args.evidencePayload.summary,
      overlapThreshold,
      degenerateEvidence: {
        degenerate: args.evidencePayload.degenerate_evidence,
        reason: args.evidencePayload.degenerate_reason,
        mode: args.evidencePayload.degenerate_evidence ? 'soft_keep_top1' : 'none',
      },
    },
    args.nCandidates || 6,
  )
  const generatedCandidates = generated.candidates

  const groundedCount = generatedCandidates.filter(
    (candidate) => candidate.grounding_status === 'grounded',
  ).length
  const weakCount = generatedCandidates.filter(
    (candidate) => candidate.grounding_status === 'weak_grounded',
  ).length
  const draftCount = generatedCandidates.length - groundedCount - weakCount

  return {
    generatedCandidates,
    payload: {
      items: generatedCandidates.map((candidate) => {
        const fallbackReasons = (candidate.fallback_reasons || []).map((reason) => {
          if (
            args.deepResearchPending &&
            (reason === 'No external evidence anchors available; candidate remains draft.' ||
              reason.startsWith('No evidence passed semantic alignment threshold'))
          ) {
            return 'Live deep research is still running; evidence anchors will appear when retrieval completes.'
          }
          return reason
        })

        return {
          id: candidate.id,
          title: candidate.title,
          summary: candidate.hypothesis,
          source: 'workflow',
          grounding_status: candidate.grounding_status,
          confidence: candidate.confidence,
          pattern_id: candidate.pattern_id,
          pattern_label: candidate.pattern_label,
          claim: candidate.claim,
          evidence_anchors: candidate.evidence_anchors || [],
          semantic_alignment: candidate.semantic_alignment ?? null,
          anchor_quality: candidate.anchor_quality ?? null,
          anchor_dim: candidate.anchor_dim ?? null,
          anchor_source: candidate.anchor_source ?? null,
          anchor_evidence_ids: candidate.anchor_evidence_ids ?? [],
          diversity_retry_count: candidate.diversity_retry_count ?? 0,
          fallback_reasons: fallbackReasons,
          share_allowed: candidate.share_allowed ?? false,
          independent_variable: candidate.independent_variable,
          dependent_variable: candidate.dependent_variable,
          expected_signal: candidate.expected_signal,
          likely_data_source: candidate.likely_data_source,
          novelty_gap: candidate.novelty_gap,
          risk_note: candidate.risk_note,
          minimal_discriminating_test: candidate.minimal_discriminating_test,
          falsifier_hint: candidate.falsifier_hint,
          taste_axis: candidate.taste_axis,
        }
      }),
      summary: {
        grounded_count: groundedCount,
        weak_count: weakCount,
        draft_count: draftCount,
        total_count: generatedCandidates.length,
      },
      diagnostics: {
        deep_research_used: args.deepResearchUsed,
        deep_research_pending: args.deepResearchPending,
        kg_first_used: args.kgFirstUsed,
        kg_timeout_applied: args.kgTimeoutApplied,
        workflow_id: args.workflowId ?? null,
        candidate_lane_mode: args.candidateLaneMode ?? null,
        mcp_fallback_used: args.mcpFallbackUsed ?? false,
        kg_injection_tokens_est: args.kgInjectionTokensEst,
        degenerate_evidence: args.evidencePayload.degenerate_evidence,
        degenerate_mode: args.evidencePayload.degenerate_evidence ? 'soft_keep_top1' : 'none',
        kg_used: args.kgUsed,
        fallback_used: (args.evidencePayload.is_fallback || !args.kgUsed) && !args.deepResearchPending,
        generation_mode: generated.mode,
        fact_count: generated.facts.length,
        cluster_count: generated.clusters.length,
        selected_cluster_count:
          generated.mode === 'evidence_first' ? generated.clusters.length : 0,
        anchor_pool_size: generated.diagnostics.anchor_pool_size,
        unique_anchor_dims: generated.diagnostics.unique_anchor_dims,
        pattern_reuse_count: generated.diagnostics.pattern_reuse_count,
        diversity_resample_count: generated.diagnostics.diversity_resample_count,
        diversity_exhausted_slots: generated.diagnostics.diversity_exhausted_slots,
        qualifying_evidence_count: generated.diagnostics.qualifying_evidence_count,
        distinct_qualifying_docs: generated.diagnostics.distinct_qualifying_docs,
        overlap_threshold: overlapThreshold,
        primary_anchor_required: true,
        evidence_quality_counts: evidenceQualityCounts,
        ephemeral_weighted_subgraph_available: false,
        ephemeral_weighted_subgraph_node_count: 0,
        ephemeral_weighted_subgraph_edge_count: 0,
        ephemeral_weighted_subgraph_card_count: 0,
        reasons: [args.deepResearchWarning, args.kgWarning].filter(
          (value): value is string => Boolean(value),
        ),
      },
      evidence_trace: {
        facts: generated.facts.slice(0, 8).map((fact) => ({
          id: fact.id,
          evidence_id: fact.evidence_id,
          text: fact.text,
          relevance: fact.relevance,
          quality_tier: fact.quality_tier,
          source_channel: fact.source_channel,
        })),
        clusters: generated.clusters.slice(0, 5).map((cluster) => ({
          id: cluster.id,
          fact_ids: cluster.fact_ids,
          evidence_ids: cluster.evidence_ids,
          key_terms: cluster.key_terms,
          score: cluster.score,
        })),
      },
    },
  }
}

function incrementStringCount(counter: Record<string, number>, rawKey: string | null | undefined): void {
  const key = normalizeSummaryValue(rawKey, '')
  if (!key) return
  counter[key] = (counter[key] || 0) + 1
}

function normalizeResolvedAnchorBundleForTrajectory(
  bundle: HypothesisResolvedAnchorBundleItem[],
): HotLoadTrajectoryArtifactPayload['resolved_anchor_bundle'] {
  return bundle.map((item) => ({
    kg_id: item.kg_id,
    label: item.label,
    node_type: item.node_type,
    matched_queries: item.matched_queries,
    score: item.score,
    rank: item.rank,
  }))
}

function buildHotLoadTrajectoryArtifact(args: {
  query: string
  workflowId: string | null
  candidateLaneMode: string | null
  mcpFallbackUsed: boolean
  resolvedAnchorBundle: HypothesisResolvedAnchorBundleItem[]
  mcpCards: HypothesisCandidateCardPayload[]
  ephemeralWeightedSubgraph: Record<string, unknown> | null
  candidateSummary: CandidateCardsArtifactPayload['summary']
  evidencePayload: EvidencePackPayload
  deepResearchUsed: boolean
  deepResearchPending: boolean
  deepResearchWarning: string | null
  extraWarnings?: string[]
}): HotLoadTrajectoryArtifactPayload {
  const verdictCounts: Record<string, number> = {}
  const evidenceSourceScopeCounts: Record<string, number> = {}
  const deepResearchStatusCounts: Record<string, number> = {}
  const subgraphSummary =
    args.ephemeralWeightedSubgraph &&
    typeof args.ephemeralWeightedSubgraph.summary === 'object' &&
    args.ephemeralWeightedSubgraph.summary !== null
      ? (args.ephemeralWeightedSubgraph.summary as Record<string, unknown>)
      : null

  for (const card of args.mcpCards) {
    const verification = card.kg_verification || {}
    incrementStringCount(
      verdictCounts,
      typeof verification.verdict === 'string' ? verification.verdict : null,
    )
    incrementStringCount(
      evidenceSourceScopeCounts,
      typeof verification.evidence_source_scope === 'string'
        ? verification.evidence_source_scope
        : null,
    )
    incrementStringCount(deepResearchStatusCounts, card.deep_research_status)
  }

  return {
    trajectory_version: 'v1',
    trigger_kind: 'free_text_query',
    query: args.query,
    query_normalized: normalizeSummaryValue(args.query, args.query),
    captured_at: new Date().toISOString(),
    workflow: {
      workflow_id: args.workflowId,
      candidate_lane_mode: args.candidateLaneMode,
      mcp_fallback_used: args.mcpFallbackUsed,
      verification_source: args.mcpFallbackUsed ? 'local_fallback' : 'mcp_workflow',
    },
    resolved_anchor_bundle: normalizeResolvedAnchorBundleForTrajectory(
      args.resolvedAnchorBundle,
    ),
    candidate_cards: {
      total_count: args.candidateSummary.total_count,
      grounded_count: args.candidateSummary.grounded_count,
      weak_count: args.candidateSummary.weak_count,
      draft_count: args.candidateSummary.draft_count,
      verdict_counts: verdictCounts,
      evidence_source_scope_counts: evidenceSourceScopeCounts,
      deep_research_status_counts: deepResearchStatusCounts,
    },
    evidence: {
      total_count: args.evidencePayload.source_stats.total,
      grounding_quality: args.evidencePayload.grounding_quality,
      deep_research_status: args.evidencePayload.deep_research_status,
      source_channel_counts: args.evidencePayload.source_stats.by_channel,
      quality_counts: args.evidencePayload.source_stats.by_quality,
    },
    deep_research: {
      used: args.deepResearchUsed,
      pending: args.deepResearchPending,
      report_available: args.evidencePayload.deep_research_report_available,
      report_artifact_id: args.evidencePayload.deep_research_report_artifact_id,
      warning: args.deepResearchWarning,
    },
    ephemeral_weighted_subgraph: {
      available: Boolean(args.ephemeralWeightedSubgraph),
      node_count:
        typeof subgraphSummary?.node_count === 'number' ? subgraphSummary.node_count : 0,
      edge_count:
        typeof subgraphSummary?.edge_count === 'number' ? subgraphSummary.edge_count : 0,
      card_subgraph_count:
        typeof subgraphSummary?.card_subgraph_count === 'number'
          ? subgraphSummary.card_subgraph_count
          : 0,
    },
    warnings: Array.from(
      new Set([...args.evidencePayload.warnings, ...(args.extraWarnings || [])]),
    ),
  }
}

export async function executeHypothesisRun(args: {
  runId: string
  sessionId: string
  intentSummary: HypothesisIntentSummary
  authHeaders?: Headers
  deepResearchOptions?: DeepResearchRuntimeOptions
  kgCompareOptions?: KgCompareRuntimeOptions
  kgOrchestrationOptions?: {
    kgFirst?: boolean
    timeoutSec?: number | null
    promptTopK?: number
    promptMaxChars?: number
  }
  nCandidates?: number
}): Promise<void> {
  const {
    runId,
    sessionId,
    intentSummary,
    authHeaders,
    deepResearchOptions,
    kgCompareOptions,
    kgOrchestrationOptions,
  } = args
  const term = normalizeSummaryValue(intentSummary.term, 'working memory')
  const deepResearchUiWaitSec = normalizeNonNegativeInt(
    deepResearchOptions?.uiWaitSec,
    normalizeNonNegativeInt(
      Number(process.env.HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC),
      DEFAULT_DEEP_RESEARCH_UI_WAIT_SEC,
    ),
  )
  const candidateCount = resolveCandidateCount(
    args.nCandidates ??
      Number(process.env.HYPOTHESIS_CANDIDATE_COUNT || DEFAULT_CANDIDATE_COUNT),
  )
  const resolvedDeepResearchOptions: DeepResearchRuntimeOptions = {
    ...deepResearchOptions,
    backgroundCapSec: normalizePositiveInt(
      deepResearchOptions?.backgroundCapSec,
      normalizePositiveInt(
        Number(process.env.HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC),
        DEFAULT_DEEP_RESEARCH_BACKGROUND_CAP_SEC,
      ),
    ),
  }
  const kgFirst = kgOrchestrationOptions?.kgFirst ?? true
  const kgCompareTimeoutMs = resolveKgTimeoutMs(kgOrchestrationOptions?.timeoutSec)
  const kgPromptTopK = normalizePositiveInt(
    kgOrchestrationOptions?.promptTopK,
    DEFAULT_KG_PROMPT_TOPK,
  )
  const kgPromptMaxChars = normalizePositiveInt(
    kgOrchestrationOptions?.promptMaxChars,
    DEFAULT_KG_PROMPT_MAX_CHARS,
  )

  try {
    emitRunState(runId, 'running', `Intent locked for "${term}"`)
    emitStage(runId, 'clarify', `Intent locked: "${term}"`, 0.08)

    const session = await getOrCreateLocalHypothesisSessionPersisted({ sessionId })
    const answers: Record<string, string> = {}
    if (intentSummary.goal) answers.goal = intentSummary.goal
    if (intentSummary.modality) answers.modality = intentSummary.modality
    if (intentSummary.population) answers.population = intentSummary.population

    const canvas = buildSuggestedCanvas({
      term,
      answers,
      context: {
        dataset_id: session.context.dataset_id,
        concept_id: session.context.concept_id,
        task_id: session.context.task_id,
      },
    })
    upsertArtifact(runId, {
      id: 'canvas',
      kind: 'hypothesis_canvas',
      payload: canvas as unknown as Record<string, unknown>,
    })
    await sleep(WAIT_MS)

    let kgComparePayload: KgComparePayload = {
      prior_art_match: [
        'Similar paradigm exists, but outcome definition differs.',
        'Prior analyses often conflate task context and population effects.',
      ],
      novelty_gap: [
        'Conditionally coherent bridge between task clusters remains under-tested.',
        'Minimal discriminating tests are rarely used before full pipelines.',
      ],
      feasibility_constraints: [
        'Need reproducible derivatives and explicit confound controls.',
        'Subgroup analyses may require stricter sample-size checks.',
      ],
      novelty_taste: {
        structural_leverage: [],
        contradiction_motifs: [],
        ood_hypotheses: [],
        topology_shifts: [],
      },
      concepts: [] as string[],
      warnings: [] as string[],
      multihop_attempts: 0,
    }
    let kgUsed = false
    let kgWarning: string | null = null
    let kgTimeoutApplied = false
    const runKgCompareStage = async (progress: number): Promise<void> => {
      emitStage(runId, 'kg_compare', 'Comparing against existing studies in BR-KG...', progress)
      const timeoutMessage =
        kgCompareTimeoutMs && kgCompareTimeoutMs > 0
          ? `KG compare timed out after ${Math.trunc(
              kgCompareTimeoutMs / 1000,
            )}s; continuing without KG priors.`
          : 'KG compare timed out; continuing without KG priors.'
      try {
        const kgCompare = await withTimeout(
          runKgCompare({
            term,
            authHeaders,
            options: {
              ...kgCompareOptions,
              timeoutMs: kgCompareTimeoutMs,
            },
          }),
          kgCompareTimeoutMs,
          timeoutMessage,
        )
        kgComparePayload = {
          prior_art_match: kgCompare.priorArtMatch,
          novelty_gap: kgCompare.noveltyGap,
          feasibility_constraints: kgCompare.feasibilityConstraints,
          novelty_taste: {
            structural_leverage: kgCompare.noveltyTaste.structuralLeverage,
            contradiction_motifs: kgCompare.noveltyTaste.contradictionMotifs,
            ood_hypotheses: kgCompare.noveltyTaste.oodHypotheses,
            topology_shifts: kgCompare.noveltyTaste.topologyShifts,
          },
          concepts: kgCompare.concepts,
          warnings: kgCompare.warnings,
          multihop_attempts: kgCompare.multihopAttempts,
        }
        kgUsed = true
        emitMetric(runId, 'kg_concept_count', kgCompare.concepts.length)
        emitMetric(runId, 'kg_multihop_attempts', kgCompare.multihopAttempts)
        if (kgCompare.warnings.length) {
          if (NO_SEED_ENTITIES_PATTERN.test(kgCompare.warnings.join(' '))) {
            emitMetric(runId, 'kg_no_seed_soft_fallback', 1)
          }
          emitStage(runId, 'kg_compare', `KG compare degraded: ${kgCompare.warnings[0]}`, 0.54)
        }
      } catch (error) {
        const rawMessage =
          error instanceof Error
            ? error.message
            : 'KG compare unavailable. Falling back to local comparison.'
        kgWarning = rawMessage
        if (/timed out/i.test(rawMessage)) {
          kgTimeoutApplied = true
          emitMetric(runId, 'kg_compare_timeout', 1)
        }
        const message = NO_SEED_ENTITIES_PATTERN.test(rawMessage)
          ? 'no anchored entities found; using local comparison fallback.'
          : rawMessage
        kgComparePayload = {
          ...kgComparePayload,
          warnings: Array.from(new Set([...kgComparePayload.warnings, message])),
        }
        emitStage(runId, 'kg_compare', `KG compare degraded: ${message}`, 0.54)
      }
      upsertArtifact(runId, {
        id: 'kg-compare',
        kind: 'kg_compare',
        payload: kgComparePayload,
      })
    }

    if (kgFirst) {
      await runKgCompareStage(0.22)
      await sleep(WAIT_MS)
    }

    const kgPromptInjection = kgFirst && kgUsed
      ? buildKgPromptInjection({
          term,
          kgCompare: kgComparePayload,
          topK: kgPromptTopK,
          maxChars: kgPromptMaxChars,
        })
      : {
          injected: false,
          prompt: null,
          summary: null,
          truncated: false,
          tokensEstimate: 0,
        }

    let deepResearchPending = true
    let evidencePayload = buildEvidencePack({
      summary: 'Deep research is running. Evidence will appear when retrieval completes.',
      evidence: normalizeEvidenceChannels(pendingDeepResearchEvidence(term), 'deep_research_pending'),
      isFallback: false,
      deepResearchStatus: 'pending',
      pendingMessage:
        'Live evidence retrieval is still in progress. This run completed intermediate artifacts first.',
      kgInjection: kgPromptInjection,
      warnings: ['Deep research in progress. Evidence is pending and will update automatically.'],
    })
    upsertArtifact(runId, {
      id: 'evidence-pack',
      kind: 'evidence_pack',
      payload: evidencePayload,
    })

    let deepResearchUsed = false
    let deepResearchWarning: string | null = null
    let deepResearchInteractionId: string | null = null
    const deepResearchReportArtifactId = 'deep-research-report'
    const deepResearchTask = (async () => {
      emitStage(runId, 'deep_research', `Querying live sources for "${term}"...`, 0.34)
      try {
        const deepResearch = await runDeepResearch({
          query: buildDeepResearchQuery({
            term,
            goal: canvas.goal,
            modality: canvas.modality,
            population: canvas.population,
            kgPriorsPrompt: kgPromptInjection.prompt,
          }),
          authHeaders,
          options: resolvedDeepResearchOptions,
          onProgress: (message, progress) => {
            emitStage(runId, 'deep_research', message, progress)
          },
        })
        if (deepResearch.fallbackPath !== 'none') {
          emitMetric(runId, 'deep_research_sync_fallback_attempt', 1)
          if (deepResearch.qualityGate.pass) {
            emitMetric(runId, 'deep_research_sync_fallback_success', 1)
          }
        }
        if (!deepResearch.qualityGate.pass) {
          emitMetric(runId, 'deep_research_quality_gate_fail', 1)
          emitMetric(runId, 'deep_research_low_confidence', 1)
        }
        const liveEvidence = normalizeEvidenceChannels(deepResearch.evidence, 'deep_research_live')
        deepResearchInteractionId =
          normalizeSummaryValue(
            typeof deepResearch.interactionId === 'string'
              ? deepResearch.interactionId
              : typeof deepResearch.report?.interaction_id === 'string'
                ? deepResearch.report.interaction_id
                : '',
            '',
          ) || null
        if (deepResearch.report) {
          upsertArtifact(runId, {
            id: deepResearchReportArtifactId,
            kind: 'deep_research_report',
            payload: deepResearch.report as unknown as Record<string, unknown>,
          })
        }
        const liveWarnings: string[] = []
        if (!deepResearch.qualityGate.pass) {
          liveWarnings.push(
            deepResearch.qualityGate.reason ||
              'Deep research evidence did not meet the balanced quality gate; marked low-confidence.',
          )
        }
        deepResearchPending = false
        evidencePayload = buildEvidencePack({
          summary: deepResearch.summary,
          evidence: liveEvidence.length
            ? liveEvidence
            : normalizeEvidenceChannels(defaultEvidence(term), 'workflow_fallback'),
          isFallback: !liveEvidence.length,
          deepResearchStatus: 'ready',
          degenerateEvidence: deepResearch.degenerateEvidence,
          deepResearchReport: deepResearch.report || null,
          reportArtifactId: deepResearch.report ? deepResearchReportArtifactId : null,
          kgInjection: kgPromptInjection,
          warnings: liveEvidence.length
            ? liveWarnings
            : [
                ...liveWarnings,
                'Deep research returned no citeable evidence; fallback scaffold retained.',
              ],
        })
        if (deepResearch.degenerateEvidence.dedupeStats.collapsedGroups > 0) {
          emitMetric(
            runId,
            'deep_research_collapsed_groups',
            deepResearch.degenerateEvidence.dedupeStats.collapsedGroups,
          )
        }
        deepResearchUsed = liveEvidence.length > 0
        emitMetric(runId, 'evidence_count', evidencePayload.evidence.length)
        upsertArtifact(runId, {
          id: 'evidence-pack',
          kind: 'evidence_pack',
          payload: evidencePayload,
        })
        emitStage(runId, 'deep_research', 'Deep research evidence updated.', 0.44)
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : 'Deep research unavailable. Falling back to local evidence.'
        const deepResearchErrorCode = getDeepResearchErrorCode(error)
        deepResearchWarning = message
        if (
          deepResearchErrorCode === DEEP_RESEARCH_ERROR_CODES.MAX_POLLS_EXCEEDED ||
          deepResearchErrorCode === DEEP_RESEARCH_ERROR_CODES.BACKGROUND_CAP_EXCEEDED
        ) {
          emitMetric(runId, 'deep_research_timeout', 1)
        }
        if (deepResearchErrorCode === DEEP_RESEARCH_ERROR_CODES.MISSING_INTERACTION_ID) {
          emitMetric(runId, 'deep_research_missing_ids', 1)
        }
        deepResearchPending = false
        evidencePayload = buildEvidencePack({
          summary: 'Deep research unavailable. Showing draft scaffold only.',
          evidence: normalizeEvidenceChannels(defaultEvidence(term), 'workflow_fallback'),
          isFallback: true,
          deepResearchStatus: 'failed',
          kgInjection: kgPromptInjection,
          warnings: [
            `Deep research failed: ${message}`,
            'Fallback scaffold is shown because live evidence retrieval did not succeed.',
          ],
        })
        upsertArtifact(runId, {
          id: 'evidence-pack',
          kind: 'evidence_pack',
          payload: evidencePayload,
        })
        emitStage(runId, 'deep_research', `Deep research unavailable: ${message}`, 0.34)
      }
    })()

    await sleep(WAIT_MS)

    if (!kgFirst) {
      await runKgCompareStage(0.48)
      await sleep(WAIT_MS)
    }

    emitStage(
      runId,
      'candidate_generation',
      'Waiting for deep research evidence before synthesizing candidates...',
      0.7,
    )

    const deepResearchSettledInUiWindow = await Promise.race([
      deepResearchTask.then(() => true),
      sleep(deepResearchUiWaitSec * 1000).then(() => false),
    ])
    if (!deepResearchSettledInUiWindow) {
      emitStage(
        runId,
        'deep_research',
        `Deep research is still running after ${formatDuration(
          deepResearchUiWaitSec,
        )}; candidate synthesis will run once evidence is ready.`,
        0.78,
      )
      emitRunState(runId, 'running', 'Deep research still running. Waiting for evidence before candidates.')
    }

    await deepResearchTask

    emitStage(
      runId,
      'candidate_generation',
      deepResearchUsed
        ? 'Surfacing high-leverage candidate directions from deep research evidence...'
        : 'Surfacing candidate directions from fallback evidence...',
      0.82,
    )
    let hotLoadResolvedAnchorBundle: HypothesisResolvedAnchorBundleItem[] = []
    let hotLoadMcpCards: HypothesisCandidateCardPayload[] = []
    let hotLoadWorkflowId: string | null = null
    let hotLoadCandidateLaneMode: string | null = null
    let hotLoadEphemeralWeightedSubgraph: Record<string, unknown> | null = null
    let hotLoadMcpFallbackUsed = false
    let initialCandidateCards:
      | ReturnType<typeof buildCandidateCardsArtifact>
      | ReturnType<typeof buildCandidateCardsArtifactFromMcp>
    try {
      const mcpCandidateCards = await runKgHypothesisCandidateCards({
        query: term,
        authHeaders,
        topN: candidateCount,
        topK: Math.max(candidateCount * 2, 12),
        tasteMode: 'balanced',
        controllerMode: 'principle_v0',
        candidateLaneMode: 'broad',
        withDeepResearch: false,
        deepResearchInteractionId: deepResearchPending ? null : deepResearchInteractionId,
      })
      if (mcpCandidateCards.candidateCards.length) {
        hotLoadResolvedAnchorBundle = mcpCandidateCards.resolvedAnchorBundle
        hotLoadMcpCards = mcpCandidateCards.candidateCards
        hotLoadEphemeralWeightedSubgraph = mcpCandidateCards.ephemeralWeightedSubgraph
        hotLoadWorkflowId =
          normalizeSummaryValue(
            typeof mcpCandidateCards.workflow?.workflow_id === 'string'
              ? mcpCandidateCards.workflow.workflow_id
              : '',
            '',
          ) || null
        hotLoadCandidateLaneMode = mcpCandidateCards.summary.candidateLaneMode
        initialCandidateCards = buildCandidateCardsArtifactFromMcp({
          canvas,
          mcpCards: mcpCandidateCards.candidateCards,
          ephemeralWeightedSubgraph: mcpCandidateCards.ephemeralWeightedSubgraph,
          evidencePayload,
          workflowId: hotLoadWorkflowId,
          candidateLaneMode: hotLoadCandidateLaneMode,
          deepResearchUsed,
          deepResearchPending,
          kgFirstUsed: kgFirst,
          kgTimeoutApplied,
          kgInjectionTokensEst: kgPromptInjection.tokensEstimate,
          kgUsed,
          deepResearchWarning,
          kgWarning,
          warnings: mcpCandidateCards.warnings,
        })
      } else {
        throw new Error('kg_hypothesis_candidate_cards returned no candidate cards')
      }
    } catch (error) {
      const fallbackMessage = `Candidate-card MCP fallback: ${error instanceof Error ? error.message : 'unknown error'}`
      hotLoadMcpFallbackUsed = true
      initialCandidateCards = buildCandidateCardsArtifact({
        canvas,
        evidencePayload,
        kgComparePayload,
        workflowId: null,
        candidateLaneMode: null,
        mcpFallbackUsed: true,
        deepResearchUsed,
        deepResearchPending,
        kgFirstUsed: kgFirst,
        kgTimeoutApplied,
        kgInjectionTokensEst: kgPromptInjection.tokensEstimate,
        kgUsed,
        deepResearchWarning,
        kgWarning: kgWarning ? `${kgWarning} | ${fallbackMessage}` : fallbackMessage,
        nCandidates: candidateCount,
      })
    }
    emitMetric(runId, 'candidate_count', initialCandidateCards.payload.items.length)

    evidencePayload = alignEvidenceGroundingQuality({
      evidencePayload,
      candidateSummary: initialCandidateCards.payload.summary,
    })
    upsertArtifact(runId, {
      id: 'evidence-pack',
      kind: 'evidence_pack',
      payload: evidencePayload,
    })

    upsertArtifact(runId, {
      id: 'candidate-cards',
      kind: 'candidate_cards',
      payload: initialCandidateCards.payload,
    })
    upsertArtifact(runId, {
      id: 'hot-load-trajectory',
      kind: 'hot_load_trajectory',
      payload: buildHotLoadTrajectoryArtifact({
        query: term,
        workflowId: hotLoadWorkflowId,
        candidateLaneMode: hotLoadCandidateLaneMode,
        mcpFallbackUsed: hotLoadMcpFallbackUsed,
        resolvedAnchorBundle: hotLoadResolvedAnchorBundle,
        mcpCards: hotLoadMcpCards,
        ephemeralWeightedSubgraph: hotLoadMcpFallbackUsed ? null : hotLoadEphemeralWeightedSubgraph,
        candidateSummary: initialCandidateCards.payload.summary,
        evidencePayload,
        deepResearchUsed,
        deepResearchPending,
        deepResearchWarning,
        extraWarnings: initialCandidateCards.payload.diagnostics.reasons,
      }),
    })
    emitMetric(runId, 'candidate_grounded_count', initialCandidateCards.payload.summary.grounded_count)
    await sleep(WAIT_MS)

    emitStage(runId, 'plan_validation', 'Generating and validating executable plan...', 0.9)
    const candidate = initialCandidateCards.generatedCandidates[0]
    const preview = buildResearchPreview(canvas, candidate)
    const plan = buildWorkflowPlan({
      canvas,
      candidate,
      preview,
    })
    upsertArtifact(runId, {
      id: 'workflow-plan',
      kind: 'workflow_plan',
      payload: {
        preview,
        plan,
      } as unknown as Record<string, unknown>,
    })

    const validation = evaluateWorkflowPlan({
      plan,
      canvas,
      context: {
        dataset_id: session.context.dataset_id,
        concept_id: session.context.concept_id,
        task_id: session.context.task_id,
      },
    })
    upsertArtifact(runId, {
      id: 'validation-report',
      kind: 'validation_report',
      payload: {
        validation,
      } as unknown as Record<string, unknown>,
    })
    await sleep(Math.trunc(WAIT_MS * 0.6))

    const completionMessage =
      evidencePayload.deep_research_status === 'ready'
        ? 'Analysis ready · Evidence ready.'
        : 'Analysis ready · Evidence update failed (fallback active).'
    emitRunState(runId, 'completed', completionMessage)
    markRunCompleted(
      runId,
      evidencePayload.deep_research_status === 'ready'
        ? 'Analysis artifacts are ready and evidence is fully updated.'
        : 'Analysis artifacts are ready; evidence update failed and fallback scaffold is active.',
    )
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Unexpected failure while executing hypothesis run.'
    markRunFailed(runId, message)
  }
}
