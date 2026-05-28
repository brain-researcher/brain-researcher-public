import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HypothesisDeepResearchReportPage } from '../HypothesisDeepResearchReportPage'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('runId=hrun-test&sessionId=session-test'),
}))

describe('HypothesisDeepResearchReportPage', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('renders calibrated claim review as the primary synthesis and raw text as background trace', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          run: {
            artifacts: [
              {
                id: 'deep-research-report',
                kind: 'deep_research_report',
                payload: {
                  query: 'cross-cultural trust fMRI',
                  status: 'completed',
                  source_run_id: 'br-claim-review-page',
                  interaction_id: 'int-page',
                  idempotency_key: 'idem-page',
                  summary: 'Calibrated claim summary from claim_report.json.',
                  synthesis_full_text:
                    '## Calibrated Claim Review\n\nCalibrated claim summary from claim_report.json.',
                  raw_summary: 'Raw upstream summary.',
                  raw_synthesis_full_text:
                    'Raw upstream synthesis mentioning SUPPORTED and unresolved tension.',
                  claim_review: {
                    source_run_id: 'br-claim-review-page',
                    source_artifact: 'claim_report.json',
                    summary: 'Calibrated claim summary from claim_report.json.',
                    overall_verdict: 'indirectly_supported',
                    caveats: ['No direct single-study contrast was available.'],
                    unresolved_questions: ['TPJ direction remains unresolved.'],
                    claim_count: 1,
                    rendered_markdown:
                      '## Calibrated Claim Review\n\nCalibrated claim summary from claim_report.json.',
                  },
                  synthesis_generated_by: 'upstream',
                  synthesis_source_count: 2,
                  search_trails: [],
                  historical_trails_available: true,
                  source_inventory: [],
                  discarded_sources: [],
                  discarded_aggregates: [],
                  search_stats: {
                    scanned_count: 4,
                    qualifying_count: 2,
                    unique_after_dedupe_count: 2,
                    final_citable_count: 2,
                    discarded_count: 0,
                  },
                  generated_at: '2026-04-14T12:00:00.000Z',
                },
              },
            ],
          },
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      ),
    ) as unknown as typeof fetch

    render(<HypothesisDeepResearchReportPage />)

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Calibrated Claim Review/i }),
      ).toBeInTheDocument()
    })

    expect(screen.getByText(/claim verdict: indirectly_supported/i)).toBeInTheDocument()
    expect(screen.getByText(/source_run_id: br-claim-review-page/i)).toBeInTheDocument()
    expect(screen.getByText(/Background Synthesis Trace/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Raw upstream synthesis mentioning SUPPORTED and unresolved tension/i),
    ).toBeInTheDocument()
  })
})
