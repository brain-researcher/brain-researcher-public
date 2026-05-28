import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEEP_RESEARCH_ERROR_CODES,
  getDeepResearchErrorCode,
  runDeepResearch,
  runKgHypothesisCandidateCards,
  runKgCompare,
} from '@/lib/server/hypothesis-research-adapter'
import { makeJsonResponse, makeToolSuccessResponse } from '../helpers/fetch-mocks'

describe('hypothesis research adapter: KG compare', () => {
  const originalFetch = global.fetch
  const originalKgMultihopTimeout = process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS
  const originalEvidenceEnrich = process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_ENRICH
  const originalDeepResearchTransientRetries = process.env.HYPOTHESIS_DEEP_RESEARCH_TRANSIENT_RETRIES
  const originalDeepResearchRetryBaseMs = process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_BASE_MS
  const originalDeepResearchRetryMaxMs = process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_MAX_MS
  const originalEvidenceUrlResolveMaxDocs = process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS
  const originalIdentifierValidation = process.env.HYPOTHESIS_IDENTIFIER_VALIDATION
  const originalDeepResearchMinCitable = process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_CITABLE_SOURCES
  const originalDeepResearchMinPrimary = process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_PRIMARY_SOURCES

  beforeEach(() => {
    process.env.HYPOTHESIS_IDENTIFIER_VALIDATION = '0'
    process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_CITABLE_SOURCES = '1'
    process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_PRIMARY_SOURCES = '0'
  })

  afterEach(() => {
    global.fetch = originalFetch
    if (originalKgMultihopTimeout === undefined) {
      delete process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS
    } else {
      process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS = originalKgMultihopTimeout
    }
    if (originalEvidenceEnrich === undefined) {
      delete process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_ENRICH
    } else {
      process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_ENRICH = originalEvidenceEnrich
    }
    if (originalDeepResearchTransientRetries === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_TRANSIENT_RETRIES
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_TRANSIENT_RETRIES = originalDeepResearchTransientRetries
    }
    if (originalDeepResearchRetryBaseMs === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_BASE_MS
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_BASE_MS = originalDeepResearchRetryBaseMs
    }
    if (originalDeepResearchRetryMaxMs === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_MAX_MS
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_MAX_MS = originalDeepResearchRetryMaxMs
    }
    if (originalEvidenceUrlResolveMaxDocs === undefined) {
      delete process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS
    } else {
      process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS = originalEvidenceUrlResolveMaxDocs
    }
    if (originalIdentifierValidation === undefined) {
      delete process.env.HYPOTHESIS_IDENTIFIER_VALIDATION
    } else {
      process.env.HYPOTHESIS_IDENTIFIER_VALIDATION = originalIdentifierValidation
    }
    if (originalDeepResearchMinCitable === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_CITABLE_SOURCES
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_CITABLE_SOURCES = originalDeepResearchMinCitable
    }
    if (originalDeepResearchMinPrimary === undefined) {
      delete process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_PRIMARY_SOURCES
    } else {
      process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_PRIMARY_SOURCES = originalDeepResearchMinPrimary
    }
    vi.restoreAllMocks()
  })

  it('parses deep research state from outputs payload shape', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-1',
                idempotency_key: 'idem-1',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Latest FMRI decoding review.',
                  documents: [
                    {
                      doc_id: 'doc-1',
                      title: 'Paper A',
                      url: 'https://example.org/a',
                      snippets: ['Summary'],
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'fMRI decoding status',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('completed')
    expect(output.interactionId).toBe('int-1')
    expect(output.idempotencyKey).toBe('idem-1')
    expect(output.summary).toContain('Latest FMRI decoding review')
    expect(output.evidence.length).toBe(1)
    expect(output.evidence[0]?.display_url).toContain('example.org/a')
    expect(output.evidence[0]?.source_host).toBe('example.org')
    expect(output.report?.query).toBe('fMRI decoding status')
    expect(output.report?.search_stats.scanned_count).toBeGreaterThan(0)
    expect(Array.isArray(output.report?.search_trails)).toBe(true)
  })

  it('renders report verdict and caveats from calibrated claim_report.json when available', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
        result: {
          status: 'success',
          data: {
            outputs: {
              status: 'running',
              interaction_id: 'int-claim-review',
            },
          },
        },
      }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
        result: {
          status: 'success',
          data: {
            outputs: {
              status: 'completed',
              run_id: 'br-claim-review',
              result: {
                summary: 'Raw evidence synthesis summary.',
                documents: [
                  {
                    doc_id: 'doc-claim-review',
                    title: 'Paper A',
                    url: 'https://example.org/paper-a',
                    snippets: ['Summary'],
                  },
                ],
              },
            },
          },
        },
      }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeToolSuccessResponse({
        ok: true,
        text: JSON.stringify({
          schema_version: 'claim-report-v1',
          summary: 'Calibrated claim summary from claim_report.json.',
          overall_verdict: 'indirectly_supported',
          caveats: ['No direct single-study statistical contrast was available.'],
          unresolved_questions: ['Direction conflict remains unresolved.'],
          claims: [{ claim_id: 'claim-1' }],
        }),
      }, 200),
    )

    const output = await runDeepResearch({
      query: 'claim review routing',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.summary).toBe('Raw evidence synthesis summary.')
    expect(output.report?.source_run_id).toBe('br-claim-review')
    expect(output.report?.summary).toBe('Calibrated claim summary from claim_report.json.')
    expect(output.report?.claim_review?.overall_verdict).toBe('indirectly_supported')
    expect(output.report?.claim_review?.claim_count).toBe(1)
    expect(output.report?.synthesis_full_text).toContain('## Calibrated Claim Review')
    expect(output.report?.synthesis_full_text).toContain(
      'No direct single-study statistical contrast was available.',
    )
    expect(output.report?.raw_summary).toBe('Raw evidence synthesis summary.')
    expect(output.report?.raw_synthesis_full_text).toContain('Raw evidence synthesis summary.')
  })

  it('uses Google deep research tools directly (without legacy deep_research start)', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              ok: true,
              data: {
                interaction_id: 'google-only-int-1',
                status: 'in_progress',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              ok: true,
              data: {
                interaction_id: 'google-only-int-1',
                status: 'completed',
                response: {
                  output: [
                    {
                      grounding_metadata: {
                        grounding_chunks: [
                          {
                            web: {
                              uri: 'https://example.org/google-only-source',
                              title: 'Google only source',
                            },
                          },
                        ],
                      },
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'google only tool routing',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.interactionId).toBe('google-only-int-1')

    const calledTools = fetchMock.mock.calls.map((call) => {
      const body = JSON.parse((call[1] as { body?: string }).body || '{}') as { tool?: string }
      return body.tool || ''
    })
    expect(calledTools[0]).toBe('google_deep_research_start')
    expect(calledTools).not.toContain('deep_research')
  })

  it('parses kg_hypothesis_candidate_cards MCP payload', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
        result: {
          status: 'success',
          data: {
            ok: true,
            result: {
              query: 'attention control',
              resolved_anchor_bundle: [
                {
                  kg_id: 'concept:attention',
                  label: 'Attention',
                  node_type: 'Concept',
                  matched_queries: ['attention control'],
                  score: 0.91,
                  rank: 1,
                },
              ],
              candidate_cards: [
                {
                  card_id: 'cand-1',
                  title: 'Attention candidate',
                  hypothesis: 'Attention shifts under task framing.',
                  taste_axis: 'controlled_ood_search',
                  minimal_discriminating_test: 'Run the smallest split first.',
                  falsifier_hint: 'Reject if the effect disappears under controls.',
                  kg_verification: {
                    verdict: 'insufficient_evidence',
                    confidence: 0.42,
                  },
                  novelty_signals: {
                    controlled_ood_score: 0.71,
                  },
                  topology_subgraph: {
                    focus_node_id: 'drn_focus_attention',
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
              warnings: ['candidate_only_surface'],
            },
          },
        },
      }, 200),
    )

    const output = await runKgHypothesisCandidateCards({
      query: 'attention control',
      topN: 1,
      withDeepResearch: false,
    })

    expect(output.query).toBe('attention control')
    expect(output.candidateCards).toHaveLength(1)
    expect(output.resolvedAnchorBundle).toEqual([
      {
        kg_id: 'concept:attention',
        label: 'Attention',
        node_type: 'Concept',
        matched_queries: ['attention control'],
        score: 0.91,
        rank: 1,
        raw: {
          kg_id: 'concept:attention',
          label: 'Attention',
          node_type: 'Concept',
          matched_queries: ['attention control'],
          score: 0.91,
          rank: 1,
        },
      },
    ])
    expect(output.candidateCards[0]?.title).toBe('Attention candidate')
    expect(output.candidateCards[0]?.kg_verification?.verdict).toBe('insufficient_evidence')
    expect(output.candidateCards[0]?.novelty_signals?.controlled_ood_score).toBe(0.71)
    expect(output.ephemeralWeightedSubgraph?.summary).toEqual({
      node_count: 4,
      edge_count: 3,
      card_subgraph_count: 1,
    })
    expect(output.summary.nCandidateCards).toBe(1)
    expect(output.summary.candidateLaneMode).toBe('broad')
    expect(output.warnings).toContain('candidate_only_surface')

    const calledTool = JSON.parse((fetchMock.mock.calls[0]?.[1] as { body?: string })?.body || '{}')
    expect(calledTool.tool).toBe('kg_hypothesis_candidate_cards')
  })

  it('drops opaque token-like summary text and keeps readable synthesis', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'cached',
                interaction_id: 'int-token',
                idempotency_key: 'idem-token',
                result: {
                  summary:
                    'AUZIYQHBP-_O0sJIC0t9o9UyReI9jtsA6aLpvXi4nWfb7SIxGxvgB-PSt4oAICiZe',
                  response: {
                    text: 'Readable synthesis from cached deep research output.',
                  },
                  documents: [
                    {
                      doc_id: 'doc-token-1',
                      title: 'Readable source',
                      url: 'https://example.org/readable-source',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'token sanitization check',
      options: {
        pollIntervalMs: 1,
        maxPolls: 1,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('cached')
    expect(output.summary).toContain('Readable synthesis from cached deep research output')
    expect(output.report?.summary).toContain('final verdict withheld')
    expect(output.report?.raw_synthesis_full_text).toContain(
      'Readable synthesis from cached deep research output',
    )
  })

  it('merges historical search trails from cached payload into report trails', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'cached',
                interaction_id: 'int-cached-trails',
                idempotency_key: 'idem-cached-trails',
                result: {
                  summary: 'Cached summary',
                  documents: [
                    {
                      doc_id: 'doc-cached-trail',
                      title: 'Cached source',
                      url: 'https://example.org/cached-source',
                    },
                  ],
                  search_trails: [
                    {
                      stage: 'start',
                      tool: 'google_deep_research_start',
                      status: 'running',
                      detail: 'historical-start',
                    },
                    {
                      stage: 'poll',
                      tool: 'google_deep_research_get',
                      status: 'completed',
                      detail: 'historical-complete',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'cached trails merge check',
      options: {
        pollIntervalMs: 1,
        maxPolls: 1,
        startGracePolls: 0,
      },
    })

    const details = (output.report?.search_trails || []).map((trail) => trail.detail || '')
    expect(details).toContain('historical-start')
    expect(details).toContain('historical-complete')
    expect(output.report?.search_trails.length).toBeGreaterThanOrEqual(2)
  })

  it('marks cached historical trails unavailable when cached payload lacks trail history', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'cached',
                interaction_id: 'int-cached-no-history',
                idempotency_key: 'idem-cached-no-history',
                result: {
                  summary: 'Cached summary without historical trails',
                  documents: [
                    {
                      doc_id: 'doc-cached-no-history',
                      title: 'Cached source',
                      url: 'https://example.org/cached-no-history',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'cached trail availability check',
      options: {
        pollIntervalMs: 1,
        maxPolls: 1,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('cached')
    expect(output.report?.historical_trails_available).toBe(false)
    expect(
      output.report?.search_trails.some((trail) =>
        (trail.detail || '').includes('historical trails unavailable'),
      ),
    ).toBe(true)
  })

  it('uses fallback_rule synthesis when upstream synthesis is not informative', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              run_id: 'br-fallback-rule',
              outputs: {
                status: 'running',
                interaction_id: 'int-fallback-rule',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              run_id: 'br-fallback-rule',
              status: 'succeeded',
              result: {
                interaction_id: 'int-fallback-rule',
                status: 'completed',
                documents: [
                  {
                    doc_id: 'doc-fallback-rule',
                    title: 'Replication disagreements in fMRI task studies',
                    url: 'https://example.org/replication-disagreement',
                    snippets: ['Differences in task context drive inconsistent replication outcomes.'],
                  },
                ],
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'replication disagreement synthesis',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.report?.synthesis_generated_by).toBe('fallback_rule')
    expect((output.report?.synthesis_full_text || '').length).toBeGreaterThan(60)
    expect((output.report?.summary || '').length).toBeGreaterThan(20)
    const calledTools = fetchMock.mock.calls.map((call) => {
      const body = JSON.parse((call[1] as { body?: string }).body || '{}') as { tool?: string }
      return body.tool || ''
    })
    expect(calledTools.slice(0, 2)).toEqual(['google_deep_research_start', 'run_get'])
  })

  it('uses llm_fallback synthesis when auth context is available', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        if (fetchMock.mock.calls.length === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-llm-fallback',
                  },
                },
              },
            }, 200)
        }

        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  result: {
                    documents: [
                      {
                        doc_id: 'doc-llm-fallback',
                        title: 'Task-context moderators in approach-avoidance fMRI',
                        url: 'https://example.org/task-context-moderator',
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.includes('/api/chat')) {
        return makeJsonResponse({
            text: 'Across sources, task-context differences explain much of the replication variance. Evidence is convergent on confound control requirements, while subgroup effects remain uncertain. For this query, prioritize preregistered discriminating tests before broad claims.',
          }, 200)
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'llm fallback synthesis',
      authHeaders: new Headers({ cookie: 'test-session=1' }),
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.report?.synthesis_generated_by).toBe('llm_fallback')
    expect(output.report?.synthesis_full_text).toContain('Verdict and caveats are withheld')
    expect(output.report?.raw_synthesis_full_text).toContain('task-context differences')
  })

  it('treats deep research maxPolls=0 as unlimited polling', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-unlimited',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-unlimited',
              },
            },
          },
        }, 200),
    )
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-unlimited',
              },
            },
          },
        }, 200),
    )
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Long-running deep research finished.',
                  documents: [
                    {
                      doc_id: 'doc-unlimited-1',
                      title: 'Unlimited polling source',
                      url: 'https://example.org/unlimited-polling',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'long-running deep research topic',
      options: {
        pollIntervalMs: 1,
        maxPolls: 0,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('completed')
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('defaults to unlimited deep research polling when maxPolls is omitted', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let call = 0
    fetchMock.mockImplementation(async () => {
      call += 1

      if (call === 1) {
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'running',
                  interaction_id: 'int-default-unlimited',
                },
              },
            },
          }, 200)
      }

      if (call < 40) {
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'running',
                  interaction_id: 'int-default-unlimited',
                },
              },
            },
          }, 200)
      }

      return makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Completed after extended polling.',
                  documents: [
                    {
                      doc_id: 'doc-default-unlimited-1',
                      title: 'Default unlimited polling source',
                      url: 'https://example.org/default-unlimited-polling',
                    },
                  ],
                },
              },
            },
          },
        }, 200)
    })

    const output = await runDeepResearch({
      query: 'extended deep research runtime',
      options: {
        pollIntervalMs: 1,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('completed')
    expect(fetchMock).toHaveBeenCalledTimes(40)
  })

  it('reports poll-limit exhaustion with explicit unlimited-polling guidance', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-capped',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-capped',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-capped',
              },
            },
          },
        }, 200),
    )

    let thrown: unknown = null
    try {
      await runDeepResearch({
        query: 'capped polling deep research',
        options: {
          pollIntervalMs: 1,
          maxPolls: 2,
          startGracePolls: 0,
        },
      })
    } catch (error) {
      thrown = error
    }

    expect(thrown).toBeInstanceOf(Error)
    expect((thrown as Error).message).toMatch(/max attempts \(2\).*deep_research_max_polls=0/i)
    expect(getDeepResearchErrorCode(thrown)).toBe(DEEP_RESEARCH_ERROR_CODES.MAX_POLLS_EXCEEDED)
  })

  it('falls back to sync mode when start response has no interaction identifiers', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    const missingIdsResponse = makeJsonResponse({
        result: {
          status: 'success',
          data: {
            status: 'running',
          },
        },
      }, 200)

    fetchMock.mockResolvedValueOnce(missingIdsResponse)
    fetchMock.mockResolvedValueOnce(missingIdsResponse)
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'ok',
                result: {
                  summary: 'Recovered through sync fallback after missing IDs.',
                  documents: [
                    {
                      doc_id: 'doc-sync-missing-ids',
                      title: 'Recovered source',
                      url: 'https://example.org/recovered-missing-ids',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'fMRI decoding status',
      options: {
        pollIntervalMs: 1,
        maxPolls: 1,
        startGracePolls: 1,
      },
    })

    expect(output.summary).toContain('Recovered through sync fallback')
    expect(output.evidence.length).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('falls back to sync mode on recoverable deep research poll errors', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-recoverable',
                idempotency_key: 'idem-recoverable',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'error',
            error: 'Tool deep_research failed: Object of type datetime is not JSON serializable',
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'ok',
                result: {
                  summary: 'Sync fallback recovered evidence.',
                  documents: [
                    {
                      doc_id: 'doc-sync-1',
                      title: 'Recovered source',
                      url: 'https://example.org/recovered',
                      snippets: ['Recovered snippet'],
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'recoverable deep research query',
      options: {
        pollIntervalMs: 1,
        maxPolls: 0,
        startGracePolls: 0,
      },
    })

    expect(output.summary).toContain('Sync fallback recovered evidence')
    expect(output.evidence.length).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('retries transient deep research poll tool-call failures with backoff', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-transient-retry',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockRejectedValueOnce(new TypeError('network down'))
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Completed after transient retry.',
                  documents: [
                    {
                      doc_id: 'doc-transient-ok',
                      title: 'Transient retry recovered source',
                      url: 'https://example.org/transient-retry',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'transient retry query',
      options: {
        pollIntervalMs: 1,
        maxPolls: 3,
        startGracePolls: 0,
        transientRetries: 1,
        retryBaseMs: 1,
        retryMaxMs: 1,
      },
    })

    expect(output.status).toBe('completed')
    expect(output.summary).toContain('Completed after transient retry')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('falls back to sync mode on terminal deep research polling failure states', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-terminal-failure',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'failed',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                interaction_id: 'int-terminal-fallback',
                result: {
                  summary: 'Recovered via sync fallback.',
                  documents: [
                    {
                      doc_id: 'doc-terminal-fallback',
                      title: 'Fallback source',
                      url: 'https://example.org/fallback',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'terminal failure state query',
      options: {
        pollIntervalMs: 1,
        maxPolls: 9,
        startGracePolls: 0,
      },
    })

    expect(output.status).toBe('completed')
    expect(output.fallbackPath).toBe('sync_after_terminal_failure')
    expect(output.summary).toContain('Recovered via sync fallback')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('extracts citeable evidence from nested citation payloads when documents are missing', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-citation',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Grounded response',
                  response: {
                    output: [
                      {
                        content: [{ text: 'Summary text without inline links.' }],
                        grounding_metadata: {
                          grounding_chunks: [
                            {
                              web: {
                                uri: 'https://example.org/decoding-review',
                                title: 'Decoding review',
                              },
                            },
                            {
                              web: {
                                uri: 'https://openneuro.org/datasets/ds000030',
                                title: 'OpenNeuro ds000030',
                              },
                            },
                          ],
                        },
                      },
                    ],
                  },
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'fMRI decoding status',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence.length).toBeGreaterThan(0)
    const urls = output.evidence.map((item) => item.url)
    expect(urls).toContain('https://example.org/decoding-review')
    expect(urls).toContain('https://openneuro.org/datasets/ds000030')
  })

  it('filters unresolved grounding redirect URLs from evidence list', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-redirect-filter',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Grounded response',
                  documents: [
                    {
                      doc_id: 'doc-vertex',
                      title: 'vertex redirect',
                      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEXAMPLE',
                    },
                    {
                      doc_id: 'doc-real',
                      title: 'Real source',
                      url: 'https://example.org/real-paper',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'filter vertex redirect sources',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence.some((item) => item.url?.includes('vertexaisearch.cloud.google.com'))).toBe(
      false,
    )
    expect(output.evidence.some((item) => item.url === 'https://example.org/real-paper')).toBe(true)
    expect(
      output.report?.discarded_sources.some(
        (source) => source.reason_code === 'redirect_unresolved',
      ),
    ).toBe(true)
  })

  it('corrects mismatched arxiv links via OpenAlex title validation', async () => {
    process.env.HYPOTHESIS_IDENTIFIER_VALIDATION = '1'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let toolCall = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        toolCall += 1
        if (toolCall === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-arxiv-correct',
                  },
                },
              },
            }, 200)
        }
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  result: {
                    documents: [
                      {
                        doc_id: 'doc-spd',
                        title:
                          'SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges',
                        url: 'https://arxiv.org/abs/2401.04561',
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.startsWith('https://export.arxiv.org/api/query')) {
        return new Response(
          '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.04561v1</id><title>Analytic three-dimensional primary hair charged black holes in the framework of Einstein-power-Yang-Mills theory</title></entry></feed>',
          { status: 200 },
        )
      }

      if (rawUrl.includes('https://api.openalex.org/works') && rawUrl.includes('search=')) {
        return makeJsonResponse({
            results: [
              {
                display_name:
                  'SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges',
                primary_location: {
                  landing_page_url: 'https://arxiv.org/abs/2504.18882',
                },
                doi: 'https://doi.org/10.48550/arXiv.2504.18882',
                ids: {
                  doi: 'https://doi.org/10.48550/arXiv.2504.18882',
                },
              },
            ],
          }, 200)
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'spd neuroimaging review',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.evidence[0]?.url).toBe('https://arxiv.org/abs/2504.18882')
    expect(output.evidence[0]?.raw_url).toBe('https://arxiv.org/abs/2401.04561')
    expect(output.evidence[0]?.display_url).toContain('arxiv.org/abs/2504.18882')
  })

  it('drops mismatched arxiv links when no canonical title match is found', async () => {
    process.env.HYPOTHESIS_IDENTIFIER_VALIDATION = '1'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let toolCall = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        toolCall += 1
        if (toolCall === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-arxiv-drop',
                  },
                },
              },
            }, 200)
        }
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  result: {
                    documents: [
                      {
                        doc_id: 'doc-spd-drop',
                        title:
                          'SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges',
                        url: 'https://arxiv.org/abs/2401.04561',
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.startsWith('https://export.arxiv.org/api/query')) {
        return new Response(
          '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.04561v1</id><title>Analytic three-dimensional primary hair charged black holes in the framework of Einstein-power-Yang-Mills theory</title></entry></feed>',
          { status: 200 },
        )
      }

      if (rawUrl.includes('https://api.openalex.org/works') && rawUrl.includes('search=')) {
        return makeJsonResponse({
            results: [
              {
                display_name: 'Completely unrelated paper',
                primary_location: {
                  landing_page_url: 'https://doi.org/10.1000/unrelated',
                },
                doi: 'https://doi.org/10.1000/unrelated',
                ids: {
                  doi: 'https://doi.org/10.1000/unrelated',
                },
              },
            ],
          }, 200)
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'spd neuroimaging mismatch drop',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.evidence[0]?.url).toBeNull()
    expect(output.evidence[0]?.raw_url).toBe('https://arxiv.org/abs/2401.04561')
    expect(output.evidence[0]?.display_url).toBeNull()
    expect(output.evidence[0]?.source_host).toBeNull()
  })

  it('canonicalizes arxiv DOI links back to arxiv abs URLs after title validation', async () => {
    process.env.HYPOTHESIS_IDENTIFIER_VALIDATION = '1'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let toolCall = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        toolCall += 1
        if (toolCall === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-arxiv-doi',
                  },
                },
              },
            }, 200)
        }
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  result: {
                    documents: [
                      {
                        doc_id: 'doc-spd-doi',
                        title:
                          'SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges',
                        url: 'https://doi.org/10.48550/arXiv.2504.18882',
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.startsWith('https://export.arxiv.org/api/query')) {
        return new Response(
          '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2504.18882v1</id><title>SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges</title></entry></feed>',
          { status: 200 },
        )
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'spd neuroimaging arxiv doi',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.evidence[0]?.url).toBe('https://arxiv.org/abs/2504.18882')
    expect(output.evidence[0]?.display_url).toContain('arxiv.org/abs/2504.18882')
  })

  it('annotates redirect_unresolved with budget-skipped diagnostics when network resolution is disabled by cap', async () => {
    process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS = '0'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-redirect-budget',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Grounded response',
                  documents: [
                    {
                      doc_id: 'doc-vertex-budget',
                      title: 'vertex redirect budget',
                      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ_BUDGET',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'redirect budget diagnostics',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    const discarded = output.report?.discarded_sources.find(
      (source) => source.reason_code === 'redirect_unresolved',
    )
    expect(discarded).toBeTruthy()
    expect(discarded?.reason_meta?.skipped_by_budget).toBe(true)
    expect(discarded?.reason_meta?.resolver).toBe('none')
  })

  it('builds discarded_aggregates for unresolved redirect clusters', async () => {
    process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS = '0'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-redirect-aggregate',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  summary: 'Grounded response',
                  documents: [
                    {
                      doc_id: 'doc-r1',
                      title: 'redirect 1',
                      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ_R1',
                    },
                    {
                      doc_id: 'doc-r2',
                      title: 'redirect 2',
                      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ_R2',
                    },
                    {
                      doc_id: 'doc-r3',
                      title: 'redirect 3',
                      url: 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ_R3',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'redirect aggregate diagnostics',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    const aggregate = output.report?.discarded_aggregates.find(
      (item) => item.reason_code === 'redirect_unresolved',
    )
    expect(aggregate).toBeTruthy()
    expect(aggregate?.count).toBe(3)
    expect(aggregate?.stats?.skipped_by_budget).toBe(3)
  })

  it('parses google_deep_research interactions response shape from nested data.data', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              ok: true,
              data: {
                interaction_id: 'google-int-1',
                status: 'in_progress',
                response: { text: 'start accepted' },
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              ok: true,
              data: {
                interaction_id: 'google-int-1',
                status: 'completed',
                response: {
                  output: [
                    {
                      grounding_metadata: {
                        grounding_chunks: [
                          {
                            web: {
                              uri: 'https://example.org/grounded-source',
                              title: 'Grounded source',
                            },
                          },
                        ],
                      },
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'fMRI decoding grounded evidence',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.interactionId).toBe('google-int-1')
    expect(output.evidence.some((item) => item.url === 'https://example.org/grounded-source')).toBe(
      true,
    )
  })

  it('dedupes repeated synthesized evidence content and keeps non-synthetic sources', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-dedup',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  documents: [
                    {
                      doc_id: 'doc-1',
                      title:
                        '# Advances in fMRI Decoding and Predictive Modeling in Healthy Adults: A February 2026 Synthesis',
                      url: 'https://arxiv.org/html/2510.16196v1',
                      snippets: [
                        'Key points: Paradigm shift in visual decoding and predictive modeling outcomes.',
                      ],
                    },
                    {
                      doc_id: 'doc-2',
                      title:
                        '# Advances in fMRI Decoding and Predictive Modeling in Healthy Adults: A February 2026 Synthesis',
                      url: 'https://openreview.net/forum?id=88ZLp7xYxw',
                      snippets: [
                        'Key points: Paradigm shift in visual decoding and predictive modeling outcomes.',
                      ],
                    },
                    {
                      doc_id: 'doc-3',
                      title: 'Nested cross-validation improves cross-site fMRI decoding robustness',
                      url: 'https://doi.org/10.1016/j.neuroimage.2025.120001',
                      snippets: ['Strict nested validation reduces inflated decoding accuracy estimates.'],
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'fMRI decoding robustness',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence.length).toBe(1)
    expect(output.degenerateEvidence.degenerate).toBe(true)
    expect(output.degenerateEvidence.mode).toBe('soft_keep_top1')
    expect(output.degenerateEvidence.dedupeStats.collapsedGroups).toBeGreaterThan(0)
    expect(output.evidence[0]?.label.toLowerCase()).toContain('nested cross-validation')
    expect(
      output.evidence.some((item) => item.label.toLowerCase().includes('february 2026 synthesis')),
    ).toBe(false)
  })

  it('collapses evidence with different titles when summary fingerprint is duplicated', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-summary-fingerprint',
              },
            },
          },
        }, 200),
    )

    const syntheticSummary =
      '## Executive Summary\n* **Paradigm Shift:** Comprehensive analysis of approach-avoidance task outcomes across heterogeneous cohorts.'

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  documents: [
                    {
                      doc_id: 'doc-a',
                      title: 'AAT synthesis in bioRxiv',
                      url: 'https://biorxiv.org/content/10.1101/2026.02.01.123456v1',
                      snippets: [syntheticSummary],
                    },
                    {
                      doc_id: 'doc-b',
                      title: 'AAT synthesis in Frontiers',
                      url: 'https://www.frontiersin.org/articles/10.3389/fnhum.2026.123456/full',
                      snippets: [syntheticSummary],
                    },
                    {
                      doc_id: 'doc-c',
                      title: 'AAT synthesis in PMC',
                      url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12345678/',
                      snippets: [syntheticSummary],
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'approach avoidance task synthesis',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.degenerateEvidence.degenerate).toBe(true)
    expect(output.degenerateEvidence.dedupeStats.collapsedGroups).toBeGreaterThan(0)
    expect(output.evidence[0]?.synthetic_summary).toBe(true)
    expect(output.evidence[0]?.quality_tier).toBe('tertiary')
  })

  it('dedupes paper duplicates across pubmed and pmc ids via canonical PMID', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let callCount = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        callCount += 1
        if (callCount === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-canonical',
                    idempotency_key: 'idem-canonical',
                  },
                },
              },
            }, 200)
        }

        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  interaction_id: 'int-canonical',
                  idempotency_key: 'idem-canonical',
                  result: {
                    summary: 'Canonical dedupe check',
                    documents: [
                      {
                        doc_id: 'doc-2',
                        title: 'PubMed source on AAT replication',
                        url: 'https://pubmed.ncbi.nlm.nih.gov/40657593/',
                        snippets: [
                          'Distinct summary for PMID record.',
                        ],
                      },
                      {
                        doc_id: 'doc-1',
                        title: 'PMC copy of same paper',
                        url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12244139/',
                        snippets: [
                          'Distinct summary for PMC copy of same paper.',
                        ],
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.includes('pmc.ncbi.nlm.nih.gov/utils/idconv/v1.0/')) {
        return makeJsonResponse({
            records: [
              {
                pmcid: 'PMC12244139',
                pmid: '40657593',
              },
            ],
          }, 200)
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'canonical dedupe test',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.evidence[0]?.canonical_id).toBe('40657593')
    const discarded = output.report?.discarded_sources ?? []
    expect(discarded).toHaveLength(1)
    expect(discarded[0].reason_code).toBe('duplicate_similarity')
    expect(discarded[0].reason_detail).toContain('PMC/PMID canonical ID')
  })

  it('enriches synthetic pubmed evidence with real abstract and clears synthetic flag', async () => {
    process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_ENRICH = '1'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    let toolCall = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url

      if (rawUrl.includes('/api/tools/run')) {
        toolCall += 1
        if (toolCall === 1) {
          return makeJsonResponse({
              result: {
                status: 'success',
                data: {
                  outputs: {
                    status: 'running',
                    interaction_id: 'int-enrich-pubmed',
                  },
                },
              },
            }, 200)
        }
        return makeJsonResponse({
            result: {
              status: 'success',
              data: {
                outputs: {
                  status: 'completed',
                  result: {
                    summary: 'Synthetic synthesis summary',
                    documents: [
                      {
                        doc_id: 'doc-pubmed-1',
                        title:
                          '# Comprehensive Analysis of Decoding in Healthy Adults: A February 2026 Synthesis',
                        url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
                        snippets: ['## Executive Summary\n* **Key Points**: Broad synthesis text.'],
                      },
                    ],
                  },
                },
              },
            },
          }, 200)
      }

      if (rawUrl.includes('eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi')) {
        return new Response(
          '<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><Abstract><AbstractText>Nested cross-validation reduced inflated fMRI decoding gains and improved cross-site generalization in healthy adults.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>',
          { status: 200 },
        )
      }

      return new Response('not found', { status: 404 })
    })

    const output = await runDeepResearch({
      query: 'fmri decoding robust validation',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence).toHaveLength(1)
    expect(output.evidence[0]?.synthetic_summary).toBe(false)
    expect(output.evidence[0]?.summary?.toLowerCase()).toContain('nested cross-validation reduced')
    expect(output.evidence[0]?.quality_tier).not.toBe('tertiary')
  })

  it('does not flag degenerate evidence when titles are distinct', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-not-degenerate',
              },
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'completed',
                result: {
                  documents: [
                    {
                      doc_id: 'doc-1',
                      title: 'Nested cross-validation improves fMRI decoding robustness',
                      url: 'https://doi.org/10.1016/j.neuroimage.2025.120001',
                    },
                    {
                      doc_id: 'doc-2',
                      title: 'Parcellation choices alter connectome biomarker stability',
                      url: 'https://doi.org/10.1016/j.neuroimage.2025.120002',
                    },
                  ],
                },
              },
            },
          },
        }, 200),
    )

    const output = await runDeepResearch({
      query: 'distinct evidence titles',
      options: {
        pollIntervalMs: 1,
        maxPolls: 2,
        startGracePolls: 0,
      },
    })

    expect(output.evidence.length).toBe(2)
    expect(output.degenerateEvidence.degenerate).toBe(false)
    expect(output.degenerateEvidence.mode).toBe('none')
    expect(output.degenerateEvidence.dedupeStats.collapsedGroups).toBe(0)
  })

  it('enforces background cap for long-running deep research polling', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockImplementation(async () => {
      return makeJsonResponse({
          result: {
            status: 'success',
            data: {
              outputs: {
                status: 'running',
                interaction_id: 'int-cap',
                idempotency_key: 'idem-cap',
              },
            },
          },
        }, 200)
    })

    await expect(
      runDeepResearch({
        query: 'never-ending deep research query',
        options: {
          pollIntervalMs: 50,
          maxPolls: 0,
          startGracePolls: 0,
          backgroundCapSec: 1,
        },
      }),
    ).rejects.toThrow(/background cap/i)
  })

  it('expands kg_multihop question with mapped task, concepts, and synonyms', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              matched_task: 'n-back',
              concepts: ['working memory', 'executive function'],
              synonyms: ['nback', 'WM task'],
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              answer: 'KG answer',
              summary: { n_paths: 2, hops_used: 2 },
              warnings: [],
            },
          },
        }, 200),
    )

    const output = await runKgCompare({ term: 'brain decoding' })
    expect(output.priorArtMatch.some((line) => line.includes('Mapped aliases:'))).toBe(true)

    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body as string) as {
      tool: string
      arguments: { question: string }
    }
    expect(secondCallBody.tool).toBe('kg_multihop_qa')
    expect(secondCallBody.arguments.question).toContain('brain decoding')
    expect(secondCallBody.arguments.question.toLowerCase()).toContain('n-back')
    expect(secondCallBody.arguments.question.toLowerCase()).toContain('working memory')
  })

  it('does not set local timeout signal for kg_multihop_qa by default', async () => {
    delete process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: { status: 'success', data: { matched_task: null, concepts: [], synonyms: [] } },
        }, 200),
    )
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: { status: 'success', data: { answer: 'ok', summary: { n_paths: 1 } } },
        }, 200),
    )

    await runKgCompare({ term: 'working memory task' })

    const secondCallInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(secondCallInit.signal).toBeUndefined()
  })

  it('sets local timeout signal for kg_multihop_qa when env timeout is configured', async () => {
    process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS = '12000'

    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: { status: 'success', data: { matched_task: null, concepts: [], synonyms: [] } },
        }, 200),
    )
    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: { status: 'success', data: { answer: 'ok', summary: { n_paths: 1 } } },
        }, 200),
    )

    await runKgCompare({ term: 'working memory task' })

    const secondCallInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(secondCallInit.signal).toBeDefined()
  })

  it('still includes original term when mapping output is sparse', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              matched_task: null,
              concepts: [],
              synonyms: [],
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              answer: null,
              summary: { n_paths: 0, hops_used: 1 },
              warnings: ['no_paths'],
            },
          },
        }, 200),
    )

    await runKgCompare({ term: 'working memory task' })

    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body as string) as {
      arguments: { question: string }
    }
    expect(secondCallBody.arguments.question.toLowerCase()).toContain('working memory task')
  })

  it('retries kg_multihop once when first attempt has no seed entities', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              matched_task: 'brain decoding',
              concepts: ['machine learning'],
              synonyms: ['decoder'],
            },
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'error',
            error: 'No seed entities found for the provided question',
          },
        }, 200),
    )

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              answer: 'Found paths after retry',
              summary: { n_paths: 1, hops_used: 2 },
              warnings: [],
            },
          },
        }, 200),
    )

    const output = await runKgCompare({ term: 'brain decoding' })
    expect(output.multihopAttempts).toBe(2)
    expect(output.priorArtMatch.some((line) => line.includes('KG multihop returned 1 path'))).toBe(
      true,
    )
  })

  it('softens no-seed failure after retry exhaustion', async () => {
    const fetchMock = vi.fn()
    global.fetch = fetchMock as unknown as typeof fetch

    fetchMock.mockResolvedValueOnce(
      makeJsonResponse({
          result: {
            status: 'success',
            data: {
              matched_task: null,
              concepts: [],
              synonyms: [],
            },
          },
        }, 200),
    )

    const noSeedErrorResponse = makeJsonResponse({
        result: {
          status: 'error',
          error: 'No seed entities found for the provided question',
        },
      }, 200)
    fetchMock.mockResolvedValueOnce(noSeedErrorResponse)
    fetchMock.mockResolvedValueOnce(noSeedErrorResponse)

    const output = await runKgCompare({ term: 'fmri-based brain decoding' })

    expect(output.multihopAttempts).toBe(2)
    expect(output.warnings.some((line) => /sparse seed anchors/i.test(line))).toBe(true)
    expect(output.noveltyGap.join(' ')).not.toContain('Tool kg_multihop_qa failed')
  })
})
