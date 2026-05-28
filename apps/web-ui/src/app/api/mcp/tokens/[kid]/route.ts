import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function DELETE(
  request: NextRequest,
  { params }: { params: { kid: string } },
) {
  const authenticated = await isRequestAuthenticated(request)
  if (!authenticated) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 })
  }

  const kid = params.kid?.trim()
  if (!kid) {
    return NextResponse.json({ detail: 'Token id is required' }, { status: 400 })
  }

  const orchestratorBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchestratorBase}/auth/mcp-tokens/${encodeURIComponent(kid)}`
  const headers = forwardAuthHeaders(request)
  headers.set('accept', 'application/json')

  try {
    const upstream = await fetch(upstreamUrl, {
      method: 'DELETE',
      headers,
      cache: 'no-store',
    })
    const raw = await upstream.text()
    const contentType = upstream.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const body = isJson ? JSON.parse(raw || '{}') : { detail: raw || 'Upstream request failed' }
    return NextResponse.json(body, { status: upstream.status })
  } catch (error) {
    console.error(`[api/mcp/tokens/${kid}] upstream request failed`, error)
    return NextResponse.json({ detail: 'MCP token service temporarily unavailable' }, { status: 502 })
  }
}
