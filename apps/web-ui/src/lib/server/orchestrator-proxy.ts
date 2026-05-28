import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export async function requireAuth(req: NextRequest): Promise<NextResponse | null> {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
  }
  return null
}

export async function proxyJson(
  req: NextRequest,
  targetUrl: string,
  init: RequestInit = {},
): Promise<NextResponse> {
  const headers = new Headers(init.headers)
  const authHeaders = forwardAuthHeaders(req)
  authHeaders.forEach((value, key) => headers.set(key, value))

  const upstream = await fetch(targetUrl, {
    ...init,
    headers,
    cache: init.cache ?? 'no-store',
  })
  const body = await upstream.text().catch(() => '')
  return new NextResponse(body || upstream.statusText, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/json',
    },
  })
}

export async function proxyStream(req: NextRequest, targetUrl: string): Promise<NextResponse> {
  const headers = forwardAuthHeaders(req)
  const upstream = await fetch(targetUrl, {
    method: 'GET',
    headers,
    cache: 'no-store',
  })

  if (!upstream.ok || !upstream.body) {
    const body = await upstream.text().catch(() => '')
    return new NextResponse(body || upstream.statusText, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') || 'application/json',
      },
    })
  }

  const responseHeaders = new Headers()
  const contentType = upstream.headers.get('content-type') || 'text/event-stream'
  responseHeaders.set('content-type', contentType)
  const cacheControl = upstream.headers.get('cache-control')
  if (cacheControl) {
    responseHeaders.set('cache-control', cacheControl)
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  })
}
