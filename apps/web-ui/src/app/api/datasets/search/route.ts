import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const headers = forwardAuthHeaders(request)
    headers.set('content-type', 'application/json')

    const response = await fetch(`${resolveAgentBaseUrl()}/api/datasets/search`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Error searching datasets:', error)
    return NextResponse.json(
      { error: 'search_failed', detail: 'Failed to search datasets' },
      { status: 500 }
    )
  }
}
