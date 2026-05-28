import { NextRequest, NextResponse } from 'next/server'

import { loadDemoRunBundleSummary } from '@/lib/server/demo-bundles'
import { loadDemoIndex } from '@/lib/server/demo-index'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  const index = loadDemoIndex()
  const demos = Array.isArray(index.demos) ? index.demos : []
  const bundles = demos.map((demo) => {
    const summary = loadDemoRunBundleSummary(demo.slug)
    return {
      slug: demo.slug,
      analysis_id: demo.analysis_id,
      title: demo.title,
      available: summary.available,
      artifact_count: summary.artifact_count,
      generated_at: summary.generated_at || null,
      source_run_ids: summary.source_run_ids,
    }
  })
  return NextResponse.json({ bundles })
}
