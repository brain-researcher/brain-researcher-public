import { NextRequest } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { threadId: string } }
) {
  const { threadId } = params

  const headers = forwardAuthHeaders(req)

  const res = await fetch(
    `${resolveAgentBaseUrl()}/api/threads/${threadId}/stream`,
    {
      method: 'GET',
      headers,
      cache: 'no-store',
    }
  )

  if (!res.ok) {
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'content-type': 'application/json' },
    })
  }

  // Pipe SSE response directly
  return new Response(res.body, {
    status: res.status,
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    },
  })
}
