import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { analysisId: string } },
) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authResponse = await requireAuth(req)
  if (authResponse) return authResponse

  // Orchestrator `/api/jobs/{id}/steps` is the canonical step surface.
  const orchBase = resolveOrchestratorBaseUrl()
  const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/steps`
  return proxyJson(req, targetUrl, { method: 'GET' })
}
