import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { threadId: string } }
) {
  const { threadId } = params

  const headers = forwardAuthHeaders(req)

  const res = await fetch(
    `${resolveAgentBaseUrl()}/api/threads/${threadId}/messages`,
    {
      method: 'GET',
      headers,
      cache: 'no-store',
    }
  )

  const text = await res.text()
  return new Response(text, {
    status: res.status,
    headers: {
      'content-type': res.headers.get('content-type') || 'application/json',
    },
  })
}
