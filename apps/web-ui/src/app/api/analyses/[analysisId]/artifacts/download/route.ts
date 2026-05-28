import { NextRequest, NextResponse } from 'next/server'

import {
  forwardAuthHeaders,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

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

function mustMatchAnalysisId(path: string, analysisId: string): boolean {
  const decoded = decodeURIComponent(analysisId)
  const jobMatch = /^\/api\/jobs\/([^/]+)\//.exec(path)
  if (jobMatch) return decodeURIComponent(jobMatch[1]) === decoded
  return true
}

function isAllowedArtifactPath(path: string): boolean {
  return /^\/api\/jobs\/[^/]+\/artifacts\/files(?:\/|$|\?)/.test(path)
}

export async function GET(req: NextRequest, { params }: { params: { analysisId: string } }) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
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

  if (!isAllowedArtifactPath(normalized)) {
    return NextResponse.json(
      { detail: 'Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.' },
      { status: 400 },
    )
  }

  if (!mustMatchAnalysisId(normalized, analysisId)) {
    return NextResponse.json(
      { detail: 'Requested artifact does not belong to this analysis.' },
      { status: 403 },
    )
  }

  const headers = forwardAuthHeaders(req)
  const range = req.headers.get('range')
  if (range) headers.set('range', range)

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
