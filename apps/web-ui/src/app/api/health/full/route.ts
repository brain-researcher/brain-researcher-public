import { NextRequest } from 'next/server'
import { resolveAgentBaseUrl } from '@/lib/server/downstream'

function resolveAgentBases() {
  const bases: string[] = []
  const addBase = (value?: string) => {
    if (!value) return
    if (!bases.includes(value)) bases.push(value)
  }

  addBase(resolveAgentBaseUrl())

  const host = process.env.AGENT_HOST
  const port = process.env.AGENT_PORT || '8000'
  if (host) {
    addBase(`http://${host}:${port}`)
    const namespace = process.env.POD_NAMESPACE || process.env.K8S_NAMESPACE || 'brain-researcher-core'
    addBase(`http://${host}.${namespace}.svc.cluster.local:${port}`)
  }
  return bases
}

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  const errors: string[] = []
  const bases = resolveAgentBases()

  for (const base of bases) {
    try {
      const res = await fetch(`${base}/api/health/full`, { cache: 'no-store' })
      const text = await res.text()
      return new Response(text, {
        status: res.status,
        headers: { 'content-type': res.headers.get('content-type') || 'application/json' },
      })
    } catch (err) {
      errors.push(`${base}: ${String(err)}`)
    }
  }

  return new Response(
    JSON.stringify({
      error: 'agent_unreachable',
      detail: errors.join(' | ') || 'all_endpoints_failed',
    }),
    {
      status: 502,
      headers: { 'content-type': 'application/json' },
    },
  )
}
