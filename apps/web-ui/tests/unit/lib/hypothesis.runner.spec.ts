import { beforeEach, describe, expect, it, vi } from 'vitest'

const runStoreFns = vi.hoisted(() => ({
  emitMetric: vi.fn(),
  emitRunState: vi.fn(),
  emitStage: vi.fn(),
  markRunCompleted: vi.fn(),
  markRunFailed: vi.fn(),
  upsertArtifact: vi.fn(),
}))

vi.mock('@/lib/server/hypothesis-local-store', () => ({
  exploreLocalHypothesisSession: vi.fn(() => ({
    candidates: [{ id: 'c-1' }],
  })),
  getOrCreateLocalHypothesisSessionPersisted: vi.fn(async () => ({
    session_id: 's-1',
    context: {
      dataset_id: null,
      concept_id: null,
      task_id: null,
    },
  })),
}))

vi.mock('@/lib/server/hypothesis-research-adapter', () => ({
  DEEP_RESEARCH_ERROR_CODES: {
    EMPTY_QUERY: 'deep_research_empty_query',
    TOOL_NOT_FOUND: 'deep_research_tool_not_found',
    TERMINAL_FAILURE_STATE: 'deep_research_terminal_failure_state',
    MAX_POLLS_EXCEEDED: 'deep_research_max_polls_exceeded',
    BACKGROUND_CAP_EXCEEDED: 'deep_research_background_cap_exceeded',
    MISSING_INTERACTION_ID: 'deep_research_missing_interaction_id',
    TRANSIENT_TOOL_FAILURE: 'deep_research_transient_tool_failure',
    REQUEST_FAILED: 'deep_research_request_failed',
  },
  getDeepResearchErrorCode: vi.fn((error: unknown) => {
    if (!error || typeof error !== 'object') return null
    const code = (error as { code?: unknown }).code
    return typeof code === 'string' ? code : null
  }),
  runDeepResearch: vi.fn(async () => ({
    status: 'completed',
    interactionId: 'int-default',
    idempotencyKey: 'idem-default',
    summary: 'Default deep research evidence.',
    evidence: [
      {
        id: 'ev-default-1',
        label: 'Default deep research paper',
        kind: 'paper',
        url: 'https://example.org/default-paper',
        source_channel: 'deep_research_live',
        quality_tier: 'secondary',
        traceability_score: 0.82,
      },
    ],
    degenerateEvidence: {
      degenerate: false,
      mode: 'none',
      reason: null,
      dedupeStats: {
        before: 1,
        after: 1,
        collapsedGroups: 0,
      },
    },
  })),
  runKgHypothesisCandidateCards: vi.fn(async () => ({
    query: 'brain decoding',
    resolvedAnchorBundle: [
      {
        kg_id: 'concept:brain_decoding',
        label: 'Brain decoding',
        node_type: 'Concept',
        matched_queries: ['brain decoding'],
        score: 0.88,
        rank: 1,
        raw: {
          kg_id: 'concept:brain_decoding',
          label: 'Brain decoding',
          node_type: 'Concept',
          matched_queries: ['brain decoding'],
          score: 0.88,
          rank: 1,
        },
      },
    ],
    candidateCards: [
      {
        card_id: 'mcp-cand-1',
        title: 'MCP Candidate 1',
        hypothesis: 'MCP-backed hypothesis',
        taste_axis: 'controlled_ood_search',
        minimal_discriminating_test: 'Run the smallest controlled split first.',
        falsifier_hint: 'Reject if the effect disappears under matched controls.',
        contradiction_probe: 'Check whether contradiction motifs survive preprocessing variants.',
        topology_shift_probe: 'Check whether topology shift proposals survive filtering.',
        grounding_status: null,
        evidence_summary: null,
        deep_research_status: null,
        deep_research_error: null,
        kg_verification: { verdict: 'insufficient_evidence', confidence: 0.41 },
        novelty_signals: { controlled_ood_score: 0.66 },
        topology_subgraph: { focus_node_id: 'drn_focus' },
        provenance: { relation_hint: 'ASSOCIATED_WITH' },
        raw: {},
      },
    ],
    summary: {
      nCandidateCards: 1,
      nGroundedCards: 0,
      nDegradedCards: 0,
      candidateLaneMode: 'broad',
      deepResearchRequested: false,
    },
    workflow: { workflow_id: 'workflow_hypothesis_candidate_cards' },
    deepResearch: null,
    ephemeralWeightedSubgraph: {
      summary: {
        node_count: 4,
        edge_count: 3,
        card_subgraph_count: 1,
      },
    },
    warnings: [],
  })),
  runKgCompare: vi.fn(async () => ({
    priorArtMatch: [],
    noveltyGap: [],
    feasibilityConstraints: [],
    warnings: [],
    concepts: [],
    multihopAttempts: 0,
  })),
}))

vi.mock('@/lib/hypothesis-workflow', () => ({
  buildSuggestedCanvas: vi.fn(() => ({
    term: 'brain decoding',
    goal: 'predictive_modeling',
    modality: 'fmri_task',
    population: 'unspecified',
  })),
  buildGroundedDirectionCandidates: vi.fn(() => [
    {
      id: 'cand-1',
      title: 'Candidate 1',
      hypothesis: 'Draft hypothesis',
      grounding_status: 'draft_unverified',
      confidence: 0.42,
      pattern_id: 'pattern-1',
      pattern_label: 'Pattern 1',
      claim: 'Claim 1',
      evidence_anchors: [],
      fallback_reasons: [],
      share_allowed: false,
      independent_variable: 'iv',
      dependent_variable: 'dv',
      expected_signal: 'positive',
      likely_data_source: 'dataset',
      novelty_gap: 'gap',
      risk_note: 'risk',
    },
  ]),
  buildGroundedDirectionCandidatesWithTrace: vi.fn(() => ({
    mode: 'template_fallback',
    facts: [],
    clusters: [],
    diagnostics: {
      anchor_pool_size: 1,
      unique_anchor_dims: 1,
      pattern_reuse_count: 0,
      diversity_resample_count: 0,
      diversity_exhausted_slots: 0,
      qualifying_evidence_count: 0,
      distinct_qualifying_docs: 0,
    },
    candidates: [
      {
        id: 'cand-1',
        title: 'Candidate 1',
        hypothesis: 'Draft hypothesis',
        grounding_status: 'draft_unverified',
        confidence: 0.42,
        pattern_id: 'pattern-1',
        pattern_label: 'Pattern 1',
        claim: 'Claim 1',
        evidence_anchors: [],
        fallback_reasons: [],
        share_allowed: false,
        anchor_dim: 'General hypothesis gap',
        anchor_source: 'hybrid',
        anchor_evidence_ids: [],
        diversity_retry_count: 0,
        independent_variable: 'iv',
        dependent_variable: 'dv',
        expected_signal: 'positive',
        likely_data_source: 'dataset',
        novelty_gap: 'gap',
        risk_note: 'risk',
      },
    ],
  })),
  buildResearchPreview: vi.fn(() => ({ summary: 'preview' })),
  buildWorkflowPlan: vi.fn(() => ({ steps: [] })),
  evaluateWorkflowPlan: vi.fn(() => ({ valid: true, warnings: [] })),
}))

vi.mock('@/lib/server/hypothesis-run-store', () => runStoreFns)

import { executeHypothesisRun } from '@/lib/server/hypothesis-runner'
import {
  DEEP_RESEARCH_ERROR_CODES,
  runDeepResearch,
  runKgHypothesisCandidateCards,
  runKgCompare,
} from '@/lib/server/hypothesis-research-adapter'

describe('executeHypothesisRun', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('waits for deep research completion before synthesizing candidates', async () => {
    vi.mocked(runDeepResearch).mockImplementationOnce(
      async () =>
        await new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                status: 'completed',
                interactionId: 'int-delayed',
                idempotencyKey: 'idem-delayed',
                summary: 'Delayed deep research evidence.',
                evidence: [
                  {
                    id: 'ev-delayed-1',
                    label: 'Delayed paper',
                    kind: 'paper',
                    url: 'https://example.org/delayed-paper',
                    source_channel: 'deep_research_live',
                    quality_tier: 'primary',
                    traceability_score: 0.9,
                  },
                ],
                degenerateEvidence: {
                  degenerate: false,
                  mode: 'none',
                  reason: null,
                  dedupeStats: { before: 1, after: 1, collapsedGroups: 0 },
                },
                qualityGate: {
                  min_citable_sources: 2,
                  min_primary_sources: 1,
                  citable_count: 1,
                  primary_count: 1,
                  pass: true,
                  low_confidence: false,
                  reason: null,
                },
                fallbackPath: 'none',
              }),
            1200,
          )
        }),
    )

    const started = Date.now()

    await executeHypothesisRun({
      runId: 'hrun-test',
      sessionId: 'session-test',
      intentSummary: {
        term: 'brain decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'unspecified',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    const elapsedMs = Date.now() - started
    expect(elapsedMs).toBeGreaterThanOrEqual(1000)
    expect(elapsedMs).toBeLessThan(5000)
    expect(runStoreFns.markRunCompleted).toHaveBeenCalledTimes(1)
    expect(runStoreFns.markRunCompleted.mock.calls[0]?.[1]).toMatch(/evidence is fully updated/i)
    expect(runStoreFns.markRunFailed).not.toHaveBeenCalled()

    const evidenceUpserts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'evidence-pack')
    expect(evidenceUpserts.length).toBeGreaterThan(0)
    const lastEvidence = evidenceUpserts[evidenceUpserts.length - 1]?.payload
    expect(lastEvidence?.deep_research_status).toBe('ready')

    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.diagnostics?.deep_research_pending).toBe(false)
  })

  it('uses MCP candidate-card payload as the primary synthesis path', async () => {
    await executeHypothesisRun({
      runId: 'hrun-mcp-cards',
      sessionId: 'session-mcp-cards',
      intentSummary: {
        term: 'brain decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'unspecified',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    expect(runKgHypothesisCandidateCards).toHaveBeenCalledTimes(1)
    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.items?.[0]?.title).toBe('MCP Candidate 1')
    expect(lastCards?.items?.[0]?.minimal_discriminating_test).toContain('smallest controlled split')
    expect(lastCards?.diagnostics?.workflow_id).toBe('workflow_hypothesis_candidate_cards')
    expect(lastCards?.diagnostics?.candidate_lane_mode).toBe('broad')
    expect(lastCards?.diagnostics?.mcp_fallback_used).toBe(false)

    const hotLoadTrajectory = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'hot-load-trajectory')
    const lastTrajectory = hotLoadTrajectory[hotLoadTrajectory.length - 1]?.payload
    expect(lastTrajectory?.query).toBe('brain decoding')
    expect(lastTrajectory?.workflow?.workflow_id).toBe('workflow_hypothesis_candidate_cards')
    expect(lastTrajectory?.workflow?.verification_source).toBe('mcp_workflow')
    expect(lastTrajectory?.resolved_anchor_bundle?.[0]?.kg_id).toBe('concept:brain_decoding')
    expect(lastTrajectory?.candidate_cards?.verdict_counts).toEqual({
      insufficient_evidence: 1,
    })
  })

  it('marks mcp_fallback_used when MCP candidate-card generation degrades to local synthesis', async () => {
    vi.mocked(runKgHypothesisCandidateCards).mockRejectedValueOnce(
      new Error('kg_hypothesis_candidate_cards unavailable'),
    )

    await executeHypothesisRun({
      runId: 'hrun-mcp-fallback',
      sessionId: 'session-mcp-fallback',
      intentSummary: {
        term: 'brain decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'unspecified',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.diagnostics?.workflow_id).toBeNull()
    expect(lastCards?.diagnostics?.candidate_lane_mode).toBeNull()
    expect(lastCards?.diagnostics?.mcp_fallback_used).toBe(true)

    const hotLoadTrajectory = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'hot-load-trajectory')
    const lastTrajectory = hotLoadTrajectory[hotLoadTrajectory.length - 1]?.payload
    expect(lastTrajectory?.workflow?.mcp_fallback_used).toBe(true)
    expect(lastTrajectory?.workflow?.verification_source).toBe('local_fallback')
    expect(lastTrajectory?.resolved_anchor_bundle).toEqual([])
  })

  it('aligns evidence grounding_quality with candidate-level grounding summary', async () => {
    vi.mocked(runDeepResearch).mockResolvedValueOnce({
      status: 'completed',
      interactionId: 'int-ready',
      idempotencyKey: 'idem-ready',
      summary: 'Deep research completed with citeable evidence.',
      evidence: [
        {
          id: 'ev-1',
          label: 'PubMed evidence',
          kind: 'paper',
          url: 'https://pubmed.ncbi.nlm.nih.gov/40800852',
          source_channel: 'deep_research_live',
          quality_tier: 'primary',
          traceability_score: 0.92,
        },
      ],
      degenerateEvidence: {
        degenerate: true,
        mode: 'soft_keep_top1',
        reason: 'Detected repeated evidence title group(s); kept top-ranked source per group.',
        dedupeStats: {
          before: 4,
          after: 1,
          collapsedGroups: 1,
        },
      },
      qualityGate: {
        min_citable_sources: 2,
        min_primary_sources: 1,
        citable_count: 1,
        primary_count: 1,
        pass: false,
        low_confidence: true,
        reason: 'Evidence gate unmet for test fixture.',
      },
      fallbackPath: 'sync_after_quality_gate',
    })

    await executeHypothesisRun({
      runId: 'hrun-align',
      sessionId: 'session-align',
      intentSummary: {
        term: 'brain decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'unspecified',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    const evidenceUpserts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'evidence-pack')
    const lastEvidence = evidenceUpserts[evidenceUpserts.length - 1]?.payload

    expect(lastEvidence?.deep_research_status).toBe('ready')
    expect(lastEvidence?.degenerate_evidence).toBe(true)
    expect(lastEvidence?.dedupe_stats?.collapsed_groups).toBe(1)
    expect(lastEvidence?.grounding_quality).toBe('draft_unverified')
    expect(Array.isArray(lastEvidence?.warnings)).toBe(true)
    expect(
      (lastEvidence?.warnings || []).some((line: string) =>
        /aligned to candidate-level evidence anchors/i.test(line),
      ),
    ).toBe(true)

    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.diagnostics?.degenerate_evidence).toBe(true)
    expect(lastCards?.diagnostics?.degenerate_mode).toBe('soft_keep_top1')
  })

  it('injects KG priors into deep research query when KG-first compare succeeds', async () => {
    vi.mocked(runKgCompare).mockResolvedValueOnce({
      priorArtMatch: ['Closest mapped task in KG: affective spatial cueing.'],
      noveltyGap: ['KG multihop returned 3 path(s) for this query.'],
      feasibilityConstraints: ['Current evidence graph resolves within ~2 hop(s).'],
      warnings: [],
      concepts: ['amygdala', 'approach bias'],
      multihopAttempts: 1,
      noveltyTaste: {
        structuralLeverage: [],
        contradictionMotifs: [],
        oodHypotheses: [],
        topologyShifts: [],
      },
    })
    vi.mocked(runDeepResearch).mockResolvedValueOnce({
      status: 'completed',
      interactionId: 'int-kg-first',
      idempotencyKey: 'idem-kg-first',
      summary: 'Deep research completed with KG-guided evidence.',
      evidence: [
        {
          id: 'ev-kg-1',
          label: 'KG-guided evidence',
          kind: 'paper',
          url: 'https://doi.org/10.1016/j.neuroimage.2025.120001',
          source_channel: 'deep_research_live',
          quality_tier: 'primary',
          traceability_score: 0.9,
        },
      ],
      degenerateEvidence: {
        degenerate: false,
        mode: 'none',
        reason: null,
        dedupeStats: {
          before: 1,
          after: 1,
          collapsedGroups: 0,
        },
      },
      qualityGate: {
        min_citable_sources: 2,
        min_primary_sources: 1,
        citable_count: 1,
        primary_count: 1,
        pass: true,
        low_confidence: false,
        reason: null,
      },
      fallbackPath: 'none',
    })

    await executeHypothesisRun({
      runId: 'hrun-kg-first',
      sessionId: 'session-kg-first',
      intentSummary: {
        term: 'approach avoidance task',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
      kgOrchestrationOptions: {
        kgFirst: true,
        timeoutSec: 90,
        promptTopK: 6,
        promptMaxChars: 1200,
      },
    })

    const deepResearchCall = vi.mocked(runDeepResearch).mock.calls[0]?.[0]
    expect(deepResearchCall?.query).toContain(
      'BR-KG priors from deterministic graph traversal',
    )
    expect(deepResearchCall?.query).toContain('Mapped concepts: amygdala, approach bias')

    const evidenceUpserts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'evidence-pack')
    const lastEvidence = evidenceUpserts[evidenceUpserts.length - 1]?.payload
    expect(lastEvidence?.kg_injected).toBe(true)
    expect(lastEvidence?.kg_injection_summary).toBeTruthy()

    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.diagnostics?.kg_first_used).toBe(true)
    expect(lastCards?.diagnostics?.kg_injection_tokens_est).toBeGreaterThan(0)
  })

  it('marks kg_timeout_applied and skips KG prompt injection when KG-first compare times out', async () => {
    vi.mocked(runKgCompare).mockRejectedValueOnce(
      new Error('KG compare timed out after 90s; continuing without KG priors.'),
    )
    vi.mocked(runDeepResearch).mockResolvedValueOnce({
      status: 'completed',
      interactionId: 'int-no-kg',
      idempotencyKey: 'idem-no-kg',
      summary: 'Deep research completed without KG priors.',
      evidence: [
        {
          id: 'ev-no-kg-1',
          label: 'Unguided evidence',
          kind: 'paper',
          url: 'https://example.org/no-kg',
          source_channel: 'deep_research_live',
          quality_tier: 'secondary',
          traceability_score: 0.8,
        },
      ],
      degenerateEvidence: {
        degenerate: false,
        mode: 'none',
        reason: null,
        dedupeStats: {
          before: 1,
          after: 1,
          collapsedGroups: 0,
        },
      },
      qualityGate: {
        min_citable_sources: 2,
        min_primary_sources: 1,
        citable_count: 1,
        primary_count: 0,
        pass: false,
        low_confidence: true,
        reason: 'Primary source threshold unmet.',
      },
      fallbackPath: 'sync_after_quality_gate',
    })

    await executeHypothesisRun({
      runId: 'hrun-kg-timeout',
      sessionId: 'session-kg-timeout',
      intentSummary: {
        term: 'fmri decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
      kgOrchestrationOptions: {
        kgFirst: true,
        timeoutSec: 90,
      },
    })

    const deepResearchCall = vi.mocked(runDeepResearch).mock.calls[0]?.[0]
    expect(deepResearchCall?.query).not.toContain(
      'BR-KG priors from deterministic graph traversal',
    )

    const evidenceUpserts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'evidence-pack')
    const lastEvidence = evidenceUpserts[evidenceUpserts.length - 1]?.payload
    expect(lastEvidence?.kg_injected).toBe(false)

    const candidateCards = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'candidate-cards')
    const lastCards = candidateCards[candidateCards.length - 1]?.payload
    expect(lastCards?.diagnostics?.kg_timeout_applied).toBe(true)
    expect(lastCards?.diagnostics?.kg_injection_tokens_est).toBe(0)
  })

  it('emits deep_research_timeout metric when deep research fails with typed timeout-like code', async () => {
    const error = new Error('Deep research exceeded polling budget.') as Error & {
      code?: string
    }
    error.code = DEEP_RESEARCH_ERROR_CODES.MAX_POLLS_EXCEEDED
    vi.mocked(runDeepResearch).mockRejectedValueOnce(error)

    await executeHypothesisRun({
      runId: 'hrun-dr-timeout',
      sessionId: 'session-dr-timeout',
      intentSummary: {
        term: 'fmri decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    expect(runStoreFns.emitMetric).toHaveBeenCalledWith('hrun-dr-timeout', 'deep_research_timeout', 1)
  })

  it('emits deep_research_missing_ids metric when deep research fails with typed missing-id code', async () => {
    const error = new Error('Deep research missing interaction identifiers.') as Error & {
      code?: string
    }
    error.code = DEEP_RESEARCH_ERROR_CODES.MISSING_INTERACTION_ID
    vi.mocked(runDeepResearch).mockRejectedValueOnce(error)

    await executeHypothesisRun({
      runId: 'hrun-dr-missing-ids',
      sessionId: 'session-dr-missing-ids',
      intentSummary: {
        term: 'fmri decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    expect(runStoreFns.emitMetric).toHaveBeenCalledWith(
      'hrun-dr-missing-ids',
      'deep_research_missing_ids',
      1,
    )
  })

  it('persists deep research report artifact and exposes report metadata in evidence pack', async () => {
    vi.mocked(runDeepResearch).mockResolvedValueOnce({
      status: 'completed',
      interactionId: 'int-report',
      idempotencyKey: 'idem-report',
      summary: 'Detailed deep research summary.',
      evidence: [
        {
          id: 'ev-report-1',
          label: 'Report evidence',
          kind: 'paper',
          url: 'https://example.org/report-evidence',
          source_channel: 'deep_research_live',
          quality_tier: 'primary',
          traceability_score: 0.91,
        },
      ],
      degenerateEvidence: {
        degenerate: false,
        mode: 'none',
        reason: null,
        dedupeStats: { before: 1, after: 1, collapsedGroups: 0 },
      },
      qualityGate: {
        min_citable_sources: 2,
        min_primary_sources: 1,
        citable_count: 1,
        primary_count: 1,
        pass: true,
        low_confidence: false,
        reason: null,
      },
      fallbackPath: 'none',
      report: {
        query: 'report query',
        status: 'completed',
        source_run_id: 'br-report-source',
        interaction_id: 'int-report',
        idempotency_key: 'idem-report',
        summary: 'Calibrated claim summary.',
        synthesis_full_text: '## Calibrated Claim Review\n\nCalibrated claim summary.',
        raw_summary: 'Detailed deep research summary.',
        raw_synthesis_full_text: 'Long-form synthesis body.',
        claim_review: {
          source_run_id: 'br-report-source',
          source_artifact: 'claim_report.json',
          summary: 'Calibrated claim summary.',
          overall_verdict: 'indirectly_supported',
          caveats: ['No direct matched contrast was available.'],
          unresolved_questions: ['Direction conflict remains unresolved.'],
          claim_count: 1,
          rendered_markdown: '## Calibrated Claim Review\n\nCalibrated claim summary.',
        },
        synthesis_generated_by: 'upstream',
        synthesis_source_count: 1,
        search_trails: [
          { stage: 'start', tool: 'deep_research', status: 'running', detail: null },
          { stage: 'poll', tool: 'deep_research', status: 'completed', detail: null },
        ],
        historical_trails_available: true,
        source_inventory: [],
        discarded_sources: [],
        discarded_aggregates: [],
        quality_gate: {
          min_citable_sources: 2,
          min_primary_sources: 1,
          citable_count: 1,
          primary_count: 1,
          pass: true,
          low_confidence: false,
          reason: null,
        },
        fallback_path: 'none',
        search_stats: {
          scanned_count: 8,
          qualifying_count: 4,
          unique_after_dedupe_count: 3,
          final_citable_count: 1,
          discarded_count: 5,
        },
        generated_at: new Date().toISOString(),
      },
    })

    await executeHypothesisRun({
      runId: 'hrun-report',
      sessionId: 'session-report',
      intentSummary: {
        term: 'fmri decoding',
        goal: 'predictive_modeling',
        modality: 'fmri_task',
        population: 'healthy adults',
        output_mode: null,
        intent_ready: true,
        missing_fields: [],
      },
      deepResearchOptions: {
        uiWaitSec: 1,
      },
    })

    const reportArtifacts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.kind === 'deep_research_report')
    expect(reportArtifacts.length).toBeGreaterThan(0)

    const evidenceUpserts = runStoreFns.upsertArtifact.mock.calls
      .map((call) => call?.[1])
      .filter((artifact) => artifact?.id === 'evidence-pack')
    const lastEvidence = evidenceUpserts[evidenceUpserts.length - 1]?.payload
    expect(lastEvidence?.deep_research_report_available).toBe(true)
    expect(lastEvidence?.deep_research_report_artifact_id).toBe('deep-research-report')
    expect(lastEvidence?.research_coverage_stats?.scanned_sources).toBe(8)
    expect(lastEvidence?.research_coverage_stats?.discarded_sources).toBe(5)
  })
})
