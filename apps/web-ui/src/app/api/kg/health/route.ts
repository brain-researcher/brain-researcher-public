import { NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'

// Legacy alias: some UI components use `/api/kg/*` as the BR-KG proxy prefix.
// Provide a stable `/api/kg/health` endpoint so connection status checks stay
// same-origin and do not depend on browser reachability to the BR-KG service.
export async function GET() {
  try {
    const healthUrl = `${resolveKgBaseUrl()}/health`

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
  } catch {
    return NextResponse.json({ ok: false, status: 'unavailable', error: 'unreachable' })
  }
}
