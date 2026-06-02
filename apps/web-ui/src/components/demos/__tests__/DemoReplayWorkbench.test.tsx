// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DemoReplayWorkbench } from '../DemoReplayWorkbench'

vi.mock('@/components/navigation/navigation-wrapper', () => ({
  NavigationWrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const replayPayload = {
  demo: {
    slug: 'demo-one',
    title: 'Demo one',
    description: 'Demo replay with evidence',
  },
  analysis: {
    analysis_id: 'analysis_demo_one',
    status: 'completed',
    title: 'Demo one analysis',
    started_at: 1_700_000_000,
    finished_at: 1_700_000_010,
    warnings: [],
  },
  prompt: {
    primary_prompt: 'Explain a result.',
    followup_prompts: [],
    coding_agent_prompts: ['Use Codex for this replay.'],
    mcp_prompts: ['Use BR MCP for this replay.'],
    source_path: null,
  },
  replay: {
    source: 'bundle_steps',
    steps: [
      {
        step_id: 'step-1',
        stage: 'evidence',
        title: 'Collect evidence',
        status: 'completed',
        tool: 'kg_search_nodes',
        tool_calls: ['kg_search_nodes'],
        prompt_text: 'Find evidence.',
        response_text: 'Found evidence.',
        artifact_refs: ['artifact-1'],
        started_at: 1_700_000_000,
        finished_at: 1_700_000_010,
        duration_ms: 10_000,
      },
    ],
  },
  reference_output: {
    summary: 'Reference output summary.',
    highlights: [],
    documents: [],
    source_path: null,
  },
  reproduce: {
    requirements: [],
    commands: [],
    source_path: null,
  },
  bundle: {
    available: true,
    artifact_count: 2,
    source_run_ids: ['run-1'],
    items: [
      {
        id: 'report-pdf',
        name: 'report.pdf',
        path: 'reports/report.pdf',
        title: 'Case report PDF',
        mime_type: 'application/pdf',
        roles: ['reference_summary_source', 'evidence'],
        download_url: '/api/demo/bundles/demo-one/artifact?path=report-pdf',
      },
      {
        id: 'artifact-1',
        name: 'evidence.json',
        path: 'evidence.json',
        download_url: '/api/demo/bundles/demo-one/evidence.json',
      },
    ],
  },
  notes: [],
}

describe('DemoReplayWorkbench PDF-only rendering', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/demos/demo-one?view=evidence')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(replayPayload), { status: 200 })),
    )
  })

  it('renders only the report PDF and omits replay metadata', async () => {
    render(<DemoReplayWorkbench demoId="demo-one" />)

    await screen.findByText('Case report PDF')

    expect(screen.getByTitle('Demo report PDF')).toHaveAttribute(
      'src',
      '/api/demo/bundles/demo-one/artifact?path=report-pdf',
    )
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute(
      'href',
      '/api/demo/bundles/demo-one/artifact?path=report-pdf',
    )
    expect(screen.queryByText('What Happens')).not.toBeInTheDocument()
    expect(screen.queryByText('Prompt + Response')).not.toBeInTheDocument()
    expect(screen.queryByText('Evidence')).not.toBeInTheDocument()
    expect(screen.queryByText('Artifacts')).not.toBeInTheDocument()
    expect(screen.queryByText('Reference Output')).not.toBeInTheDocument()
    expect(screen.queryByText('Reproduce This')).not.toBeInTheDocument()
    expect(screen.queryByText('evidence.json')).not.toBeInTheDocument()
  })

  it('uses the reference summary PDF when multiple PDFs are present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              ...replayPayload,
              bundle: {
                ...replayPayload.bundle,
                artifact_count: 2,
                items: [
                  {
                    id: 'secondary-pdf',
                    name: 'appendix.pdf',
                    path: 'reports/appendix.pdf',
                    title: 'Appendix PDF',
                    mime_type: 'application/pdf',
                    download_url: '/api/demo/bundles/demo-one/artifact?path=secondary-pdf',
                  },
                  {
                    id: 'report-pdf',
                    name: 'report.pdf',
                    path: 'reports/report.pdf',
                    title: 'Case report PDF',
                    mime_type: 'application/pdf',
                    roles: ['reference_summary_source', 'evidence'],
                    download_url: '/api/demo/bundles/demo-one/artifact?path=report-pdf',
                  },
                  ...replayPayload.bundle.items,
                ],
              },
            }),
            { status: 200 },
          ),
      ),
    )

    render(<DemoReplayWorkbench demoId="demo-one" />)

    await screen.findByText('Case report PDF')

    expect(screen.getByText('Case report PDF')).toBeInTheDocument()
    expect(screen.getByTitle('Demo report PDF')).toHaveAttribute(
      'src',
      '/api/demo/bundles/demo-one/artifact?path=report-pdf',
    )
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute(
      'href',
      '/api/demo/bundles/demo-one/artifact?path=report-pdf',
    )
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute(
      'href',
      '/api/demo/bundles/demo-one/artifact?path=report-pdf&download=1',
    )
  })
})
