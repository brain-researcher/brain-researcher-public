import { NextRequest, NextResponse } from 'next/server'

import {
  exploreLocalHypothesisSession,
  getOrCreateLocalHypothesisSessionPersisted,
  upsertLocalHypothesisSessionFromRemote,
} from '@/lib/server/hypothesis-local-store'
import { proxyHypothesis, shouldFallbackToLocalHypothesis } from '@/lib/server/hypothesis-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const normalized = {
    ...body,
    session_id:
      typeof (body as any).session_id === 'string'
        ? (body as any).session_id
        : typeof (body as any).sessionId === 'string'
          ? (body as any).sessionId
          : undefined,
    open_question_id:
      typeof (body as any).open_question_id === 'string'
        ? (body as any).open_question_id
        : typeof (body as any).openQuestionId === 'string'
          ? (body as any).openQuestionId
          : undefined,
    n_candidates:
      typeof (body as any).n_candidates === 'number'
        ? (body as any).n_candidates
        : typeof (body as any).nCandidates === 'number'
          ? (body as any).nCandidates
          : undefined,
  }

  const upstream = await proxyHypothesis(req, {
    method: 'POST',
    pathname: '/explore',
    body: normalized,
  })

  if (upstream.ok) {
    const payload = await upstream.clone().json().catch(() => null)
    if (payload && typeof payload === 'object') {
      const source = payload as Record<string, unknown>
      await upsertLocalHypothesisSessionFromRemote({
        sessionId:
          (typeof normalized.session_id === 'string' && normalized.session_id) ||
          (typeof source.session_id === 'string' && source.session_id) ||
          (typeof source.sessionId === 'string' && source.sessionId) ||
          undefined,
        session: source.session,
        openQuestions: source.open_questions ?? source.openQuestions,
        candidates: source.candidates ?? source.items,
        messages: source.messages,
        selectedHypothesisId: source.selected_hypothesis_id ?? source.selectedHypothesisId,
        leaderboardUrl: source.leaderboard_url ?? source.leaderboardUrl,
      })
    }
    return upstream
  }

  if (!shouldFallbackToLocalHypothesis(upstream.status)) {
    return upstream
  }

  const sessionId =
    typeof normalized.session_id === 'string' ? normalized.session_id.trim() : ''
  if (!sessionId) {
    return NextResponse.json(
      { error: 'missing_session_id', message: 'session_id is required.' },
      { status: 400 },
    )
  }

  await getOrCreateLocalHypothesisSessionPersisted({ sessionId })

  const fallback = exploreLocalHypothesisSession({
    sessionId,
    openQuestionId:
      typeof normalized.open_question_id === 'string' ? normalized.open_question_id : null,
    nCandidates:
      typeof normalized.n_candidates === 'number' ? normalized.n_candidates : undefined,
  })

  return NextResponse.json(fallback)
}
