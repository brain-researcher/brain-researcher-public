import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

async function proxyToOrchestrator(
  request: NextRequest,
  targetPath: string,
  method: 'GET' | 'POST',
) {
  const authenticated = await isRequestAuthenticated(request)
  if (!authenticated) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 })
  }

  const orchestratorBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchestratorBase}${targetPath}`
  const headers = forwardAuthHeaders(request)
  headers.set('accept', 'application/json')

  const init: RequestInit = {
    method,
    headers,
    cache: 'no-store',
  }

  if (method === 'POST') {
    headers.set('content-type', 'application/json')
    const body = await request.text()
    init.body = body || '{}'
  }

  try {
    const upstream = await fetch(upstreamUrl, init)
    const raw = await upstream.text()
    const contentType = upstream.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const body = isJson ? JSON.parse(raw || '{}') : { detail: raw || 'Upstream request failed' }
    return NextResponse.json(body, { status: upstream.status })
  } catch (error) {
    console.error(`[api/mcp/tokens:${method}] upstream request failed`, error)
    return NextResponse.json({ detail: 'MCP token service temporarily unavailable' }, { status: 502 })
  }
}

export async function GET(request: NextRequest) {
  return proxyToOrchestrator(request, '/auth/mcp-tokens', 'GET')
}

export async function POST(request: NextRequest) {
  return proxyToOrchestrator(request, '/auth/mcp-tokens', 'POST')
}
