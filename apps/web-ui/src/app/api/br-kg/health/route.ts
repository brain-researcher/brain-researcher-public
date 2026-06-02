import { NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const baseUrl = resolveKgBaseUrl()
    const healthUrl = `${baseUrl}/health`

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 4000)
    const res = await fetch(healthUrl, { signal: controller.signal, cache: 'no-store' })
    clearTimeout(timeout)

    if (!res.ok) {
      return NextResponse.json({
        ok: false,
        status: 'unavailable',
        upstream_status: res.status,
      })
    }

    const data = await res.json().catch(() => null)
    return NextResponse.json({ ok: true, ...(data ?? {}) })
  } catch (error) {
    return NextResponse.json({ ok: false, status: 'unavailable', error: 'unreachable' })
  }
}
