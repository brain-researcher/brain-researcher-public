import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { proxyJson, requireAuth } from '@/lib/server/orchestrator-proxy'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(
  req: NextRequest,
  { params }: { params: { analysisId: string; artifactId: string } },
) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  const artifactId = typeof params.artifactId === 'string' ? params.artifactId.trim() : ''
  if (!analysisId || !artifactId) {
    return NextResponse.json({ detail: 'analysisId and artifactId are required.' }, { status: 400 })
  }

  const authResponse = await requireAuth(req)
  if (authResponse) return authResponse

  const body = await req.text()
  const orchBase = resolveOrchestratorBaseUrl()
  const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/artifacts/${encodeURIComponent(artifactId)}/annotate`
  return proxyJson(req, targetUrl, {
    method: 'POST',
    headers: { 'content-type': req.headers.get('content-type') || 'application/json' },
    body,
  })
}
