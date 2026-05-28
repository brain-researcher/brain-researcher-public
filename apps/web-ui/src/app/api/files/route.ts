import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${resolveAgentBaseUrl()}/api/files`, {
      method: 'GET',
      headers: forwardAuthHeaders(request),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Error listing files:', error)
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to list files' },
      { status: 503 }
    )
  }
}
