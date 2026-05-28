import { NextRequest, NextResponse } from 'next/server'

import {
  getOrCreateLocalHypothesisSessionPersisted,
  runBatchLocalHypothesisSession,
} from '@/lib/server/hypothesis-local-store'
import { proxyHypothesis, shouldFallbackToLocalHypothesis } from '@/lib/server/hypothesis-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function normalizeIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const sessionId =
    typeof (body as any).session_id === 'string'
      ? (body as any).session_id.trim()
      : typeof (body as any).sessionId === 'string'
        ? (body as any).sessionId.trim()
        : ''

  const hypothesisIds = normalizeIds((body as any).hypothesis_ids)
  const selectedIds = normalizeIds((body as any).selected_ids)
  const mergedIds = Array.from(new Set([...hypothesisIds, ...selectedIds]))

  if (!sessionId) {
    return NextResponse.json(
      { error: 'missing_session_id', message: 'session_id is required.' },
      { status: 400 },
    )
  }

  if (!mergedIds.length) {
    return NextResponse.json(
      {
        error: 'missing_hypothesis_ids',
        message: 'At least one hypothesis id is required.',
      },
      { status: 400 },
    )
  }

  const normalized = {
    ...body,
    session_id: sessionId,
    hypothesis_ids: mergedIds,
  }

  const upstream = await proxyHypothesis(req, {
    method: 'POST',
    pathname: '/run-batch',
    body: normalized,
  })

  if (upstream.ok || !shouldFallbackToLocalHypothesis(upstream.status)) {
    return upstream
  }

  await getOrCreateLocalHypothesisSessionPersisted({ sessionId })

  const fallback = runBatchLocalHypothesisSession({
    sessionId,
    hypothesisIds: mergedIds,
  })

  return NextResponse.json(fallback)
}
