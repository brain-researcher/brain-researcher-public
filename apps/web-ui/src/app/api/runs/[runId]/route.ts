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
    // Compatibility-only detail facade for legacy run consumers.
    const res = await fetch(
      `${resolveAgentBaseUrl()}/api/runs/${encodedRunId}`,
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
        [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
      },
    })
  } catch (error) {
    return new Response(JSON.stringify({ error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to fetch run' }), {
      status: 503,
      headers: {
        'content-type': 'application/json',
        [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
      },
    })
  }
}
