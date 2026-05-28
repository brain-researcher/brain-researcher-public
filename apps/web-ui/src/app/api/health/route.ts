import { NextRequest } from 'next/server'
import { resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  try {
    const res = await fetch(`${resolveAgentBaseUrl()}/api/health`, { cache: 'no-store' })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'content-type': res.headers.get('content-type') || 'application/json' },
    })
  } catch (err) {
    return new Response(JSON.stringify({ error: 'agent_unreachable', detail: String(err) }), {
      status: 502,
      headers: { 'content-type': 'application/json' },
    })
  }
}
