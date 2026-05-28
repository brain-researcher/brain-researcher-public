import { NextRequest, NextResponse } from 'next/server'

import { buildSuggestedCanvas, normalizeCanvas } from '@/lib/hypothesis-workflow'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const term =
    typeof (body as any).term === 'string'
      ? (body as any).term.trim()
      : typeof (body as any).canvas?.term === 'string'
        ? (body as any).canvas.term.trim()
        : ''

  if (!term) {
    return NextResponse.json(
      { error: 'missing_term', message: 'term or canvas.term is required.' },
      { status: 400 },
    )
  }

  const answers =
    (body as any).answers && typeof (body as any).answers === 'object'
      ? ((body as any).answers as Record<string, string>)
      : undefined

  const context =
    (body as any).context && typeof (body as any).context === 'object'
      ? ((body as any).context as {
          dataset_id?: string | null
          concept_id?: string | null
          task_id?: string | null
        })
      : undefined

  const suggested = buildSuggestedCanvas({ term, answers, context })

  const normalized = normalizeCanvas(
    {
      ...suggested,
      ...((body as any).canvas && typeof (body as any).canvas === 'object' ? (body as any).canvas : {}),
      term,
    },
    term,
  )

  return NextResponse.json({ canvas: normalized })
}
