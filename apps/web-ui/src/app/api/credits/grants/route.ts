import { NextRequest, NextResponse } from 'next/server'

import { resolveCreditsIdentity } from '@/lib/server/credits'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function grantProxyEnabled(): boolean {
  const raw = process.env.BR_ENABLE_CREDITS_GRANT_PROXY || ''
  const normalized = raw.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

export async function POST(req: NextRequest) {
  if (!grantProxyEnabled()) {
    return NextResponse.json({ error: 'E-NOT-FOUND', detail: 'Not found.' }, { status: 404 })
  }

  const authFailure = await requireAuth(req)
  if (authFailure) return authFailure

  const base = resolveOrchestratorBaseUrl()
  const target = `${base}/api/credits/grants`
  const body = await req.text()
  let payload: Record<string, unknown>
  try {
    const parsed = body ? JSON.parse(body) : {}
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Expected JSON object.')
    }
    payload = parsed as Record<string, unknown>
  } catch {
    return Response.json(
      { error: 'E-BAD-REQUEST', detail: 'Invalid JSON body.' },
      { status: 400 },
    )
  }
  const workspaceId = typeof payload.workspace_id === 'string' ? payload.workspace_id : null
  const userId = typeof payload.user_id === 'string' ? payload.user_id : null
  const identity = await resolveCreditsIdentity(req, { workspaceId, userId })
  payload.workspace_id = identity.workspaceId
  payload.user_id = identity.userId

  return proxyJson(req, target, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
