import fs from 'fs'

import { NextRequest, NextResponse } from 'next/server'

import { resolveBundleArtifactFile } from '@/lib/server/demo-bundles'
import { resolveDemoEntry } from '@/lib/server/demo-index'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { demoId: string } },
) {
  const rawDemoId = typeof params.demoId === 'string' ? params.demoId.trim() : ''
  if (!rawDemoId) {
    return NextResponse.json({ detail: 'demoId is required.' }, { status: 400 })
  }
  const artifactPath = req.nextUrl.searchParams.get('path')?.trim() || ''
  if (!artifactPath) {
    return NextResponse.json({ detail: 'path query param is required.' }, { status: 400 })
  }

  const entry = resolveDemoEntry(rawDemoId)
  if (!entry) {
    return NextResponse.json({ detail: `Unknown demo "${rawDemoId}".` }, { status: 404 })
  }

  const resolved = resolveBundleArtifactFile(entry.slug, artifactPath)
  if (!resolved) {
    return NextResponse.json(
      { detail: 'Artifact is not available for this demo.' },
      { status: 404 },
    )
  }

  const body = fs.readFileSync(resolved.filePath)
  const filename = resolved.filePath.split('/').pop() || 'artifact'
  return new NextResponse(body, {
    status: 200,
    headers: {
      'content-type': resolved.mimeType,
      'content-disposition': `inline; filename="${filename}"`,
      'cache-control': 'no-store',
    },
  })
}
