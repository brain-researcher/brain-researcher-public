import { NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  try {
    const baseUrl = resolveKgBaseUrl()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 4000)
    const res = await fetch(`${baseUrl}/health`, { signal: controller.signal, cache: 'no-store' })
    clearTimeout(timeout)

    if (!res.ok) {
      return NextResponse.json({ ok: false, status: res.status }, { status: res.status })
    }

    const data = await res.json().catch(() => null)
    return NextResponse.json({ ok: true, ...(data ?? {}) })
  } catch {
    return NextResponse.json({ ok: false, error: 'unreachable' }, { status: 503 })
  }
}
