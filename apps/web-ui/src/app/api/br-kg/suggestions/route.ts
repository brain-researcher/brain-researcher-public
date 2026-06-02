import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
// isRequestAuthenticated removed: suggestions are now public (Phase C)

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

type SuggestionsListResponse = {
  items: unknown[]
  count: number
  unavailable?: boolean
}

function normalizeSuggestionsPayload(payload: unknown): SuggestionsListResponse {
  if (!payload) {
    return { items: [], count: 0 }
  }

  if (Array.isArray(payload)) {
    return { items: payload, count: payload.length }
  }

  if (typeof payload !== 'object' || Array.isArray(payload)) {
    return { items: [], count: 0 }
  }

  const record = payload as Record<string, unknown>
  const items = Array.isArray(record.items)
    ? record.items
    : Array.isArray(record.suggestions)
      ? (record.suggestions as unknown[])
      : []
  const count = typeof record.count === 'number' ? record.count : items.length

  return { items, count }
}

export async function GET(req: NextRequest) {
  // Suggestions are public: unauthenticated users get suggestions too
  // (prevents /kg page from showing "unavailable" when not logged in).
  // Auth headers are forwarded when present so the upstream can personalise.
  const headers = forwardAuthHeaders(req)

  let upstream: Response
  try {
    upstream = await fetch(`${resolveAgentBaseUrl()}/api/br-kg/suggestions`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json(
      { items: [], count: 0, unavailable: true } satisfies SuggestionsListResponse,
      { status: 200 },
    )
  }

  if (upstream.status === 404 || upstream.status === 501) {
    return NextResponse.json(
      { items: [], count: 0, unavailable: true } satisfies SuggestionsListResponse,
      { status: 200 },
    )
  }

  const raw = await upstream.text().catch(() => '')
  if (!upstream.ok) {
    console.warn('BR-KG suggestions unavailable', upstream.status, raw.slice(0, 200))
    return NextResponse.json(
      { items: [], count: 0, unavailable: true } satisfies SuggestionsListResponse,
      { status: 200 },
    )
  }

  let payload: unknown = null
  try {
    payload = raw ? JSON.parse(raw) : null
  } catch {
    payload = null
  }

  return NextResponse.json(normalizeSuggestionsPayload(payload))
}
