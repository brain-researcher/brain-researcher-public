import { describe, expect, it } from 'vitest'

import {
  isChartCsvArtifact,
  isChartImageArtifact,
  parseCsvPreview,
  splitDemoChartArtifacts,
  type DemoBundleArtifactItem,
} from '@/lib/charts/demo-chart-artifacts'

const makeArtifact = (overrides: Partial<DemoBundleArtifactItem>): DemoBundleArtifactItem => ({
  path: '/tmp/artifact',
  download_url: '/api/demo/file',
  ...overrides,
})

describe('demo chart artifacts', () => {
  it('classifies image artifacts by mime type and extension', () => {
    expect(
      isChartImageArtifact(makeArtifact({ mime_type: 'image/png', path: 'figure.dat' })),
    ).toBe(true)
    expect(
      isChartImageArtifact(makeArtifact({ mime_type: 'application/octet-stream', path: 'figure.svg' })),
    ).toBe(true)
    expect(
      isChartImageArtifact(makeArtifact({ mime_type: 'text/plain', name: 'plot.jpeg' })),
    ).toBe(true)
    expect(
      isChartImageArtifact(makeArtifact({ mime_type: 'text/csv', path: 'table.csv' })),
    ).toBe(false)
  })

  it('classifies csv artifacts by mime type and extension', () => {
    expect(
      isChartCsvArtifact(makeArtifact({ mime_type: 'text/csv', path: 'sample.bin' })),
    ).toBe(true)
    expect(
      isChartCsvArtifact(
        makeArtifact({ mime_type: 'application/octet-stream', path: 'summary.csv' }),
      ),
    ).toBe(true)
    expect(
      isChartCsvArtifact(makeArtifact({ mime_type: 'text/tab-separated-values', path: 'x.tsv' })),
    ).toBe(true)
    expect(
      isChartCsvArtifact(makeArtifact({ mime_type: 'image/png', path: 'figure.png' })),
    ).toBe(false)
  })

  it('splits image/csv chart artifacts from a mixed artifact list', () => {
    const artifacts: DemoBundleArtifactItem[] = [
      makeArtifact({ id: 'img1', mime_type: 'image/png', path: 'a.png' }),
      makeArtifact({ id: 'csv1', mime_type: 'text/csv', path: 'b.csv' }),
      makeArtifact({ id: 'txt1', mime_type: 'text/plain', path: 'notes.txt' }),
      makeArtifact({ id: 'img2', mime_type: 'application/octet-stream', path: 'c.svg' }),
    ]
    const grouped = splitDemoChartArtifacts(artifacts)

    expect(grouped.images.map((item) => item.id)).toEqual(['img1', 'img2'])
    expect(grouped.csvs.map((item) => item.id)).toEqual(['csv1'])
  })

  it('parses csv preview with quoted values and truncation', () => {
    const csv = [
      'subject,metric,note',
      'sub-01,0.42,"good, stable"',
      'sub-02,0.18,warning',
      'sub-03,0.33,ok',
    ].join('\n')

    const preview = parseCsvPreview(csv, 3, 3)
    expect(preview).not.toBeNull()
    expect(preview?.header).toEqual(['subject', 'metric', 'note'])
    expect(preview?.rows[0]).toEqual(['sub-01', '0.42', 'good, stable'])
    expect(preview?.rows.length).toBe(2)
    expect(preview?.truncated).toBe(true)
  })

  it('returns null for empty csv content', () => {
    expect(parseCsvPreview(' \n \n')).toBeNull()
  })
})
