import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import {
  isCanonicalJobArtifactPath,
  mustMatchAnalysisId,
  resolveSharedAnalysisAccess,
  shouldAllowSummaryArtifactPath,
} from '@/lib/server/share-access'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const PASSTHROUGH_HEADERS = [
  'content-type',
  'content-length',
  'content-disposition',
  'content-range',
  'accept-ranges',
  'etag',
  'last-modified',
] as const

function proxyResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers()
  for (const key of PASSTHROUGH_HEADERS) {
    const value = upstream.get(key)
    if (value) headers.set(key, value)
  }
  headers.set('cache-control', 'private, no-store, max-age=0')
  return headers
}

function normalizeRelativeUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return null
  if (!trimmed.startsWith('/')) return null
  if (trimmed.includes('\0')) return null
  if (trimmed.includes('\\')) return null

  try {
    const parsed = new URL(trimmed, 'http://localhost')
    return `${parsed.pathname}${parsed.search}`
  } catch {
    return null
  }
}

export async function GET(req: NextRequest, { params }: { params: { token: string } }) {
  const token = typeof params.token === 'string' ? params.token.trim() : ''
  const resolved = await resolveSharedAnalysisAccess(token)
  if (resolved.ok === false) {
    return NextResponse.json(resolved.body, { status: resolved.status })
  }

  const rawUrl = req.nextUrl.searchParams.get('url') || ''
  const normalized = normalizeRelativeUrl(rawUrl)
  if (!normalized) {
    return NextResponse.json(
      { detail: 'url must be a relative /api/... path (absolute URLs are not allowed).' },
      { status: 400 },
    )
  }

  if (
    normalized.startsWith('/api/analyses/') ||
    normalized.startsWith('/api/share/') ||
    normalized.includes('/artifacts/download')
  ) {
    return NextResponse.json({ detail: 'Refusing to proxy nested Web UI API routes.' }, { status: 400 })
  }

  if (!isCanonicalJobArtifactPath(normalized)) {
    return NextResponse.json(
      { detail: 'Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.' },
      { status: 400 },
    )
  }

  if (!mustMatchAnalysisId(normalized, resolved.analysisId)) {
    return NextResponse.json(
      { detail: 'Requested artifact does not belong to this analysis.' },
      { status: 403 },
    )
  }

  if (resolved.shareLevel === 'summary' && !shouldAllowSummaryArtifactPath(normalized)) {
    return NextResponse.json(
      { detail: 'This shared link is summary-only; this artifact is not available.' },
      { status: 403 },
    )
  }

  const headers = new Headers()
  const range = req.headers.get('range')
  if (range) headers.set('range', range)

  if (process.env.NODE_ENV !== 'production') {
    const fallbackUser = process.env.DEMO_DEBUG_USER || process.env.DEV_CREDENTIALS_EMAIL
    if (fallbackUser) {
      headers.set('x-debug-user', fallbackUser)
    }
  }

  const upstreamUrl = `${resolveOrchestratorBaseUrl()}${normalized}`

  let upstream: Response
  try {
    upstream = await fetch(upstreamUrl, { method: 'GET', headers, cache: 'no-store' })
  } catch (error) {
    return NextResponse.json(
      {
        error: 'E-UPSTREAM-UNAVAILABLE',
        detail:
          process.env.NODE_ENV === 'production'
            ? 'Failed to download artifact.'
            : `Failed to download artifact: ${String(error)}`,
      },
      { status: 503 },
    )
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: proxyResponseHeaders(upstream.headers),
  })
}
