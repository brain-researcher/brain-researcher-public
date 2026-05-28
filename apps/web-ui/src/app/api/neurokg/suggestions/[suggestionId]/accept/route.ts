import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(
  req: NextRequest,
  { params }: { params: { suggestionId: string } },
) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  const suggestionId = params.suggestionId
  const headers = forwardAuthHeaders(req)

  let upstream: Response
  try {
    upstream = await fetch(`${resolveAgentBaseUrl()}/api/neurokg/suggestions/${suggestionId}/accept`, {
      method: 'POST',
      headers,
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'BR-KG suggestions unavailable.' },
      { status: 503 },
    )
  }

  if (upstream.status === 404 || upstream.status === 501) {
    return NextResponse.json(
      { error: 'E-NOT-IMPLEMENTED', detail: 'Accept endpoint not available.' },
      { status: 501 },
    )
  }

  const raw = await upstream.text().catch(() => '')
  if (!upstream.ok) {
    return new NextResponse(raw, {
      status: upstream.status,
      headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' },
    })
  }

  let payload: unknown = null
  try {
    payload = raw ? JSON.parse(raw) : null
  } catch {
    payload = null
  }

  return NextResponse.json(payload ?? { ok: true })
}

