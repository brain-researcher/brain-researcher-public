import { NextRequest } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
const COMPAT_HEADER_KEY = 'x-br-compat-surface'
const COMPAT_HEADER_VALUE = 'agent-runs'

export async function GET(
  req: NextRequest,
  { params }: { params: { runId: string } }
) {
  const { runId } = params

  const headers = forwardAuthHeaders(req)

  try {
    const encodedRunId = encodeURIComponent(runId)
    const res = await fetch(`${resolveAgentBaseUrl()}/api/runs/${encodedRunId}/stream`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    })

    if (!res.ok) {
      const text = await res.text()
      return new Response(text, {
        status: res.status,
        headers: {
          'content-type': 'application/json',
          [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
        },
      })
    }

    // Compatibility-only SSE facade for legacy run consumers.
    return new Response(res.body, {
      status: res.status,
      headers: {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
        [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
      },
    })
  } catch {
    return new Response(JSON.stringify({ error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to stream run' }), {
      status: 503,
      headers: {
        'content-type': 'application/json',
        [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
      },
    })
  }
}
