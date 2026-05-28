import { NextRequest, NextResponse } from 'next/server'

import {
  chatLocalHypothesisSession,
  getOrCreateLocalHypothesisSessionPersisted,
} from '@/lib/server/hypothesis-local-store'
import { proxyHypothesis, shouldFallbackToLocalHypothesis } from '@/lib/server/hypothesis-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

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

  const message =
    typeof (body as any).message === 'string'
      ? (body as any).message.trim()
      : typeof (body as any).prompt === 'string'
        ? (body as any).prompt.trim()
        : ''

  if (!sessionId) {
    return NextResponse.json(
      { error: 'missing_session_id', message: 'session_id is required.' },
      { status: 400 },
    )
  }

  if (!message) {
    return NextResponse.json(
      { error: 'missing_message', message: 'message is required.' },
      { status: 400 },
    )
  }

  const normalized = {
    ...body,
    session_id: sessionId,
    message,
    selected_hypothesis_id:
      typeof (body as any).selected_hypothesis_id === 'string'
        ? (body as any).selected_hypothesis_id
        : typeof (body as any).selectedHypothesisId === 'string'
          ? (body as any).selectedHypothesisId
          : undefined,
  }

  const upstream = await proxyHypothesis(req, {
    method: 'POST',
    pathname: '/chat',
    body: normalized,
  })

  if (upstream.ok || !shouldFallbackToLocalHypothesis(upstream.status)) {
    return upstream
  }

  await getOrCreateLocalHypothesisSessionPersisted({ sessionId })

  const fallback = chatLocalHypothesisSession({
    sessionId,
    message,
    selectedHypothesisId:
      typeof normalized.selected_hypothesis_id === 'string'
        ? normalized.selected_hypothesis_id
        : null,
  })

  return NextResponse.json(fallback)
}
