import { NextRequest, NextResponse } from 'next/server'

import { loadDemoRunBundleSummary } from '@/lib/server/demo-bundles'
import { loadDemoIndex } from '@/lib/server/demo-index'
import { ensureDemoRunsExist } from '@/lib/server/demo-seed'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function demoTier(demo: {
  slug?: string
  demo_type?: string
  tags?: string[]
}): number {
  const slug = (demo.slug || '').toLowerCase()
  const demoType = (demo.demo_type || '').toLowerCase()
  const tags = Array.isArray(demo.tags)
    ? demo.tags.map((value) => String(value).toLowerCase())
    : []

  if (slug.startsWith('case1-') || tags.includes('case1')) return 1
  if (slug.startsWith('case2-') || tags.includes('case2')) return 2
  if (slug.startsWith('case3-') || tags.includes('case3')) return 3
  if (slug.startsWith('case4-') || tags.includes('case4')) return 4
  if (slug.startsWith('bounded-self-evolving-') || tags.includes('bounded-self-evolving')) {
    return 5
  }
  if (slug.startsWith('uc1-') || tags.includes('uc1')) return 6
  if (slug.startsWith('uc2-') || tags.includes('uc2')) return 7
  if (slug.startsWith('uc3-') || tags.includes('uc3')) return 8
  if (
    demoType === 'exploration' ||
    slug.includes('exploration') ||
    tags.includes('exploration')
  ) {
    return 9
  }
  return 10
}

export async function GET(_req: NextRequest) {
  const index = loadDemoIndex()
  const demos = Array.isArray(index.demos) ? index.demos : []
  await ensureDemoRunsExist(demos)
  const demosWithBundles = demos
    .map((demo) => {
      const summary = loadDemoRunBundleSummary(demo.slug)
      return {
        ...demo,
        bundle_available: summary.available,
        bundle_artifact_count: summary.artifact_count,
        bundle_generated_at: summary.generated_at,
        bundle_source_run_ids: summary.source_run_ids,
      }
    })
    .sort((a, b) => {
      const tierDiff = demoTier(a) - demoTier(b)
      if (tierDiff !== 0) return tierDiff
      if ((a.slug || '') && (b.slug || '')) {
        return String(a.slug).localeCompare(String(b.slug))
      }
      return String(a.title || '').localeCompare(String(b.title || ''))
    })

  return NextResponse.json({ demos: demosWithBundles })
}
