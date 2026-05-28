import { NextRequest } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(req: NextRequest) {
  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const base = resolveOrchestratorBaseUrl()
  const target = new URL(`${base}/dashboard/metrics`)

  req.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value)
  })

  return proxyJson(req, target.toString(), { method: 'GET' })
}
