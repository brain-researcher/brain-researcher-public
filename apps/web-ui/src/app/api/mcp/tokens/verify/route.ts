import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(request: NextRequest) {
  const authenticated = await isRequestAuthenticated(request)
  if (!authenticated) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 })
  }

  const orchestratorBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchestratorBase}/auth/mcp-tokens/verify`
  const headers = forwardAuthHeaders(request)
  headers.set('accept', 'application/json')

  try {
    const upstream = await fetch(upstreamUrl, {
      method: 'GET',
      headers,
      cache: 'no-store',
    })
    const raw = await upstream.text()
    const contentType = upstream.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const body = isJson ? JSON.parse(raw || '{}') : { detail: raw || 'Upstream request failed' }
    return NextResponse.json(body, { status: upstream.status })
  } catch (error) {
    console.error('[api/mcp/tokens/verify] upstream request failed', error)
    return NextResponse.json({ detail: 'MCP token service temporarily unavailable' }, { status: 502 })
  }
}
