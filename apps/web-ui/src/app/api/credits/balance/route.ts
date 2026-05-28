import { NextRequest } from 'next/server'

import { resolveCreditsIdentity } from '@/lib/server/credits'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(req: NextRequest) {
  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const base = resolveOrchestratorBaseUrl()
  const target = new URL(`${base}/api/credits/balance`)
  const workspaceId = req.nextUrl.searchParams.get('workspace_id')
  const userId = req.nextUrl.searchParams.get('user_id')
  const identity = await resolveCreditsIdentity(req, { workspaceId, userId })
  target.searchParams.set('workspace_id', identity.workspaceId)
  target.searchParams.set('user_id', identity.userId)

  return proxyJson(req, target.toString(), { method: 'GET' })
}
