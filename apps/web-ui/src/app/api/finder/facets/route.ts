import { NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}))
    const upstream = await fetch(`${resolveKgBaseUrl()}/kg/facets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    })

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => '')
      return NextResponse.json(
        { facets: {}, error: text || 'upstream_unavailable' },
        { status: 502 },
      )
    }

    const data = await upstream.json().catch(() => ({}))
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ facets: {}, error: 'proxy_error' }, { status: 500 })
  }
}
