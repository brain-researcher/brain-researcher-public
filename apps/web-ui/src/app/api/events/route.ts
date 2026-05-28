import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(request: NextRequest) {
  const upstreamUrl = `${resolveOrchestratorBaseUrl()}/api/events`
  const headers = forwardAuthHeaders(request)
  headers.set('accept', 'application/json')

  const trackingId = request.headers.get('x-tracking-id')
  if (trackingId) {
    headers.set('x-tracking-id', trackingId)
  }

  const contentType = request.headers.get('content-type') || 'application/json'
  headers.set('content-type', contentType)

  try {
    const body = await request.text()
    const upstream = await fetch(upstreamUrl, {
      method: 'POST',
      headers,
      body,
      cache: 'no-store',
    })
    const text = await upstream.text()
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') || 'application/json',
        'cache-control': 'private, no-store, max-age=0',
      },
    })
  } catch (error) {
    console.error('[api/events] upstream request failed', error)
    return NextResponse.json({ detail: 'Analytics service temporarily unavailable' }, { status: 502 })
  }
}
