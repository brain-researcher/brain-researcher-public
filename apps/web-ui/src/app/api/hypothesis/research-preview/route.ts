import { NextRequest, NextResponse } from 'next/server'

import {
  buildResearchPreview,
  buildDirectionCandidates,
  normalizeCanvas,
} from '@/lib/hypothesis-workflow'
import type { DirectionCandidate } from '@/types/hypothesis'

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

  let candidate =
    (body as any).candidate && typeof (body as any).candidate === 'object'
      ? ((body as any).candidate as DirectionCandidate)
      : null

  if (!candidate) {
    const defaults = buildDirectionCandidates(canvas, 1)
    candidate = defaults[0] || null
  }

  if (!candidate) {
    return NextResponse.json(
      { error: 'missing_candidate', message: 'candidate is required.' },
      { status: 400 },
    )
  }

  return NextResponse.json({
    preview: buildResearchPreview(canvas, candidate),
  })
}
