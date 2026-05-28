import { NextRequest } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const base = resolveOrchestratorBaseUrl()
  const body = await req.text()
  return proxyJson(req, `${base}/api/user/notifications/mark-read`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body || '{}',
  })
}
