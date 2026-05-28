'use client'

import type {
  CandidateGroundingStatus,
  EvidenceAnchor,
  HypothesisCanvas,
  HypothesisEvidenceItem,
  ResearchPreview,
  ValidationReport,
  WorkflowPlan,
} from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export type ArtifactCandidate = {
  id: string
  title: string
  summary: string
  source: 'session' | 'workflow'
  grounding_status?: CandidateGroundingStatus
  confidence?: number | null
  pattern_id?: string | null
  pattern_label?: string | null
  claim?: string | null
  evidence_anchors?: EvidenceAnchor[]
  semantic_alignment?: number | null
  anchor_quality?: {
    primary: number
    secondary: number
    tertiary: number
  } | null
  anchor_dim?: string | null
  anchor_source?: 'kg' | 'evidence' | 'kg_compare' | 'hybrid' | null
  anchor_evidence_ids?: string[]
  diversity_retry_count?: number | null
  fallback_reasons?: string[]
  share_allowed?: boolean
  independent_variable?: string | null
  dependent_variable?: string | null
  expected_signal?: string | null
  likely_data_source?: string | null
  novelty_gap?: string | null
  risk_note?: string | null
  minimal_discriminating_test?: string | null
  falsifier_hint?: string | null
  taste_axis?: string | null
}

type KgCompareArtifact = {
  prior_art_match: string[]
  novelty_gap: string[]
  feasibility_constraints: string[]
  novelty_taste?: {
    structural_leverage: string[]
    contradiction_motifs: string[]
    ood_hypotheses: string[]
    topology_shifts: string[]
  }
} | null

type CandidateArtifactSummary = {
  grounded_count: number
  weak_count: number
  draft_count: number
  total_count: number
} | null

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
} | null

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
} | null

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
} | null

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
} | null

type HypothesisArtifactPanelProps = {
  analysisReady?: boolean
  canvas: HypothesisCanvas | null
  preview: ResearchPreview | null
  candidates: ArtifactCandidate[]
  candidateSummary?: CandidateArtifactSummary
  candidateDiagnostics?: CandidateArtifactDiagnostics
  candidateTrace?: CandidateEvidenceTrace
  evidence: HypothesisEvidenceItem[]
  evidenceMeta?: EvidenceArtifactMeta
  hotLoadTrajectory?: HotLoadTrajectoryArtifact
  sessionId?: string | null
  runId?: string | null
  plan: WorkflowPlan | null
  validation: ValidationReport | null
  kgCompare: KgCompareArtifact
}

export function HypothesisArtifactPanel({
  analysisReady = false,
  canvas,
  preview,
  candidates,
  candidateSummary,
  candidateDiagnostics,
  candidateTrace,
  evidence,
  evidenceMeta,
  hotLoadTrajectory,
  sessionId,
  runId,
  plan,
  validation,
  kgCompare,
}: HypothesisArtifactPanelProps) {
  const hasData =
    Boolean(canvas) ||
    Boolean(preview) ||
    candidates.length > 0 ||
    evidence.length > 0 ||
    Boolean(hotLoadTrajectory) ||
    Boolean(plan) ||
    Boolean(validation) ||
    Boolean(kgCompare)
  const deepResearchStatus = evidenceMeta?.deep_research_status || null
  const evidencePending = deepResearchStatus === 'pending'
  const reportHref =
    evidenceMeta?.deep_research_report_available && sessionId && runId
      ? `/hypothesis/report?sessionId=${encodeURIComponent(sessionId)}&runId=${encodeURIComponent(runId)}`
      : null
  const runTrajectoryJsonlHref = runId
    ? `/api/hypothesis/trajectory?runId=${encodeURIComponent(runId)}&jsonl=1&download=1`
    : null
  const sessionTrajectoryJsonlHref = sessionId
    ? `/api/hypothesis/trajectory?sessionId=${encodeURIComponent(sessionId)}&jsonl=1&download=1`
    : null

  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Artifacts</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {!hasData ? (
          <div className="text-xs text-muted-foreground">
            No artifacts yet. Send a query in chat and the run will populate this panel automatically.
          </div>
        ) : null}

        {canvas ? (
          <details open className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Canvas</summary>
            <div className="mt-2 space-y-1">
              <div>term: {canvas.term}</div>
              <div>goal: {canvas.goal}</div>
              <div>modality: {canvas.modality}</div>
              <div>population: {canvas.population}</div>
              <div>outcome: {canvas.primary_outcome}</div>
              <div>question: {canvas.research_question}</div>
            </div>
          </details>
        ) : null}

        {preview ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Research Preview</summary>
            <div className="mt-2 space-y-1">
              <div>minutes: {preview.estimated_minutes}</div>
              <div>credits: {preview.estimated_credits}</div>
              <div>risk: {preview.risk_level}</div>
              <div>scope: {preview.coverage_scope.join(' | ')}</div>
            </div>
          </details>
        ) : null}

        {candidates.length ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Candidates ({candidates.length})</summary>
            {analysisReady && evidencePending ? (
              <div className="mt-2 text-[11px] text-amber-700">
                Candidate structure is ready now; evidence anchors are still being enriched.
              </div>
            ) : null}
            {candidateSummary ? (
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="outline">grounded: {candidateSummary.grounded_count}</Badge>
                <Badge variant="outline">weak: {candidateSummary.weak_count}</Badge>
                <Badge variant="outline">draft: {candidateSummary.draft_count}</Badge>
                <Badge variant="outline">total: {candidateSummary.total_count}</Badge>
              </div>
            ) : null}
            {candidateDiagnostics ? (
              <div className="mt-2 text-[11px] text-muted-foreground">
                diagnostics: deep_research={candidateDiagnostics.deep_research_used ? 'on' : 'off'} | kg=
                {candidateDiagnostics.kg_used ? 'on' : 'off'} | pending=
                {candidateDiagnostics.deep_research_pending ? 'on' : 'off'} | fallback=
                {candidateDiagnostics.fallback_used ? 'on' : 'off'} | mcp_fallback=
                {candidateDiagnostics.mcp_fallback_used ? 'on' : 'off'} | kg_first=
                {candidateDiagnostics.kg_first_used ? 'on' : 'off'} | kg_timeout=
                {candidateDiagnostics.kg_timeout_applied ? 'on' : 'off'} | kg_tokens=
                {candidateDiagnostics.kg_injection_tokens_est} | mode=
                {candidateDiagnostics.generation_mode} | workflow=
                {candidateDiagnostics.workflow_id || 'local'} | lane=
                {candidateDiagnostics.candidate_lane_mode || 'n/a'} | degenerate=
                {candidateDiagnostics.degenerate_evidence
                  ? candidateDiagnostics.degenerate_mode
                  : 'none'}{' '}
                | anchors=
                {candidateDiagnostics.unique_anchor_dims}/{candidateDiagnostics.anchor_pool_size} | pattern_reuse=
                {candidateDiagnostics.pattern_reuse_count} | resample=
                {candidateDiagnostics.diversity_resample_count} (exhausted {candidateDiagnostics.diversity_exhausted_slots}) | qualifying=
                {candidateDiagnostics.qualifying_evidence_count}/
                {candidateDiagnostics.distinct_qualifying_docs}
                {' '}
                | facts=
                {candidateDiagnostics.fact_count} | clusters=
                {candidateDiagnostics.cluster_count}/{candidateDiagnostics.selected_cluster_count} | overlap&gt;=
                {candidateDiagnostics.overlap_threshold.toFixed(2)} | primary_required=
                {candidateDiagnostics.primary_anchor_required ? 'yes' : 'no'}
                <div>
                  evidence quality: primary={candidateDiagnostics.evidence_quality_counts.primary}, secondary=
                  {candidateDiagnostics.evidence_quality_counts.secondary}, tertiary=
                  {candidateDiagnostics.evidence_quality_counts.tertiary}
                </div>
              </div>
            ) : null}
            <div className="mt-2 space-y-2">
              {candidates.slice(0, 10).map((candidate) => (
                <div key={candidate.id} className="rounded border border-border/60 p-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="font-medium">{candidate.title}</div>
                    <Badge
                      variant={
                        candidate.grounding_status === 'grounded'
                          ? 'default'
                          : candidate.grounding_status === 'weak_grounded'
                            ? 'outline'
                            : 'secondary'
                      }
                    >
                      {candidate.grounding_status || 'draft_unverified'}
                    </Badge>
                    {candidate.confidence !== null && candidate.confidence !== undefined ? (
                      <Badge variant="outline">confidence: {candidate.confidence.toFixed(2)}</Badge>
                    ) : null}
                  </div>
                  <div className="text-muted-foreground">{candidate.summary}</div>
                  {candidate.evidence_anchors?.length ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      anchors:{' '}
                      {candidate.evidence_anchors
                        .slice(0, 3)
                        .map((anchor) => anchor.label)
                        .join(' | ')}
                    </div>
                  ) : null}
                  {candidate.semantic_alignment !== null &&
                  candidate.semantic_alignment !== undefined ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      semantic alignment: {candidate.semantic_alignment.toFixed(2)}
                    </div>
                  ) : null}
                  {candidate.anchor_dim ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      anchor: {candidate.anchor_dim}
                      {candidate.anchor_source ? ` (${candidate.anchor_source})` : ''}
                    </div>
                  ) : null}
                  {candidate.taste_axis ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      taste axis: {candidate.taste_axis}
                    </div>
                  ) : null}
                  {candidate.minimal_discriminating_test ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      minimal test: {candidate.minimal_discriminating_test}
                    </div>
                  ) : null}
                  {candidate.falsifier_hint ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      falsifier: {candidate.falsifier_hint}
                    </div>
                  ) : null}
                  {candidate.fallback_reasons?.length ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      fallback: {candidate.fallback_reasons.slice(0, 2).join(' | ')}
                    </div>
                  ) : null}
                  {candidate.share_allowed === false ? (
                    <div className="text-[11px] text-muted-foreground mt-1">
                      export/share disabled until grounded evidence is available
                    </div>
                  ) : null}
                  <div className="text-[11px] text-muted-foreground mt-1">source: {candidate.source}</div>
                </div>
              ))}
            </div>
            {candidateTrace?.facts?.length || candidateTrace?.clusters?.length ? (
              <div className="mt-2 rounded border border-border/60 p-2 text-[11px] text-muted-foreground">
                <div className="font-medium text-foreground">Evidence-first trace</div>
                {candidateTrace?.facts?.length ? (
                  <div className="mt-1">
                    facts: {candidateTrace.facts.length} | top:{' '}
                    {candidateTrace.facts
                      .slice(0, 3)
                      .map((fact) => `${fact.text} (${fact.quality_tier}, r=${fact.relevance.toFixed(2)})`)
                      .join(' | ')}
                  </div>
                ) : null}
                {candidateTrace?.clusters?.length ? (
                  <div className="mt-1">
                    clusters: {candidateTrace.clusters.length} | top terms:{' '}
                    {candidateTrace.clusters
                      .slice(0, 3)
                      .map((cluster) => `${cluster.id}[${cluster.key_terms.slice(0, 3).join(', ')}]`)
                      .join(' | ')}
                  </div>
                ) : null}
              </div>
            ) : null}
          </details>
        ) : null}

        {hotLoadTrajectory ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Hot-Load Trajectory</summary>
            <div className="mt-2 space-y-1">
              <div className="flex flex-wrap gap-3 text-[11px]">
                {runTrajectoryJsonlHref ? (
                  <a
                    className="text-primary underline underline-offset-2"
                    href={runTrajectoryJsonlHref}
                  >
                    download run JSONL
                  </a>
                ) : null}
                {sessionTrajectoryJsonlHref ? (
                  <a
                    className="text-primary underline underline-offset-2"
                    href={sessionTrajectoryJsonlHref}
                  >
                    download session JSONL
                  </a>
                ) : null}
              </div>
              <div>query: {hotLoadTrajectory.query}</div>
              <div>
                workflow: {hotLoadTrajectory.workflow.workflow_id || 'n/a'} | source:{' '}
                {hotLoadTrajectory.workflow.verification_source} | lane:{' '}
                {hotLoadTrajectory.workflow.candidate_lane_mode || 'n/a'} | mcp_fallback:{' '}
                {hotLoadTrajectory.workflow.mcp_fallback_used ? 'yes' : 'no'}
              </div>
              <div>
                candidates: {hotLoadTrajectory.candidate_cards.total_count} | grounded:{' '}
                {hotLoadTrajectory.candidate_cards.grounded_count} | weak:{' '}
                {hotLoadTrajectory.candidate_cards.weak_count} | draft:{' '}
                {hotLoadTrajectory.candidate_cards.draft_count}
              </div>
              <div>
                evidence: {hotLoadTrajectory.evidence.total_count} | quality:{' '}
                {hotLoadTrajectory.evidence.grounding_quality} | deep_research:{' '}
                {hotLoadTrajectory.evidence.deep_research_status}
              </div>
              <div>
                anchors:{' '}
                {hotLoadTrajectory.resolved_anchor_bundle.length
                  ? hotLoadTrajectory.resolved_anchor_bundle
                      .slice(0, 4)
                      .map((item) => item.label || item.kg_id)
                      .join(' | ')
                  : 'n/a'}
              </div>
              <div>
                verdicts:{' '}
                {Object.entries(hotLoadTrajectory.candidate_cards.verdict_counts)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(' | ') || 'n/a'}
              </div>
              <div>
                evidence_scope:{' '}
                {Object.entries(hotLoadTrajectory.candidate_cards.evidence_source_scope_counts)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(' | ') || 'n/a'}
              </div>
            </div>
          </details>
        ) : null}

        {evidence.length ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Evidence ({evidence.length})</summary>
            {evidenceMeta ? (
              <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                {evidenceMeta.deep_research_status === 'pending' ? (
                  <div className="font-medium text-amber-700">
                    Evidence updating
                    {evidenceMeta.pending_message ? `: ${evidenceMeta.pending_message}` : ''}
                  </div>
                ) : null}
                <div>
                  deep_research_status: {evidenceMeta.deep_research_status} | grounding_quality:{' '}
                  {evidenceMeta.grounding_quality} | fallback:{' '}
                  {evidenceMeta.is_fallback ? 'yes' : 'no'}
                </div>
                <div>
                  kg_injected: {evidenceMeta.kg_injected ? 'yes' : 'no'}
                  {evidenceMeta.kg_injection_truncated ? ' (truncated)' : ''}
                </div>
                {evidenceMeta.kg_injection_summary ? (
                  <div>kg summary: {evidenceMeta.kg_injection_summary}</div>
                ) : null}
                <div>
                  degenerate evidence: {evidenceMeta.degenerate_evidence ? 'yes' : 'no'}
                  {evidenceMeta.degenerate_evidence
                    ? ` | groups collapsed: ${evidenceMeta.dedupe_stats.collapsed_groups} (${evidenceMeta.dedupe_stats.before} -> ${evidenceMeta.dedupe_stats.after})`
                    : ''}
                </div>
                {evidenceMeta.degenerate_reason ? (
                  <div>degenerate reason: {evidenceMeta.degenerate_reason}</div>
                ) : null}
                <div>
                  source channels:{' '}
                  {Object.entries(evidenceMeta.source_stats.by_channel)
                    .map(([channel, n]) => `${channel}=${n}`)
                    .join(', ') || 'n/a'}
                </div>
                <div>
                  source quality:{' '}
                  {Object.entries(evidenceMeta.source_stats.by_quality)
                    .map(([tier, n]) => `${tier}=${n}`)
                    .join(', ') || 'n/a'}
                </div>
                <div>
                  research coverage: scanned={evidenceMeta.research_coverage_stats.scanned_sources} | passed=
                  {evidenceMeta.research_coverage_stats.qualifying_sources} | unique=
                  {evidenceMeta.research_coverage_stats.unique_after_dedupe} | final=
                  {evidenceMeta.research_coverage_stats.final_citable_sources} | discarded=
                  {evidenceMeta.research_coverage_stats.discarded_sources}
                </div>
                {reportHref ? (
                  <a
                    href={reportHref}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block text-blue-600 hover:underline"
                  >
                    Open Full Deep Research Report
                  </a>
                ) : null}
                {evidenceMeta.warnings.length ? (
                  <div>warnings: {evidenceMeta.warnings.slice(0, 2).join(' | ')}</div>
                ) : null}
              </div>
            ) : null}
            <div className="mt-2 space-y-2">
              {evidence.slice(0, 6).map((item) => (
                <div key={item.id} className="rounded border border-border/60 p-2">
                  <div className="font-medium">{item.label}</div>
                  <div className="text-muted-foreground">
                    {item.kind}
                    {item.source_channel ? ` | ${item.source_channel}` : ''}
                    {item.quality_tier ? ` | ${item.quality_tier}` : ''}
                    {item.path_type ? ` | ${item.path_type}` : ''}
                    {item.source_host ? ` | ${item.source_host}` : ''}
                  </div>
                  {item.summary ? <div className="text-muted-foreground mt-1">{item.summary}</div> : null}
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-block text-[11px] text-blue-600 hover:underline"
                    >
                      {item.display_url || item.url}
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
        ) : null}

        {kgCompare ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">KG Compare</summary>
            <div className="mt-2 space-y-2">
              {kgCompare.prior_art_match.length ? (
                <div>
                  <div className="font-medium">Prior Art Match</div>
                  <div className="text-muted-foreground">
                    {kgCompare.prior_art_match.join(' | ')}
                  </div>
                </div>
              ) : null}
              {kgCompare.novelty_gap.length ? (
                <div>
                  <div className="font-medium">Novelty Gap</div>
                  <div className="text-muted-foreground">{kgCompare.novelty_gap.join(' | ')}</div>
                </div>
              ) : null}
              {kgCompare.feasibility_constraints.length ? (
                <div>
                  <div className="font-medium">Feasibility Constraints</div>
                  <div className="text-muted-foreground">
                    {kgCompare.feasibility_constraints.join(' | ')}
                  </div>
                </div>
              ) : null}
              {kgCompare.novelty_taste?.structural_leverage?.length ? (
                <div>
                  <div className="font-medium">Structural Leverage</div>
                  <div className="text-muted-foreground">
                    {kgCompare.novelty_taste.structural_leverage.join(' | ')}
                  </div>
                </div>
              ) : null}
              {kgCompare.novelty_taste?.contradiction_motifs?.length ? (
                <div>
                  <div className="font-medium">Contradiction Motifs</div>
                  <div className="text-muted-foreground">
                    {kgCompare.novelty_taste.contradiction_motifs.join(' | ')}
                  </div>
                </div>
              ) : null}
              {kgCompare.novelty_taste?.ood_hypotheses?.length ? (
                <div>
                  <div className="font-medium">OOD Hypotheses</div>
                  <div className="text-muted-foreground">
                    {kgCompare.novelty_taste.ood_hypotheses.join(' | ')}
                  </div>
                </div>
              ) : null}
              {kgCompare.novelty_taste?.topology_shifts?.length ? (
                <div>
                  <div className="font-medium">Topology Shifts</div>
                  <div className="text-muted-foreground">
                    {kgCompare.novelty_taste.topology_shifts.join(' | ')}
                  </div>
                </div>
              ) : null}
            </div>
          </details>
        ) : null}

        {plan ? (
          <details className="rounded-md border border-border/70 p-2 text-xs mb-2">
            <summary className="cursor-pointer font-medium">Plan</summary>
            <div className="mt-2 space-y-2">
              <div>
                <div className="font-medium">MVP</div>
                <div className="text-muted-foreground">{plan.mvp_steps.join(' | ')}</div>
              </div>
              <div>
                <div className="font-medium">Falsifier</div>
                <div className="text-muted-foreground">{plan.falsifier}</div>
              </div>
            </div>
          </details>
        ) : null}

        {validation ? (
          <details className="rounded-md border border-border/70 p-2 text-xs">
            <summary className="cursor-pointer font-medium">Validation</summary>
            <div className="mt-2 space-y-1">
              <div>status: {validation.status}</div>
              <div>triage: {validation.triage.status}</div>
              {validation.triage.reason_codes.length ? (
                <div>reason codes: {validation.triage.reason_codes.join(', ')}</div>
              ) : null}
            </div>
          </details>
        ) : null}
      </CardContent>
    </Card>
  )
}
