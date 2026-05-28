import { NextRequest, NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * GET /api/kg/search
 *
 * Searches the knowledge graph for nodes matching a query.
 *
 * Query params:
 *   - q: Search query (required)
 *   - limit: Max results to return (default: 20)
 *
 * Returns: {
 *   operations: Array<{id: string, name: string, description?: string}>
 *   synonyms: Array<{term: string, maps_to?: string}>
 * }
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl
    const query = searchParams.get('q')
    const limit = parseInt(searchParams.get('limit') || '20', 10)

    if (!query) {
      return NextResponse.json(
        { error: 'Missing required parameter: q' },
        { status: 400 }
      )
    }

    // Prefer server-side env vars (runtime), since NEXT_PUBLIC_* can be inlined at build time.
    const baseUrl = resolveKgBaseUrl()

    // Use BR-KG's search endpoint and normalize results into the legacy UI shape.
    // BR-KG: POST /api/search (alias: POST /api/kg/search)
    const queryUrl = `${baseUrl}/api/kg/search?format=list`

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)

    const response = await fetch(queryUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        limit,
      }),
      signal: controller.signal,
      cache: 'no-store',
    })

    clearTimeout(timeout)

    if (!response.ok) {
      console.error(
        `BR-KG search failed: ${response.status} ${response.statusText}`
      )
      return NextResponse.json(
        { error: 'Search failed' },
        { status: response.status }
      )
    }

    const data = await response.json()

    const resultList = Array.isArray(data) ? data : Array.isArray(data?.results) ? data.results : []
    const operations = resultList
      .map((r: any) => {
        const nodeId = String(r?.node_id ?? r?.nodeId ?? '').trim()
        const props = (r?.properties && typeof r.properties === 'object') ? r.properties : {}
        const nameCandidate =
          props.name ??
          props.label ??
          props.title ??
          props.dataset_id ??
          props.id ??
          nodeId
        const descriptionCandidate =
          props.description ??
          props.definition ??
          props.definition_text ??
          props.summary ??
          ''

        const id = nodeId || String(props.id ?? '').trim()
        const name = String(nameCandidate ?? '').trim()
        const description = String(descriptionCandidate ?? '').trim() || undefined
        if (!id || !name) return null
        return { id, name, description }
      })
      .filter(Boolean)

    // BR-KG search results do not currently emit synonym mappings in a stable schema.
    const synonyms: Array<{ term: string; maps_to?: string }> = []

    return NextResponse.json({
      operations,
      synonyms,
    })
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.error('BR-KG search timed out')
      return NextResponse.json(
        { error: 'Request timed out' },
        { status: 504 }
      )
    }

    console.error('Error searching knowledge graph:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
