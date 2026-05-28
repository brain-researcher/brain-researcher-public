import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { demo_id: string } },
) {
  const demoId = typeof params.demo_id === 'string' ? params.demo_id.trim() : ''
  if (!demoId) {
    return NextResponse.json({ detail: 'demo_id is required.' }, { status: 400 })
  }

  const orchBase = resolveOrchestratorBaseUrl()
  const targetUrl = `${orchBase}/api/demo/real-results/${encodeURIComponent(demoId)}${req.nextUrl.search}`
  const upstream = await fetch(targetUrl, {
    method: 'GET',
    cache: 'no-store',
  })

  const body = await upstream.text().catch(() => '')
  return new NextResponse(body || upstream.statusText, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/json',
      'cache-control': 'no-store',
    },
  })
}
