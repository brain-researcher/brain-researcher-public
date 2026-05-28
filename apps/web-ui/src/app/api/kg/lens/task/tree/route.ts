import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders } from '@/lib/server/downstream'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(request: NextRequest) {
  const baseUrl = resolveKgBaseUrl()
  const upstreamUrl = new URL(`${baseUrl}/api/kg/lens/task/tree`)
  upstreamUrl.search = request.nextUrl.search

  const headers = forwardAuthHeaders(request)
  const accept = request.headers.get('accept')
  if (accept) headers.set('accept', accept)

  try {
    const response = await fetch(upstreamUrl.toString(), {
      method: 'GET',
      headers,
      cache: 'no-store',
    })

    if (!response.ok) {
      return NextResponse.json({
        ok: false,
        error: 'unavailable',
        upstream_status: response.status,
      })
    }

    const contentType = response.headers.get('content-type') || 'application/json'
    const payload = await response.arrayBuffer()
    return new NextResponse(payload, {
      status: 200,
      headers: {
        'content-type': contentType,
        'cache-control': 'private, no-store, max-age=0',
      },
    })
  } catch {
    return NextResponse.json({
      ok: false,
      error: 'unreachable',
      upstream_status: 503,
    })
  }
}
