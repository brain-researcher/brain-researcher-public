import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const DEMO_ARTIFACT_MAP: Record<string, { target: string; filename: string }> = {
  base: {
    target: '/api/viz/demo/base?filename=demo_base.nii.gz',
    filename: 'demo_base.nii.gz',
  },
  overlay: {
    target: '/api/viz/demo/overlay?filename=demo_overlay.nii.gz',
    filename: 'demo_overlay.nii.gz',
  },
}

function normalizeKey(pathSegments: string[]): string {
  if (pathSegments.length === 0) return ''
  const last = pathSegments[pathSegments.length - 1].toLowerCase()
  if (last.includes('overlay')) return 'overlay'
  if (last.includes('base')) return 'base'
  if (last.includes('demo_overlay')) return 'overlay'
  if (last.includes('demo_base')) return 'base'
  return last.replace(/\.(nii|nii\.gz|mgz|mgh)$/i, '')
}

export async function GET(
  req: NextRequest,
  { params }: { params: { demoId: string; artifactPath: string[] } },
) {
  const artifactPath = Array.isArray(params.artifactPath) ? params.artifactPath : []
  const key = normalizeKey(artifactPath)
  const mapping = DEMO_ARTIFACT_MAP[key]
  if (!mapping) {
    return NextResponse.json({ detail: 'Demo artifact not found.' }, { status: 404 })
  }

  const targetUrl = new URL(mapping.target, req.nextUrl.origin)
  const upstream = await fetch(targetUrl.toString(), { method: 'GET', cache: 'no-store' })

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => '')
    return new NextResponse(text || upstream.statusText, {
      status: upstream.status,
      headers: { 'content-type': upstream.headers.get('content-type') || 'text/plain' },
    })
  }

  const responseHeaders = new Headers()
  responseHeaders.set('content-type', upstream.headers.get('content-type') || 'application/octet-stream')
  responseHeaders.set('cache-control', 'public, max-age=86400')
  responseHeaders.set('content-disposition', `attachment; filename="${mapping.filename}"`)

  return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders })
}
