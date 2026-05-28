import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { getVerifiedBearerToken } from '@/lib/server/request-auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

type HubRouteContext = {
  params: {
    path: string[]
  }
}

async function proxyHubRequest(request: NextRequest, context: HubRouteContext) {
  const subPath = context.params.path.join('/')
  const orchestratorBase = resolveOrchestratorBaseUrl()
  const url = new URL(request.url)
  const qs = url.search || ''
  const upstreamUrl = `${orchestratorBase}/api/hub/${subPath}${qs}`

  const headers = forwardAuthHeaders(request)
  const verifiedBearer = await getVerifiedBearerToken(request)
  if (verifiedBearer) {
    headers.set('authorization', `Bearer ${verifiedBearer}`)
  }
  const contentType = request.headers.get('content-type')
  const accept = request.headers.get('accept')
  if (contentType) headers.set('content-type', contentType)
  if (accept) headers.set('accept', accept)

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: 'no-store',
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    const body = await request.text()
    if (body) {
      init.body = body
    }
  }

  try {
    const upstream = await fetch(upstreamUrl, init)
    const body = await upstream.text().catch(() => '')
    return new NextResponse(body || upstream.statusText, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') || 'application/json',
      },
    })
  } catch (error) {
    console.error(`[api/hub/${subPath}] upstream request failed`, error)
    return NextResponse.json({ detail: 'Hub gateway temporarily unavailable' }, { status: 502 })
  }
}

export async function GET(request: NextRequest, context: HubRouteContext) {
  return proxyHubRequest(request, context)
}

export async function POST(request: NextRequest, context: HubRouteContext) {
  return proxyHubRequest(request, context)
}

export async function PATCH(request: NextRequest, context: HubRouteContext) {
  return proxyHubRequest(request, context)
}

export async function PUT(request: NextRequest, context: HubRouteContext) {
  return proxyHubRequest(request, context)
}

export async function DELETE(request: NextRequest, context: HubRouteContext) {
  return proxyHubRequest(request, context)
}
