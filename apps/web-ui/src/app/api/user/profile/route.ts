import { NextRequest } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(req: NextRequest) {
  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const base = resolveOrchestratorBaseUrl()
  return proxyJson(req, `${base}/api/user/profile`, { method: 'GET' })
}
