import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(request: NextRequest) {
  const payload = await request.json().catch(() => null)
  if (!payload || typeof payload !== 'object') {
    return NextResponse.json({ detail: 'Invalid request body' }, { status: 400 })
  }

  const orchestratorBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchestratorBase}/auth/reset-password`

  try {
    const upstream = await fetch(upstreamUrl, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
    })

    const raw = await upstream.text()
    const contentType = upstream.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const body = isJson
      ? (JSON.parse(raw || '{}') as Record<string, unknown>)
      : { detail: raw || `Upstream reset failed (${upstream.status})` }

    return NextResponse.json(body, { status: upstream.status })
  } catch (error) {
    console.error('[api/orchestrator/auth/reset-password] upstream request failed', error)
    return NextResponse.json(
      { detail: 'Password reset service temporarily unavailable' },
      { status: 502 },
    )
  }
}
