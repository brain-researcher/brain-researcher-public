import { NextRequest, NextResponse } from 'next/server'

import { bundleArtifacts, loadDemoRunBundle } from '@/lib/server/demo-bundles'
import { resolveDemoEntry } from '@/lib/server/demo-index'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  _req: NextRequest,
  { params }: { params: { demoId: string } },
) {
  const rawDemoId = typeof params.demoId === 'string' ? params.demoId.trim() : ''
  if (!rawDemoId) {
    return NextResponse.json({ detail: 'demoId is required.' }, { status: 400 })
  }

  const entry = resolveDemoEntry(rawDemoId)
  if (!entry) {
    return NextResponse.json({ detail: `Unknown demo "${rawDemoId}".` }, { status: 404 })
  }

  const bundle = loadDemoRunBundle(entry.slug)
  if (!bundle) {
    return NextResponse.json(
      {
        slug: entry.slug,
        available: false,
        artifact_count: 0,
        source_run_ids: entry.source_run_ids || [],
        items: [],
      },
      { status: 200 },
    )
  }

  const artifacts = bundleArtifacts(bundle)
  const artifactItems = artifacts.map((artifact) => {
    const clean = artifact.path.replace(/\\/g, '/')
    const name = clean.split('/').filter(Boolean).pop() || clean
    return {
      id: artifact.id,
      name,
      path: clean,
      title: artifact.title || null,
      stage: artifact.stage || null,
      roles: artifact.roles || [],
      mime_type: artifact.mime_type || 'application/octet-stream',
      download_url: `/api/demo/bundles/${encodeURIComponent(entry.slug)}/artifact?path=${encodeURIComponent(artifact.id || clean)}`,
    }
  })

  return NextResponse.json({
    slug: entry.slug,
    available: true,
    generated_at: bundle.generated_at || null,
    artifact_count:
      typeof bundle.artifact_count === 'number'
        ? bundle.artifact_count
        : artifacts.length,
    source_run_ids:
      (bundle.source_run_ids && bundle.source_run_ids.length > 0
        ? bundle.source_run_ids
        : entry.source_run_ids) || [],
    items: artifactItems,
  })
}
