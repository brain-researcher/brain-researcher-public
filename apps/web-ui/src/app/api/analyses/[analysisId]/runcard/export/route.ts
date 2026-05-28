import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { requireAuth } from '@/lib/server/orchestrator-proxy'

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

  const format = req.nextUrl.searchParams.get('format') || 'json'
  const orchBase = resolveOrchestratorBaseUrl()
  const url = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/runcard/export?format=${encodeURIComponent(format)}`
  const headers = forwardAuthHeaders(req)

  try {
    const res = await fetch(url, { cache: 'no-store', headers })
    const body = await res.arrayBuffer()
    const contentType = res.headers.get('content-type') || 'application/octet-stream'
    const filename =
      res.headers
        .get('content-disposition')
        ?.split('filename=')[1]
        ?.replace(/\"/g, '') || `run_card_${analysisId}.${format}`

    return new NextResponse(body, {
      status: res.status,
      headers: {
        'content-type': contentType,
        'content-disposition': `attachment; filename="${filename}"`,
      },
    })
  } catch (err) {
    return NextResponse.json(
      { error: 'orchestrator_unreachable', detail: String(err) },
      { status: 502 },
    )
  }
}
