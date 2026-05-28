import { NextRequest, NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'

export async function GET(
  _req: NextRequest,
  { params }: { params: { datasetId: string } },
) {
  try {
    const datasetId = params.datasetId
    const upstream = await fetch(
      `${resolveKgBaseUrl()}/kg/explain/${encodeURIComponent(datasetId)}`,
      { cache: 'no-store' },
    )

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => '')
      return NextResponse.json(
        { error: text || 'upstream_unavailable' },
        { status: 502 },
      )
    }

    const data = await upstream.json().catch(() => ({}))
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'proxy_error' }, { status: 500 })
  }
}
