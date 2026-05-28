import { NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'
export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}))
    const kgBase = resolveKgBaseUrl()

    const upstream = await fetch(`${kgBase}/kg/searchDatasets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!upstream.ok) {
      return NextResponse.json(
        { items: [], total: 0, error: 'upstream_unavailable' },
        { status: 502 }
      )
    }

    const data = await upstream.json()
    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json(
      { items: [], total: 0, error: 'proxy_error' },
      { status: 500 }
    )
  }
}
