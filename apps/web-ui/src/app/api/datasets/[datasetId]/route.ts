import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

export async function GET(
  request: NextRequest,
  { params }: { params: { datasetId: string } }
) {
  const { datasetId } = params

  try {
    const response = await fetch(`${resolveAgentBaseUrl()}/api/datasets/${encodeURIComponent(datasetId)}`, {
      method: 'GET',
      headers: forwardAuthHeaders(request),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Error fetching dataset:', error)
    return NextResponse.json(
      { error: 'fetch_failed', detail: 'Failed to fetch dataset' },
      { status: 500 }
    )
  }
}
