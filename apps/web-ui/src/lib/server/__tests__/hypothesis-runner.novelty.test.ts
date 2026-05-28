import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const upsertArtifactMock = vi.fn()
const emitMetricMock = vi.fn()
const emitRunStateMock = vi.fn()
const emitStageMock = vi.fn()
const markRunCompletedMock = vi.fn()
const markRunFailedMock = vi.fn()

const getOrCreateSessionMock = vi.fn()
const exploreLocalSessionMock = vi.fn()

const runDeepResearchMock = vi.fn()

vi.mock('@/lib/server/hypothesis-run-store', () => ({
  emitMetric: emitMetricMock,
  emitRunState: emitRunStateMock,
  emitStage: emitStageMock,
  markRunCompleted: markRunCompletedMock,
  markRunFailed: markRunFailedMock,
  upsertArtifact: upsertArtifactMock,
}))

vi.mock('@/lib/server/hypothesis-local-store', () => ({
  getOrCreateLocalHypothesisSessionPersisted: getOrCreateSessionMock,
  exploreLocalHypothesisSession: exploreLocalSessionMock,
}))

vi.mock('@/lib/server/hypothesis-research-adapter', async () => {
  const actual = await vi.importActual<typeof import('@/lib/server/hypothesis-research-adapter')>(
    '@/lib/server/hypothesis-research-adapter',
  )
  return {
    ...actual,
    runDeepResearch: runDeepResearchMock,
  }
})

const fetchMock = vi.fn()

function toolSuccessPayload(payload: Record<string, unknown>) {
  return new Response(
    JSON.stringify({
      result: {
        status: 'success',
        data: {
          data: payload,
        },
      },
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  )
}

describe('executeHypothesisRun novelty tool integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    process.env.HYPOTHESIS_KG_NOVELTY_TOOLS_ENABLED = '1'

    getOrCreateSessionMock.mockResolvedValue({
      session_id: 'session-test-001',
      context: {
        dataset_id: 'ds:manual:nsd',
        concept_id: 'trm_measurement_invariance',
        task_id: 'task_switching',
      },
    })
    exploreLocalSessionMock.mockReturnValue({
      candidates: [{ id: 'local-1' }, { id: 'local-2' }],
    })

    runDeepResearchMock.mockResolvedValue({
      summary: 'Deep research found usable evidence anchors.',
      evidence: [
        {
          id: 'ev-primary-1',
          label: 'Task-fMRI study with construct mapping',
          kind: 'paper',
          summary: 'Compares cognitive-control tasks under harmonized GLM settings.',
          source_channel: 'deep_research_live',
          confidence: 0.88,
          quality_tier: 'primary',
          traceability_score: 0.86,
          url: 'https://example.org/paper1',
        },
        {
          id: 'ev-primary-2',
          label: 'Cross-dataset benchmark report',
          kind: 'paper',
          summary: 'Shows task-choice sensitivity in brain-behavior coupling.',
          source_channel: 'deep_research_live',
          confidence: 0.84,
          quality_tier: 'primary',
          traceability_score: 0.83,
          url: 'https://example.org/paper2',
        },
      ],
      qualityGate: {
        min_citable_sources: 2,
        min_primary_sources: 1,
        citable_count: 2,
        primary_count: 2,
        pass: true,
        low_confidence: false,
        reason: null,
      },
      fallbackPath: 'none',
      report: null,
      degenerateEvidence: {
        degenerate: false,
        reason: null,
        mode: 'none',
        dedupeStats: {
          before: 2,
          after: 2,
          collapsedGroups: 0,
        },
      },
    })

    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      const raw = typeof init?.body === 'string' ? init.body : '{}'
      const parsed = JSON.parse(raw) as { tool?: string; arguments?: Record<string, unknown> }
      const tool = parsed.tool

      if (tool === 'task_to_concept_mapping') {
        return toolSuccessPayload({
          matched_task: 'task switching',
          concepts: ['concept:cognitive_control', 'concept:performance_monitoring'],
          synonyms: ['task-switching', 'set-shifting'],
        })
      }

      if (tool === 'kg_multihop_qa') {
        return toolSuccessPayload({
          answer: 'Mapped concepts show partial replication with method-sensitive branches.',
          summary: { n_paths: 3, hops_used: 2 },
          warnings: [],
        })
      }

      if (tool === 'kg_probe') {
        const args = (parsed.arguments || {}) as Record<string, unknown>
        if (args.probe_type === 'structural_leverage') {
          return toolSuccessPayload({
            ok: true,
            result: {
              items: [
                { label: 'bridge:rt-aware-glm' },
                { label: 'bridge:parcellation-switch' },
              ],
            },
            warnings: [],
          })
        }

        if (args.probe_type === 'contradiction_motifs') {
          return toolSuccessPayload({
            ok: true,
            result: {
              motifs: [
                {
                  publication_label: 'Motif paper',
                  support_count: 2,
                  conflict_count: 1,
                },
              ],
            },
            warnings: [],
          })
        }
      }

      if (tool === 'kg_hypothesis_workflow') {
        const args = (parsed.arguments || {}) as Record<string, unknown>
        if (args.operation === 'sample') {
          return toolSuccessPayload({
            ok: true,
            result: {
              hypotheses: [
                { statement: 'OOD path: RT-aware GLM × task-switching dissociation.' },
                { statement: 'OOD path: cross-atlas mismatch predicts slope sign reversal.' },
              ],
            },
            warnings: [],
          })
        }
      }

      if (tool === 'kg_detect_topology_shifts') {
        return toolSuccessPayload({
          ok: true,
          result: {
            proposals: [
              {
                edge: {
                  source_id: 'paper:a',
                  rel_type: 'MENTIONS',
                  target_id: 'concept:cognitive_control',
                },
                delta: -0.12,
              },
            ],
          },
          warnings: [],
        })
      }

      if (tool === 'kg_hypothesis_candidate_cards') {
        return toolSuccessPayload({
          ok: true,
          result: {
            query: 'RDoC cognitive control construct invariance',
            candidate_cards: [
              {
                card_id: 'mcp-cand-1',
                title: 'Bridge control candidate',
                hypothesis: 'Bridge hypothesis anchored in structural leverage.',
                taste_axis: 'bridge_disconnected_regions',
                minimal_discriminating_test:
                  'Use the smallest available dataset split to test whether candidate performance shifts.',
                falsifier_hint:
                  'If the bridge signal disappears under matched controls, reject the candidate.',
                contradiction_probe: 'Probe contradiction motifs across preprocessing choices.',
                topology_shift_probe: 'Probe topology shifts after tightening filters.',
                kg_verification: {
                  verdict: 'insufficient_evidence',
                  confidence: 0.36,
                },
                novelty_signals: {
                  controlled_ood_score: 0.72,
                },
                topology_subgraph: {
                  focus_node_id: 'drn_focus_bridge',
                },
                provenance: {
                  relation_hint: 'ASSOCIATED_WITH',
                },
              },
            ],
            ephemeral_weighted_subgraph: {
              summary: {
                node_count: 4,
                edge_count: 3,
                card_subgraph_count: 1,
              },
            },
            summary: {
              n_candidate_cards: 1,
              n_grounded_cards: 0,
              n_degraded_cards: 0,
              candidate_lane_mode: 'broad',
              deep_research_requested: false,
            },
            warnings: [],
          },
        })
      }

      return new Response(JSON.stringify({ result: { status: 'error', error: `unknown tool ${tool}` } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })

    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    delete process.env.HYPOTHESIS_KG_NOVELTY_TOOLS_ENABLED
  })

  it('propagates novelty tool signals into candidate_cards with new fields', async () => {
    const { executeHypothesisRun } = await import('@/lib/server/hypothesis-runner')

    await executeHypothesisRun({
      runId: 'hrun-test-novelty-001',
      sessionId: 'session-test-001',
      intentSummary: {
        term: 'RDoC cognitive control construct invariance',
        goal: 'replication_dispute',
        modality: 'fmri_task',
        population: 'healthy_adults',
        output_mode: 'three_options',
        intent_ready: true,
        missing_fields: [],
      },
      nCandidates: 4,
    })

    const toolCalls = fetchMock.mock.calls
      .map(([, init]) => {
        const raw = typeof init?.body === 'string' ? init.body : '{}'
        const parsed = JSON.parse(raw) as { tool?: string }
        return parsed.tool || ''
      })
      .filter(Boolean)

    expect(toolCalls).toContain('kg_probe')
    expect(toolCalls).toContain('kg_hypothesis_workflow')
    expect(toolCalls).toContain('kg_hypothesis_candidate_cards')
    expect(toolCalls).not.toContain('kg_find_structural_leverage')
    expect(toolCalls).not.toContain('kg_sample_ood_hypothesis')
    expect(toolCalls).not.toContain('kg_detect_contradiction_motifs')

    const requestBodies = fetchMock.mock.calls
      .map(([, init]) => {
        const raw = typeof init?.body === 'string' ? init.body : '{}'
        return JSON.parse(raw) as { tool?: string; arguments?: Record<string, unknown> }
      })
      .filter((payload) => payload.tool === 'kg_probe' || payload.tool === 'kg_hypothesis_workflow')

    expect(requestBodies).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          tool: 'kg_probe',
          arguments: expect.objectContaining({
            probe_type: 'structural_leverage',
          }),
        }),
        expect.objectContaining({
          tool: 'kg_probe',
          arguments: expect.objectContaining({
            probe_type: 'contradiction_motifs',
          }),
        }),
        expect.objectContaining({
          tool: 'kg_hypothesis_workflow',
          arguments: expect.objectContaining({
            operation: 'sample',
          }),
        }),
      ]),
    )

    const artifactCalls = upsertArtifactMock.mock.calls
    const candidateArtifactCall = artifactCalls.find(
      (call) => call[1]?.kind === 'candidate_cards',
    )
    expect(candidateArtifactCall).toBeTruthy()

    const candidatePayload = candidateArtifactCall?.[1]?.payload as {
      items: Array<Record<string, unknown>>
      diagnostics: Record<string, unknown>
    }

    expect(Array.isArray(candidatePayload.items)).toBe(true)
    expect(candidatePayload.items.length).toBeGreaterThan(0)

    const first = candidatePayload.items[0]
    expect(first.title).toBe('Bridge control candidate')
    expect(typeof first.minimal_discriminating_test).toBe('string')
    expect((first.minimal_discriminating_test as string).length).toBeGreaterThan(20)
    expect(typeof first.falsifier_hint).toBe('string')
    expect((first.falsifier_hint as string).length).toBeGreaterThan(20)
    expect(typeof first.taste_axis).toBe('string')
    expect((first.taste_axis as string).length).toBeGreaterThan(0)

    const kgCompareArtifactCall = artifactCalls.find(
      (call) => call[1]?.kind === 'kg_compare',
    )
    expect(kgCompareArtifactCall).toBeTruthy()
    const kgPayload = kgCompareArtifactCall?.[1]?.payload as {
      novelty_taste?: {
        structural_leverage?: string[]
        ood_hypotheses?: string[]
      }
    }
    expect(kgPayload.novelty_taste?.structural_leverage?.length).toBeGreaterThan(0)
    expect(kgPayload.novelty_taste?.ood_hypotheses?.length).toBeGreaterThan(0)
  })
})
