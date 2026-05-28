import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest) {
  try {
    // Forward the multipart form data to Agent
    const formData = await request.formData()
    const headers = forwardAuthHeaders(request)

    const response = await fetch(`${resolveAgentBaseUrl()}/api/files/upload`, {
      method: 'POST',
      headers,
      body: formData,
      cache: 'no-store',
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Error uploading file:', error)
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to upload file' },
      { status: 503 }
    )
  }
}
