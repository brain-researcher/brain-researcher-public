import { NextRequest, NextResponse } from 'next/server'

import { buildDirectionCandidates, normalizeCanvas } from '@/lib/hypothesis-workflow'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const canvasRaw =
    (body as any).canvas && typeof (body as any).canvas === 'object'
      ? ((body as any).canvas as Record<string, unknown>)
      : null

  if (!canvasRaw) {
    return NextResponse.json(
      { error: 'missing_canvas', message: 'canvas is required.' },
      { status: 400 },
    )
  }

  const canvas = normalizeCanvas(canvasRaw as any, typeof (body as any).term === 'string' ? (body as any).term : undefined)

  const requestedCount =
    typeof (body as any).count === 'number'
      ? (body as any).count
      : typeof (body as any).n_candidates === 'number'
        ? (body as any).n_candidates
        : 5

  const count = Math.max(1, Math.min(11, Math.trunc(requestedCount || 5)))

  return NextResponse.json({
    candidates: buildDirectionCandidates(canvas, count),
  })
}
