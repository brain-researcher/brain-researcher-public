import { NextRequest, NextResponse } from 'next/server'

import { resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * GET /api/kg/tools
 *
 * Proxies to Agent debug endpoint to fetch tools from the knowledge graph
 * with KG hints, promoted status, and runtime information.
 *
 * Query params:
 *   - intent: Operation/intent to search for (required)
 *   - pipeline: Pipeline context (optional)
 *   - per_family: Max tools per family to return (default: 5)
 *   - exposure: Optional repeated param to filter by exposure (chat/pipeline/cli/advanced/internal)
 *   - domain/function/risk: Optional metadata filters
 *
 * Returns: Agent debug response with tool families and tools
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl
    const intent = searchParams.get('intent')
    const pipeline = searchParams.get('pipeline')
    const perFamily = searchParams.get('per_family') || '5'
    const exposures = searchParams.getAll('exposure')
    const domain = searchParams.get('domain')
    const func = searchParams.get('function')
    const risk = searchParams.get('risk')

    if (!intent) {
      return NextResponse.json(
        { error: 'Missing required parameter: intent' },
        { status: 400 }
      )
    }

    const agentUrl = resolveAgentBaseUrl()

    // Build query string
    const params = new URLSearchParams({
      intent,
      per_family: perFamily,
    })

    if (pipeline) {
      params.append('pipeline', pipeline)
    }

    exposures.forEach(e => params.append('exposure', e))
    if (domain) params.append('domain', domain)
    if (func) params.append('function', func)
    if (risk) params.append('risk', risk)

    const targetUrl = `${agentUrl}/agent/debug/kg/tools?${params.toString()}`

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)

    const response = await fetch(targetUrl, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
    })

    clearTimeout(timeout)

    if (!response.ok) {
      console.error(
        `Agent debug/kg/tools failed: ${response.status} ${response.statusText}`
      )
      return NextResponse.json(
        { error: 'Failed to fetch tools from agent' },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.error('Agent tools request timed out')
      return NextResponse.json(
        { error: 'Request timed out' },
        { status: 504 }
      )
    }

    console.error('Error fetching tools:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
