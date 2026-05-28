import { NextRequest, NextResponse } from 'next/server'

import { patchWorkflowPlan } from '@/lib/hypothesis-workflow'
import type { ValidationReport, WorkflowPlan } from '@/types/hypothesis'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null)

  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'invalid_body', message: 'Expected JSON body.' }, { status: 400 })
  }

  const patchCount =
    typeof (body as any).patch_count === 'number'
      ? (body as any).patch_count
      : typeof (body as any).patchCount === 'number'
        ? (body as any).patchCount
        : 0

  if (patchCount >= 1) {
    return NextResponse.json(
      {
        error: 'patch_limit_exceeded',
        message: 'Automatic patch is limited to 1 retry.',
      },
      { status: 409 },
    )
  }

  const plan =
    (body as any).plan && typeof (body as any).plan === 'object'
      ? ((body as any).plan as WorkflowPlan)
      : null

  const validation =
    (body as any).validation && typeof (body as any).validation === 'object'
      ? ((body as any).validation as ValidationReport)
      : null

  if (!plan || !validation) {
    return NextResponse.json(
      {
        error: 'missing_inputs',
        message: 'plan and validation are required.',
      },
      { status: 400 },
    )
  }

  try {
    const patch = patchWorkflowPlan({ plan, validation })
    return NextResponse.json({ patch })
  } catch (error) {
    return NextResponse.json(
      {
        error: 'patch_not_applicable',
        message: error instanceof Error ? error.message : 'Automatic patch is not applicable.',
      },
      { status: 422 },
    )
  }
}
