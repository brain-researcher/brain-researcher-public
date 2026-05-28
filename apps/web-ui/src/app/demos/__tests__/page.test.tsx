import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import DemosPage from '../page'

vi.mock('@/components/navigation/navigation-wrapper', () => ({
  NavigationWrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@/lib/server/demo-index', () => ({
  loadDemoIndex: () => ({
    demos: [
      {
        slug: 'case2-cocaine-network-segregation',
        analysis_id: 'run_case2',
        title: 'Case 2: Cocaine Network Segregation Robustness',
        description: 'Case 2 report.',
        demo_type: 'manuscript_case_report',
        stage_tags: ['R5'],
        tags: ['case2'],
      },
      {
        slug: 'case1-neuromark-schizophrenia-multiverse',
        analysis_id: 'run_case1',
        title: 'Case 1: NeuroMark Schizophrenia Multiverse Analysis',
        description: 'Case 1 report.',
        demo_type: 'manuscript_case_report',
        stage_tags: ['R5'],
        tags: ['case1'],
      },
    ],
  }),
}))

vi.mock('@/lib/server/demo-bundles', () => ({
  loadDemoRunBundle: (slug: string) =>
    slug.startsWith('case1-')
      ? {
          artifact_count: 1,
          artifacts: [
            {
              id: 'a001',
              path: 'reports/case1.pdf',
              mime_type: 'application/pdf',
              roles: ['reference_summary_source', 'evidence'],
              title: 'Case 1 PDF report',
            },
          ],
        }
      : null,
  bundleArtifacts: (bundle: { artifacts?: unknown[] } | null) => bundle?.artifacts ?? [],
}))

describe('DemosPage', () => {
  it('renders a meaningful demo catalog instead of falling through to Home', () => {
    render(<DemosPage />)

    expect(
      screen.getByRole('heading', { name: /Demos and use cases/i }),
    ).toBeInTheDocument()

    const [case1] = screen.getAllByRole('link', {
      name: /Open use case/i,
    }) as HTMLAnchorElement[]
    expect(case1.getAttribute('href')).toBe(
      '/demos/case1-neuromark-schizophrenia-multiverse',
    )
    expect(
      screen.getByText('Case 1: NeuroMark Schizophrenia Multiverse Analysis'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Case 2: Cocaine Network Segregation Robustness'),
    ).toBeInTheDocument()
    expect(screen.getByText('Report: Case 1 PDF report')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open report PDF/i })).toHaveAttribute(
      'href',
      '/api/demo/bundles/case1-neuromark-schizophrenia-multiverse/artifact?path=a001',
    )
  })

  it('does not keep the legacy /demos to Home redirect', () => {
    const config = readFileSync(join(process.cwd(), 'next.config.js'), 'utf8')

    expect(config).not.toContain("source: '/demos', destination: '/'")
  })
})
