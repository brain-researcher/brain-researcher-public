import { NextRequest, NextResponse } from 'next/server'

import { resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * POST /api/plan
 *
 * Proxies to Agent planner to generate execution plans based on
 * pipeline, modality, and input specifications.
 *
 * Query params:
 *   - debug_selection: Set to "true" to include selection reasons in response (optional)
 *
 * Body: {
 *   pipeline?: string
 *   domain?: string
 *   modality?: string[]
 *   inputs?: Record<string, any>
 *   use_kg_hints?: boolean
 *   kg_hint_weight?: number
 *   promoted_weight?: number
 * }
 *
 * Returns: Agent plan response with chosen tools and optional selection_reasons
 */
export async function POST(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl
    const debugSelection = searchParams.get('debug_selection') === 'true'

    const agentUrl = resolveAgentBaseUrl()

    const targetUrl = `${agentUrl}/agent/plan`

    // Parse request body
    let body: any
    try {
      body = await request.json()
    } catch (error) {
      return NextResponse.json(
        { error: 'Invalid JSON in request body' },
        { status: 400 }
      )
    }

    // Inject debug_selection into body if requested via query param
    if (debugSelection && !body.debug_selection) {
      body.debug_selection = true
    }

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000) // 15s timeout for planning

    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    })

    clearTimeout(timeout)

    if (!response.ok) {
      // Try to get error details from response
      let errorDetails
      try {
        errorDetails = await response.json()
      } catch {
        errorDetails = { error: response.statusText }
      }

      console.error(
        `Agent plan failed: ${response.status} ${response.statusText}`,
        errorDetails
      )

      return NextResponse.json(
        {
          error: 'Plan generation failed',
          details: errorDetails,
        },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.error('Agent plan request timed out after 15s')
      return NextResponse.json(
        { error: 'Plan generation timed out' },
        { status: 504 }
      )
    }

    console.error('Error generating plan:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
