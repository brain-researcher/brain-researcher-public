import { NextRequest, NextResponse } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const headers = forwardAuthHeaders(req)

  const res = await fetch(`${resolveAgentBaseUrl()}/api/tools`, {
    method: 'GET',
    headers,
    cache: 'no-store',
  })

  const text = await res.text()
  return new Response(text, {
    status: res.status,
    headers: {
      'content-type': res.headers.get('content-type') || 'application/json',
    },
  })
}
