import { NextRequest } from 'next/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from '../route'

const runStoreMocks = vi.hoisted(() => ({
  getRunSnapshotPersisted: vi.fn(),
  getRunSnapshotsForSessionPersisted: vi.fn(),
}))

vi.mock('@/lib/server/hypothesis-run-store', () => runStoreMocks)

describe('/api/hypothesis/trajectory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns 400 when neither sessionId nor runId is provided', async () => {
    const req = new NextRequest('http://localhost/api/hypothesis/trajectory')
    const res = await GET(req)
    const body = await res.json()

    expect(res.status).toBe(400)
    expect(body).toEqual({
      error: 'missing_target',
      message: 'sessionId or runId is required.',
    })
  })

  it('exports session-scoped hot-load trajectory rows', async () => {
    vi.mocked(runStoreMocks.getRunSnapshotsForSessionPersisted).mockResolvedValueOnce([
      {
        run_id: 'hrun-001',
        session_id: 'hsession-001',
        state: 'completed',
        intent_summary: {
          term: 'fmri-based image decoding',
          intent_ready: true,
          missing_fields: [],
        },
        started_at: '2026-03-15T07:00:00Z',
        updated_at: '2026-03-15T07:05:00Z',
        done: true,
        error_message: null,
        artifacts: [
          {
            id: 'hot-load-trajectory',
            kind: 'hot_load_trajectory',
            updated_at: '2026-03-15T07:05:00Z',
            payload: {
              query: 'fmri-based image decoding',
              query_normalized: 'fmri-based image decoding',
              workflow: {
                workflow_id: 'workflow_hypothesis_candidate_cards',
                candidate_lane_mode: 'broad',
                mcp_fallback_used: false,
                verification_source: 'mcp_workflow',
              },
              resolved_anchor_bundle: [
                { kg_id: 'concept:image_decoding', label: 'Image decoding' },
              ],
              candidate_cards: {
                total_count: 1,
                grounded_count: 0,
                weak_count: 0,
                draft_count: 1,
                verdict_counts: { uncertain: 1 },
                evidence_source_scope_counts: { hybrid_kg_literature: 1 },
                deep_research_status_counts: { ok: 1 },
              },
              evidence: {
                total_count: 3,
                grounding_quality: 'partial',
                deep_research_status: 'ready',
                source_channel_counts: { deep_research_live: 3 },
                quality_counts: { primary: 2 },
              },
              deep_research: {
                used: true,
                pending: false,
                report_available: true,
              },
              warnings: [],
            },
          },
        ],
      },
    ] as never)

    const req = new NextRequest(
      'http://localhost/api/hypothesis/trajectory?sessionId=hsession-001&limit=10',
    )
    const res = await GET(req)
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(runStoreMocks.getRunSnapshotsForSessionPersisted).toHaveBeenCalledWith({
      sessionId: 'hsession-001',
      limit: 10,
    })
    expect(body.ok).toBe(true)
    expect(body.summary.total_rows).toBe(1)
    expect(body.rows[0]).toMatchObject({
      session_id: 'hsession-001',
      run_id: 'hrun-001',
      query: 'fmri-based image decoding',
      workflow_id: 'workflow_hypothesis_candidate_cards',
      top_anchor_labels: ['Image decoding'],
    })
  })

  it('exports run-scoped hot-load trajectory rows', async () => {
    vi.mocked(runStoreMocks.getRunSnapshotPersisted).mockResolvedValueOnce({
      run_id: 'hrun-002',
      session_id: 'hsession-002',
      state: 'completed',
      intent_summary: {
        term: 'visual reconstruction',
        intent_ready: true,
        missing_fields: [],
      },
      started_at: '2026-03-15T08:00:00Z',
      updated_at: '2026-03-15T08:01:00Z',
      done: true,
      error_message: null,
      artifacts: [
        {
          id: 'hot-load-trajectory',
          kind: 'hot_load_trajectory',
          updated_at: '2026-03-15T08:01:00Z',
          payload: {
            query: 'visual reconstruction',
            query_normalized: 'visual reconstruction',
            workflow: {
              workflow_id: null,
              candidate_lane_mode: null,
              mcp_fallback_used: true,
              verification_source: 'local_fallback',
            },
            resolved_anchor_bundle: [],
            candidate_cards: {
              total_count: 0,
              grounded_count: 0,
              weak_count: 0,
              draft_count: 0,
              verdict_counts: {},
              evidence_source_scope_counts: {},
              deep_research_status_counts: {},
            },
            evidence: {
              total_count: 0,
              grounding_quality: 'draft_unverified',
              deep_research_status: 'failed',
              source_channel_counts: {},
              quality_counts: {},
            },
            deep_research: {
              used: false,
              pending: false,
              report_available: false,
            },
            warnings: ['fallback'],
          },
        },
      ],
    } as never)

    const req = new NextRequest('http://localhost/api/hypothesis/trajectory?runId=hrun-002')
    const res = await GET(req)
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(runStoreMocks.getRunSnapshotPersisted).toHaveBeenCalledWith('hrun-002')
    expect(body.target).toEqual({ run_id: 'hrun-002' })
    expect(body.rows[0]).toMatchObject({
      run_id: 'hrun-002',
      verification_source: 'local_fallback',
      mcp_fallback_used: true,
      deep_research_status: 'failed',
    })
  })

  it('filters rows by deepResearchStatus, verificationSource, mcpFallbackUsed, and q', async () => {
    vi.mocked(runStoreMocks.getRunSnapshotsForSessionPersisted).mockResolvedValueOnce([
      {
        run_id: 'hrun-a',
        session_id: 'hsession-filter',
        state: 'completed',
        intent_summary: { term: 'image reconstruction', intent_ready: true, missing_fields: [] },
        started_at: '2026-03-15T09:00:00Z',
        updated_at: '2026-03-15T09:01:00Z',
        done: true,
        error_message: null,
        artifacts: [
          {
            id: 'hot-load-trajectory',
            kind: 'hot_load_trajectory',
            updated_at: '2026-03-15T09:01:00Z',
            payload: {
              query: 'image reconstruction',
              query_normalized: 'image reconstruction',
              workflow: {
                workflow_id: 'workflow_hypothesis_candidate_cards',
                candidate_lane_mode: 'broad',
                mcp_fallback_used: false,
                verification_source: 'mcp_workflow',
              },
              resolved_anchor_bundle: [],
              candidate_cards: {
                total_count: 1,
                grounded_count: 0,
                weak_count: 1,
                draft_count: 0,
                verdict_counts: { uncertain: 1 },
                evidence_source_scope_counts: { hybrid_kg_literature: 1 },
                deep_research_status_counts: { ok: 1 },
              },
              evidence: {
                total_count: 2,
                grounding_quality: 'partial',
                deep_research_status: 'ready',
                source_channel_counts: {},
                quality_counts: {},
              },
              deep_research: {
                used: true,
                pending: false,
                report_available: true,
              },
              warnings: [],
            },
          },
        ],
      },
      {
        run_id: 'hrun-b',
        session_id: 'hsession-filter',
        state: 'completed',
        intent_summary: { term: 'working memory', intent_ready: true, missing_fields: [] },
        started_at: '2026-03-15T09:10:00Z',
        updated_at: '2026-03-15T09:11:00Z',
        done: true,
        error_message: null,
        artifacts: [
          {
            id: 'hot-load-trajectory',
            kind: 'hot_load_trajectory',
            updated_at: '2026-03-15T09:11:00Z',
            payload: {
              query: 'working memory',
              query_normalized: 'working memory',
              workflow: {
                workflow_id: null,
                candidate_lane_mode: null,
                mcp_fallback_used: true,
                verification_source: 'local_fallback',
              },
              resolved_anchor_bundle: [],
              candidate_cards: {
                total_count: 0,
                grounded_count: 0,
                weak_count: 0,
                draft_count: 0,
                verdict_counts: {},
                evidence_source_scope_counts: {},
                deep_research_status_counts: {},
              },
              evidence: {
                total_count: 0,
                grounding_quality: 'draft_unverified',
                deep_research_status: 'failed',
                source_channel_counts: {},
                quality_counts: {},
              },
              deep_research: {
                used: false,
                pending: false,
                report_available: false,
              },
              warnings: ['fallback'],
            },
          },
        ],
      },
    ] as never)

    const req = new NextRequest(
      'http://localhost/api/hypothesis/trajectory?sessionId=hsession-filter&deepResearchStatus=ready&verificationSource=mcp_workflow&mcpFallbackUsed=0&q=image',
    )
    const res = await GET(req)
    const body = await res.json()

    expect(res.status).toBe(200)
    expect(body.filters).toEqual({
      deep_research_status: 'ready',
      verification_source: 'mcp_workflow',
      mcp_fallback_used: false,
      query_contains: 'image',
    })
    expect(body.summary.total_rows).toBe(1)
    expect(body.rows[0].run_id).toBe('hrun-a')
  })

  it('exports JSONL when jsonl=1 is requested', async () => {
    vi.mocked(runStoreMocks.getRunSnapshotPersisted).mockResolvedValueOnce({
      run_id: 'hrun-003',
      session_id: 'hsession-003',
      state: 'completed',
      intent_summary: {
        term: 'image reconstruction',
        intent_ready: true,
        missing_fields: [],
      },
      started_at: '2026-03-15T09:00:00Z',
      updated_at: '2026-03-15T09:01:00Z',
      done: true,
      error_message: null,
      artifacts: [
        {
          id: 'hot-load-trajectory',
          kind: 'hot_load_trajectory',
          updated_at: '2026-03-15T09:01:00Z',
          payload: {
            query: 'image reconstruction',
            query_normalized: 'image reconstruction',
            workflow: {
              workflow_id: 'workflow_hypothesis_candidate_cards',
              candidate_lane_mode: 'broad',
              mcp_fallback_used: false,
              verification_source: 'mcp_workflow',
            },
            resolved_anchor_bundle: [],
            candidate_cards: {
              total_count: 1,
              grounded_count: 0,
              weak_count: 1,
              draft_count: 0,
              verdict_counts: { uncertain: 1 },
              evidence_source_scope_counts: { hybrid_kg_literature: 1 },
              deep_research_status_counts: { ok: 1 },
            },
            evidence: {
              total_count: 2,
              grounding_quality: 'partial',
              deep_research_status: 'ready',
              source_channel_counts: { deep_research_live: 2 },
              quality_counts: { primary: 1, secondary: 1 },
            },
            deep_research: {
              used: true,
              pending: false,
              report_available: true,
            },
            warnings: [],
          },
        },
      ],
    } as never)

    const req = new NextRequest(
      'http://localhost/api/hypothesis/trajectory?runId=hrun-003&jsonl=1&download=1',
    )
    const res = await GET(req)
    const text = await res.text()

    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('application/x-ndjson')
    expect(res.headers.get('content-disposition')).toContain(
      'hot-load-trajectory-hrun-003.jsonl',
    )
    const lines = text.trim().split('\n')
    expect(lines).toHaveLength(1)
    expect(JSON.parse(lines[0])).toMatchObject({
      run_id: 'hrun-003',
      query: 'image reconstruction',
      verification_source: 'mcp_workflow',
    })
  })
})
