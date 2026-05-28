import { NextRequest, NextResponse } from 'next/server'

import { evaluateWorkflowPlan, normalizeCanvas } from '@/lib/hypothesis-workflow'
import type { WorkflowPlan } from '@/types/hypothesis'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const plan =
    (body as any).plan && typeof (body as any).plan === 'object'
      ? ((body as any).plan as WorkflowPlan)
      : null

  if (!plan) {
    return NextResponse.json(
      { error: 'missing_plan', message: 'plan is required.' },
      { status: 400 },
    )
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

  const context =
    (body as any).context && typeof (body as any).context === 'object'
      ? {
          dataset_id:
            typeof (body as any).context.dataset_id === 'string'
              ? (body as any).context.dataset_id
              : null,
          concept_id:
            typeof (body as any).context.concept_id === 'string'
              ? (body as any).context.concept_id
              : null,
          task_id:
            typeof (body as any).context.task_id === 'string'
              ? (body as any).context.task_id
              : null,
        }
      : undefined

  const canvas = normalizeCanvas(canvasRaw as any, typeof (body as any).term === 'string' ? (body as any).term : undefined)

  return NextResponse.json({
    validation: evaluateWorkflowPlan({
      plan,
      canvas,
      context,
    }),
  })
}
