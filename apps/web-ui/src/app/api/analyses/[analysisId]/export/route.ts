import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
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

  const headers = forwardAuthHeaders(req)
  const range = req.headers.get('range')
  if (range) headers.set('range', range)

  const orchBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchBase}/api/analyses/${encodeURIComponent(analysisId)}/export`

  let upstream: Response
  try {
    upstream = await fetch(upstreamUrl, { method: 'GET', headers, cache: 'no-store' })
  } catch (error) {
    return NextResponse.json(
      {
        error: 'E-UPSTREAM-UNAVAILABLE',
        detail:
          process.env.NODE_ENV === 'production'
            ? 'Failed to fetch export bundle.'
            : `Failed to fetch export bundle: ${String(error)}`,
      },
      { status: 503 },
    )
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: proxyResponseHeaders(upstream.headers),
  })
}

