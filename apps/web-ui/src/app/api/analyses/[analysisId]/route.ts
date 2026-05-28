import { NextRequest, NextResponse } from 'next/server'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import { loadDemoRunBundleSummary } from '@/lib/server/demo-bundles'
import { loadDemoIndex } from '@/lib/server/demo-index'
import { forwardAuthHeaders } from '@/lib/server/downstream'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest, { params }: { params: { analysisId: string } }) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authed = await isRequestAuthenticated(req)
  const demos = loadDemoIndex().demos || []
  const demoEntry = demos.find((demo) => demo.analysis_id === analysisId) || null
  const headers = authed ? forwardAuthHeaders(req) : new Headers()
  if (!authed) {
    if (!demoEntry) {
      return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
    }

    const bearer = issueInternalJwt({
      subject: 'demo-viewer',
      email: 'demo-viewer@local',
      name: 'demo-viewer',
      role: 'demo',
      provider: 'demo-viewer',
      ttlSeconds: 10 * 60,
    })
    if (!bearer) {
      return NextResponse.json(
        { error: 'E-UNAUTHORIZED', detail: 'Demo auth is not configured.' },
        { status: 500 },
      )
    }
    headers.set('authorization', `Bearer ${bearer}`)
  }

  const curatedOnly = demoEntry?.demo_type === 'manuscript_case_report'
  const curatedBundleResult = {
    ok: false as const,
    status: 404,
    body: { detail: 'Curated demo bundle only.' },
  }
  const result = curatedOnly ? curatedBundleResult : await buildAnalysisDetail({ analysisId, headers })

  if (!result.ok) {
    if (demoEntry && 'status' in result && result.status === 404) {
      const bundle = loadDemoRunBundleSummary(demoEntry.slug)
      const now = Math.floor(Date.now() / 1000)
      const warningDetail =
        typeof result.body?.detail === 'string' ? result.body.detail : 'Run not found.'
      const bundleWarning = bundle.available
        ? `Showing curated demo bundle (${bundle.artifact_count} evidence files).`
        : 'Demo bundle not available for this case.'
      return NextResponse.json({
        analysis_id: analysisId,
        status: 'completed',
        created_at: now,
        started_at: now,
        finished_at: now,
        title: demoEntry.title || analysisId,
        has_results: bundle.available ? bundle.artifact_count > 0 : false,
        dataset: {
          dataset_id: 'demo_bundle',
          name: 'Demo bundle',
          source: 'demo',
        },
        template: {
          template_id: demoEntry.canonical_name || demoEntry.slug,
          analysis_id: analysisId,
          pipeline_id: demoEntry.slug,
          name: demoEntry.title || demoEntry.slug,
        },
        parameters: {
          demo_type: demoEntry.demo_type || 'research_demo',
          manuscript_figure: demoEntry.manuscript_figure || null,
          evidence_mode: demoEntry.evidence_mode || 'hybrid',
          log_mode: demoEntry.log_mode || 'redacted_full_trace',
          stage_tags: demoEntry.stage_tags || [],
          source_run_ids: demoEntry.source_run_ids || [],
          is_template: Boolean(demoEntry.is_template),
        },
        warnings: curatedOnly ? [bundleWarning] : [`Live run unavailable (${warningDetail})`, bundleWarning],
      })
    }

    const payload = 'body' in result ? result.body : { detail: 'Unknown error' }
    const status = 'status' in result ? result.status : 500
    return NextResponse.json(payload, { status })
  }

  return NextResponse.json(result.detail)
}
