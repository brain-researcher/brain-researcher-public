import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders } from '@/lib/server/downstream'
import { normalizeKgSubpath, resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

async function proxy(request: NextRequest, { params }: { params: { path?: string[] } }) {
  const baseUrl = resolveKgBaseUrl()
  const subpath = normalizeKgSubpath(Array.isArray(params.path) ? params.path : [])
  const pathSuffix =
    subpath === 'subgraph' || subpath === 'graphql'
      ? subpath
      : subpath
        ? `api/${subpath}`
        : 'api'
  const upstreamUrl = new URL(`${baseUrl}/${pathSuffix}`)
  upstreamUrl.search = request.nextUrl.search

  const method = request.method.toUpperCase()
  const headers = forwardAuthHeaders(request)
  const contentType = request.headers.get('content-type')
  const accept = request.headers.get('accept')
  if (contentType) headers.set('content-type', contentType)
  if (accept) headers.set('accept', accept)

  let body: ArrayBuffer | undefined
  if (method !== 'GET' && method !== 'HEAD') {
    body = await request.arrayBuffer()
  }

  try {
    const res = await fetch(upstreamUrl.toString(), {
      method,
      headers,
      body,
      cache: 'no-store',
    })

    const passthrough = new Headers()
    const resContentType = res.headers.get('content-type')
    const resDisposition = res.headers.get('content-disposition')
    if (resContentType) passthrough.set('content-type', resContentType)
    if (resDisposition) passthrough.set('content-disposition', resDisposition)
    passthrough.set('cache-control', 'private, no-store, max-age=0')

    const payload = await res.arrayBuffer()
    return new NextResponse(payload, { status: res.status, headers: passthrough })
  } catch {
    return NextResponse.json({ ok: false, error: 'unreachable' }, { status: 503 })
  }
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
export const OPTIONS = proxy
