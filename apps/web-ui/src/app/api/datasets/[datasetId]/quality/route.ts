import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(
  request: NextRequest,
  { params }: { params: { datasetId: string } },
) {
  const { datasetId } = params

  try {
    const headers = forwardAuthHeaders(request)
    headers.set('content-type', 'application/json')

    const response = await fetch(
      `${resolveAgentBaseUrl()}/api/datasets/${encodeURIComponent(datasetId)}/quality`,
      {
        method: 'GET',
        headers,
        cache: 'no-store',
      },
    )

    const text = await response.text().catch(() => '')
    let json: any = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      json = null
    }

    return NextResponse.json(
      json ?? { error: 'invalid_json', detail: text || response.statusText },
      { status: response.status },
    )
  } catch (error) {
    console.error('Error fetching dataset quality:', error)
    return NextResponse.json(
      { error: 'fetch_failed', detail: 'Failed to fetch dataset quality' },
      { status: 500 },
    )
  }
}
