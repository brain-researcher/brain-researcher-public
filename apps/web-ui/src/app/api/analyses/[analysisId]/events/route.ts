import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyStream, requireAuth } from '@/lib/server/orchestrator-proxy'

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

  const orchBase = resolveOrchestratorBaseUrl()
  const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/stream`
  const response = await proxyStream(req, targetUrl)

  response.headers.set('cache-control', 'no-cache, no-transform')
  response.headers.set('x-accel-buffering', 'no')
  return response
}
