import { describe, expect, it } from 'vitest'

import {
  extractHotLoadTrajectoryRow,
  summarizeHotLoadTrajectoryRows,
} from '@/lib/server/hypothesis-hot-load-trajectory'
import type { HypothesisRunSnapshot } from '@/types/hypothesis'

function buildSnapshot(): HypothesisRunSnapshot {
  return {
    run_id: 'hrun-trajectory-001',
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
          trajectory_version: 'v1',
          trigger_kind: 'free_text_query',
          query: 'fmri-based image decoding',
          query_normalized: 'fmri-based image decoding',
          captured_at: '2026-03-15T07:05:00Z',
          workflow: {
            workflow_id: 'workflow_hypothesis_candidate_cards',
            candidate_lane_mode: 'broad',
            mcp_fallback_used: false,
            verification_source: 'mcp_workflow',
          },
          resolved_anchor_bundle: [
            {
              kg_id: 'concept:image_decoding',
              label: 'Image decoding',
              node_type: 'Concept',
              matched_queries: ['fmri-based image decoding'],
              score: 0.93,
              rank: 1,
            },
          ],
          candidate_cards: {
            total_count: 2,
            grounded_count: 0,
            weak_count: 1,
            draft_count: 1,
            verdict_counts: {
              uncertain: 1,
              insufficient_evidence: 1,
            },
            evidence_source_scope_counts: {
              hybrid_kg_literature: 1,
            },
            deep_research_status_counts: {
              ok: 1,
            },
          },
          evidence: {
            total_count: 4,
            grounding_quality: 'partial',
            deep_research_status: 'ready',
            source_channel_counts: {
              deep_research_live: 3,
              graph: 1,
            },
            quality_counts: {
              primary: 2,
              secondary: 1,
              tertiary: 1,
            },
          },
          deep_research: {
            used: true,
            pending: false,
            report_available: true,
            report_artifact_id: 'deep-research-report',
            warning: null,
          },
          ephemeral_weighted_subgraph: {
            available: true,
            node_count: 7,
            edge_count: 6,
            card_subgraph_count: 2,
          },
          warnings: ['candidate_only_surface'],
        },
      },
    ],
  }
}

describe('hypothesis hot-load trajectory helper', () => {
  it('extracts a normalized row from a run snapshot', () => {
    const row = extractHotLoadTrajectoryRow(buildSnapshot())

    expect(row).toBeTruthy()
    expect(row?.query).toBe('fmri-based image decoding')
    expect(row?.workflow_id).toBe('workflow_hypothesis_candidate_cards')
    expect(row?.candidate_lane_mode).toBe('broad')
    expect(row?.resolved_anchor_count).toBe(1)
    expect(row?.top_anchor_labels).toEqual(['Image decoding'])
    expect(row?.verdict_counts).toEqual({
      uncertain: 1,
      insufficient_evidence: 1,
    })
    expect(row?.evidence_source_scope_counts).toEqual({
      hybrid_kg_literature: 1,
    })
    expect(row?.ephemeral_weighted_subgraph_available).toBe(true)
    expect(row?.ephemeral_weighted_subgraph_node_count).toBe(7)
    expect(row?.ephemeral_weighted_subgraph_edge_count).toBe(6)
  })

  it('summarizes multiple trajectory rows', () => {
    const row = extractHotLoadTrajectoryRow(buildSnapshot())
    const summary = summarizeHotLoadTrajectoryRows(row ? [row, { ...row, run_id: 'hrun-2' }] : [])

    expect(summary).toEqual({
      total_rows: 2,
      unique_queries: 1,
      unique_sessions: 1,
      mcp_fallback_rows: 0,
      deep_research_ready_rows: 2,
      verification_source_counts: {
        mcp_workflow: 2,
      },
      deep_research_status_counts: {
        ready: 2,
      },
    })
  })
})
