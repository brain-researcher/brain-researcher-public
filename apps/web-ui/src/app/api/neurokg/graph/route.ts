import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders } from '@/lib/server/downstream'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

const STATIC_EXPORT = process.env.NEXT_ENABLE_STATIC_EXPORT === 'true'

export const dynamic = STATIC_EXPORT ? 'error' : 'force-dynamic'
export const revalidate = 0

export async function GET(request: NextRequest) {
  if (STATIC_EXPORT) {
    return NextResponse.json(
      { ok: false, error: 'BR-KG proxy disabled in static export. Use NEUROKG_URL directly.' },
      { status: 503 },
    )
  }

  const searchParams = request.nextUrl.searchParams

  try {
    const baseUrl = resolveKgBaseUrl()
    const graphUrl = new URL(`${baseUrl}/api/graph`)

    // Preserve all query params from the UI request (e.g. scheme=ONVOC) so the
    // Knowledge Graph UI renders the expected view.
    searchParams.forEach((value, key) => {
      graphUrl.searchParams.append(key, value)
    })
    if (!searchParams.has('limit')) {
      graphUrl.searchParams.set('limit', '100')
    }

    const headers = forwardAuthHeaders(request)
    const accept = request.headers.get('accept')
    if (accept) headers.set('accept', accept)

    const res = await fetch(graphUrl.toString(), {
      method: 'GET',
      headers,
      cache: 'no-store',
    })

    const passthrough = new Headers()
    passthrough.set('cache-control', 'private, no-store, max-age=0')
    const contentType = res.headers.get('content-type')
    if (contentType) passthrough.set('content-type', contentType)

    const payload = await res.arrayBuffer()
    return new NextResponse(payload, { status: res.status, headers: passthrough })
  } catch (error) {
    return NextResponse.json({ ok: false, error: 'unreachable' }, { status: 503 })
  }
}
