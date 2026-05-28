import { NextRequest, NextResponse } from 'next/server'

import { getLocalHypothesisRunPersisted } from '@/lib/server/hypothesis-local-store'
import { proxyHypothesis, shouldFallbackToLocalHypothesis } from '@/lib/server/hypothesis-proxy'
import { getRunSnapshotPersisted } from '@/lib/server/hypothesis-run-store'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(
  req: NextRequest,
  context: { params: { runId: string } },
) {
  const runId = context.params.runId?.trim()

  if (!runId) {
    return NextResponse.json(
      { error: 'missing_run_id', message: 'runId is required.' },
      { status: 400 },
    )
  }

  if (runId.startsWith('hrun-')) {
    const snapshot = await getRunSnapshotPersisted(runId)
    if (!snapshot) {
      return NextResponse.json(
        { error: 'run_not_found', message: `Run ${runId} not found in hypothesis run store.` },
        { status: 404 },
      )
    }
    return NextResponse.json({ run: snapshot })
  }

  const upstream = await proxyHypothesis(req, {
    method: 'GET',
    pathname: `/run/${encodeURIComponent(runId)}`,
  })

  if (upstream.ok || !shouldFallbackToLocalHypothesis(upstream.status)) {
    return upstream
  }

  const run = await getLocalHypothesisRunPersisted(runId)
  if (!run) {
    return NextResponse.json(
      { error: 'run_not_found', message: `Run ${runId} not found in local fallback store.` },
      { status: 404 },
    )
  }

  return NextResponse.json({ run })
}
