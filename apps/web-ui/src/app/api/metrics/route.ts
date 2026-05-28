import { NextRequest } from 'next/server'
import { resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  try {
    const res = await fetch(`${resolveAgentBaseUrl()}/metrics`, { cache: 'no-store' })
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'content-type': 'text/plain; version=0.0.4' },
    })
  } catch (err) {
    // Return minimal metrics indicating the proxy itself is up but agent is unreachable
    const fallback = [
      '# HELP webui_up Web UI service availability',
      '# TYPE webui_up gauge',
      'webui_up 1',
      '# HELP webui_agent_reachable Agent service reachability',
      '# TYPE webui_agent_reachable gauge',
      'webui_agent_reachable 0',
    ].join('\n')
    return new Response(fallback + '\n', {
      status: 200,
      headers: { 'content-type': 'text/plain; version=0.0.4' },
    })
  }
}
