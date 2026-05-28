import { NextRequest, NextResponse } from 'next/server'

import { resolveCreditsIdentity } from '@/lib/server/credits'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function monthlyTopUpProxyEnabled(): boolean {
  const raw = process.env.BR_ENABLE_API_USD_MONTHLY_TOP_UP_PROXY || ''
  const normalized = raw.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

export async function POST(req: NextRequest) {
  if (!monthlyTopUpProxyEnabled()) {
    return NextResponse.json({ error: 'E-NOT-FOUND', detail: 'Not found.' }, { status: 404 })
  }

  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const identity = await resolveCreditsIdentity(req)
  const base = resolveOrchestratorBaseUrl()
  const target = `${base}/api/credits/api-usd/monthly-top-up`

  return proxyJson(req, target, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      workspace_id: identity.workspaceId,
      user_id: identity.userId,
    }),
  })
}
