import type { HypothesisArtifactEnvelope, HypothesisRunSnapshot } from '@/types/hypothesis'

type JsonRecord = Record<string, unknown>

export type HotLoadTrajectoryExportRow = {
  session_id: string
  run_id: string
  run_state: string
  started_at: string
  updated_at: string
  query: string
  query_normalized: string
  workflow_id: string | null
  candidate_lane_mode: string | null
  mcp_fallback_used: boolean
  verification_source: 'mcp_workflow' | 'local_fallback'
  deep_research_status: 'pending' | 'ready' | 'failed'
  deep_research_used: boolean
  deep_research_pending: boolean
  deep_research_report_available: boolean
  ephemeral_weighted_subgraph_available: boolean
  ephemeral_weighted_subgraph_node_count: number
  ephemeral_weighted_subgraph_edge_count: number
  ephemeral_weighted_subgraph_card_count: number
  total_candidates: number
  grounded_candidates: number
  weak_candidates: number
  draft_candidates: number
  resolved_anchor_count: number
  top_anchor_labels: string[]
  verdict_counts: Record<string, number>
  evidence_source_scope_counts: Record<string, number>
  deep_research_status_counts: Record<string, number>
  source_channel_counts: Record<string, number>
  quality_counts: Record<string, number>
  warnings: string[]
  trajectory: JsonRecord
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as JsonRecord
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asNullableString(value: unknown): string | null {
  const normalized = asString(value)
  return normalized || null
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function asBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true') return true
    if (normalized === 'false') return false
  }
  return fallback
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => asString(item)).filter(Boolean)
}

function parseCounterMap(value: unknown): Record<string, number> {
  const source = asRecord(value)
  if (!source) return {}
  const next: Record<string, number> = {}
  for (const [key, raw] of Object.entries(source)) {
    const parsed = asNumber(raw)
    if (parsed !== null) next[key] = parsed
  }
  return next
}

function findHotLoadTrajectoryArtifact(
  artifacts: HypothesisArtifactEnvelope[],
): HypothesisArtifactEnvelope | null {
  for (let index = artifacts.length - 1; index >= 0; index -= 1) {
    const artifact = artifacts[index]
    if (artifact?.kind === 'hot_load_trajectory') return artifact
  }
  return null
}

export function extractHotLoadTrajectoryRow(
  snapshot: HypothesisRunSnapshot,
): HotLoadTrajectoryExportRow | null {
  const artifact = findHotLoadTrajectoryArtifact(snapshot.artifacts || [])
  if (!artifact) return null

  const payload = asRecord(artifact.payload)
  if (!payload) return null

  const workflow = asRecord(payload.workflow)
  const candidateCards = asRecord(payload.candidate_cards ?? payload.candidateCards)
  const evidence = asRecord(payload.evidence)
  const deepResearch = asRecord(payload.deep_research ?? payload.deepResearch)
  const ephemeralWeightedSubgraph = asRecord(
    payload.ephemeral_weighted_subgraph ?? payload.ephemeralWeightedSubgraph,
  )
  if (!workflow || !candidateCards || !evidence || !deepResearch) return null

  const resolvedAnchorBundle = Array.isArray(
    payload.resolved_anchor_bundle ?? payload.resolvedAnchorBundle,
  )
    ? ((payload.resolved_anchor_bundle ?? payload.resolvedAnchorBundle) as unknown[])
    : []

  const topAnchorLabels = resolvedAnchorBundle
    .map((item) => {
      const row = asRecord(item)
      return asString(row?.label) || asString(row?.kg_id)
    })
    .filter(Boolean)
    .slice(0, 5)

  const deepResearchStatus = asString(
    evidence.deep_research_status ?? evidence.deepResearchStatus,
  )
  const normalizedDeepResearchStatus =
    deepResearchStatus === 'pending' || deepResearchStatus === 'failed'
      ? deepResearchStatus
      : 'ready'

  const verificationSource = asString(
    workflow.verification_source ?? workflow.verificationSource,
  )

  return {
    session_id: snapshot.session_id,
    run_id: snapshot.run_id,
    run_state: snapshot.state,
    started_at: snapshot.started_at,
    updated_at: snapshot.updated_at,
    query: asString(payload.query),
    query_normalized: asString(payload.query_normalized ?? payload.queryNormalized),
    workflow_id: asNullableString(workflow.workflow_id ?? workflow.workflowId),
    candidate_lane_mode: asNullableString(
      workflow.candidate_lane_mode ?? workflow.candidateLaneMode,
    ),
    mcp_fallback_used: asBoolean(
      workflow.mcp_fallback_used ?? workflow.mcpFallbackUsed,
      false,
    ),
    verification_source:
      verificationSource === 'local_fallback' ? 'local_fallback' : 'mcp_workflow',
    deep_research_status: normalizedDeepResearchStatus,
    deep_research_used: asBoolean(deepResearch.used, false),
    deep_research_pending: asBoolean(deepResearch.pending, false),
    deep_research_report_available: asBoolean(
      deepResearch.report_available ?? deepResearch.reportAvailable,
      false,
    ),
    ephemeral_weighted_subgraph_available: asBoolean(
      ephemeralWeightedSubgraph?.available ?? ephemeralWeightedSubgraph?.isAvailable,
      false,
    ),
    ephemeral_weighted_subgraph_node_count:
      asNumber(
        ephemeralWeightedSubgraph?.node_count ?? ephemeralWeightedSubgraph?.nodeCount,
      ) ?? 0,
    ephemeral_weighted_subgraph_edge_count:
      asNumber(
        ephemeralWeightedSubgraph?.edge_count ?? ephemeralWeightedSubgraph?.edgeCount,
      ) ?? 0,
    ephemeral_weighted_subgraph_card_count:
      asNumber(
        ephemeralWeightedSubgraph?.card_subgraph_count ??
          ephemeralWeightedSubgraph?.cardSubgraphCount,
      ) ?? 0,
    total_candidates: asNumber(candidateCards.total_count ?? candidateCards.totalCount) ?? 0,
    grounded_candidates:
      asNumber(candidateCards.grounded_count ?? candidateCards.groundedCount) ?? 0,
    weak_candidates: asNumber(candidateCards.weak_count ?? candidateCards.weakCount) ?? 0,
    draft_candidates: asNumber(candidateCards.draft_count ?? candidateCards.draftCount) ?? 0,
    resolved_anchor_count: resolvedAnchorBundle.length,
    top_anchor_labels: topAnchorLabels,
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
    source_channel_counts: parseCounterMap(
      evidence.source_channel_counts ?? evidence.sourceChannelCounts,
    ),
    quality_counts: parseCounterMap(evidence.quality_counts ?? evidence.qualityCounts),
    warnings: asStringArray(payload.warnings),
    trajectory: payload,
  }
}

export function summarizeHotLoadTrajectoryRows(rows: HotLoadTrajectoryExportRow[]): {
  total_rows: number
  unique_queries: number
  unique_sessions: number
  mcp_fallback_rows: number
  deep_research_ready_rows: number
  verification_source_counts: Record<string, number>
  deep_research_status_counts: Record<string, number>
} {
  const uniqueQueries = new Set<string>()
  const uniqueSessions = new Set<string>()
  const verificationSourceCounts: Record<string, number> = {}
  const deepResearchStatusCounts: Record<string, number> = {}
  let mcpFallbackRows = 0
  let deepResearchReadyRows = 0

  for (const row of rows) {
    if (row.query) uniqueQueries.add(row.query)
    if (row.session_id) uniqueSessions.add(row.session_id)
    verificationSourceCounts[row.verification_source] =
      (verificationSourceCounts[row.verification_source] || 0) + 1
    deepResearchStatusCounts[row.deep_research_status] =
      (deepResearchStatusCounts[row.deep_research_status] || 0) + 1
    if (row.mcp_fallback_used) mcpFallbackRows += 1
    if (row.deep_research_status === 'ready') deepResearchReadyRows += 1
  }

  return {
    total_rows: rows.length,
    unique_queries: uniqueQueries.size,
    unique_sessions: uniqueSessions.size,
    mcp_fallback_rows: mcpFallbackRows,
    deep_research_ready_rows: deepResearchReadyRows,
    verification_source_counts: verificationSourceCounts,
    deep_research_status_counts: deepResearchStatusCounts,
  }
}
