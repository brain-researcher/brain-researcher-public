import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

export async function POST(req: NextRequest, { params }: { params: { analysisId: string } }) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ detail: 'Authentication required.' }, { status: 401 })
  }

  let body: any = {}
  try {
    body = (await req.json().catch(() => ({}))) as any
  } catch {
    body = {}
  }

  const expiresInHours = clamp(Number(body?.expires_in_hours ?? body?.expiresInHours ?? 24) || 24, 1, 168)
  const shareLevelRaw = String(body?.share_level ?? body?.shareLevel ?? 'summary')
    .trim()
    .toLowerCase()
  const shareLevel = shareLevelRaw === 'full' ? 'full' : 'summary'

  const headers = forwardAuthHeaders(req)
  const orchBase = resolveOrchestratorBaseUrl()

  try {
    const upstream = await fetch(`${orchBase}/api/analyses/${encodeURIComponent(analysisId)}/share`, {
      method: 'POST',
      headers: { ...Object.fromEntries(headers.entries()), 'content-type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({
        expires_in_hours: expiresInHours,
        share_level: shareLevel,
      }),
    })

    if (upstream.ok) {
      const issued = (await upstream.json().catch(() => null)) as any
      const shareToken = String(issued?.share_token ?? issued?.shareToken ?? '').trim()
      const expiresAt = issued?.expires_at ?? issued?.expiresAt

      if (!shareToken) {
        return NextResponse.json({ detail: 'Share token was not returned.' }, { status: 502 })
      }

      const origin = req.nextUrl.origin
      const sharePath = `/share/${encodeURIComponent(shareToken)}`

      return NextResponse.json(
        {
          analysis_id: analysisId,
          share_token: shareToken,
          share_level: issued?.share_level ?? shareLevel,
          revocable: true,
          share_url: `${origin}${sharePath}`,
          share_path: sharePath,
          expires_at: expiresAt,
        },
        { status: 201 },
      )
    }

    const text = await upstream.text().catch(() => '')
    let json: any = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      json = null
    }
    return NextResponse.json(json ?? { detail: text || upstream.statusText }, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'Upstream unavailable.' }, { status: 502 })
  }
}
