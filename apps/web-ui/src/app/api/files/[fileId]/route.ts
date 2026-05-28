import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

export async function GET(
  request: NextRequest,
  { params }: { params: { fileId: string } }
) {
  const { fileId } = params

  try {
    const response = await fetch(`${resolveAgentBaseUrl()}/api/files/${fileId}`, {
      method: 'GET',
      headers: forwardAuthHeaders(request),
    })

    if (!response.ok) {
      const text = await response.text()
      return new Response(text, {
        status: response.status,
        headers: { 'content-type': 'application/json' },
      })
    }

    // Stream file content
    const headers = new Headers()
    headers.set('content-type', response.headers.get('content-type') || 'application/octet-stream')
    if (response.headers.get('content-disposition')) {
      headers.set('content-disposition', response.headers.get('content-disposition')!)
    }

    return new Response(response.body, {
      status: 200,
      headers,
    })
  } catch (error) {
    console.error('Error downloading file:', error)
    return NextResponse.json(
      { error: 'download_failed', detail: 'Failed to download file' },
      { status: 500 }
    )
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { fileId: string } }
) {
  const { fileId } = params

  try {
    const response = await fetch(`${resolveAgentBaseUrl()}/api/files/${fileId}`, {
      method: 'DELETE',
      headers: forwardAuthHeaders(request),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Error deleting file:', error)
    return NextResponse.json(
      { error: 'delete_failed', detail: 'Failed to delete file' },
      { status: 500 }
    )
  }
}
