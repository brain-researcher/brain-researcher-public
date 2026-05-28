import { NextRequest, NextResponse } from 'next/server'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import {
  bundleArtifacts,
  loadDemoRunBundle,
  resolveBundleArtifactFile,
} from '@/lib/server/demo-bundles'
import {
  artifactPreview,
  buildPresentation,
  buildPromptPack,
  buildPromptSourceFiles,
  buildReferenceOutput,
  buildReplaySteps,
  buildReproduceSpec,
  buildTransparentEvidenceNotes,
} from '@/lib/server/demo-replay'
import { resolveDemoEntry } from '@/lib/server/demo-index'
import { forwardAuthHeaders } from '@/lib/server/downstream'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { ensureDemoRunExists } from '@/lib/server/demo-seed'
import type { AnalysisDetail } from '@/types/analysis'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function buildFallbackDetail(args: {
  analysisId: string
  demoTitle: string
  slug: string
  canonicalName?: string
  bundleArtifactCount: number
  warningDetail: string
  curatedOnly?: boolean
}): AnalysisDetail {
  const now = Math.floor(Date.now() / 1000)
  const bundleWarning =
    args.bundleArtifactCount > 0
      ? `Showing curated demo bundle (${args.bundleArtifactCount} evidence files).`
      : 'Demo bundle not available for this case.'
  return {
    analysis_id: args.analysisId,
    status: 'completed',
    created_at: now,
    started_at: now,
    finished_at: now,
    title: args.demoTitle || args.analysisId,
    has_results: args.bundleArtifactCount > 0,
    dataset: {
      dataset_id: 'demo_bundle',
      name: 'Demo bundle',
      source: 'demo',
    },
    template: {
      template_id: args.canonicalName || args.slug,
      analysis_id: args.analysisId,
      pipeline_id: args.slug,
      name: args.demoTitle || args.slug,
    },
    parameters: {
      demo_mode: 'bundle_fallback',
      is_replay: true,
    },
    warnings: args.curatedOnly
      ? [bundleWarning]
      : [`Live run unavailable (${args.warningDetail})`, bundleWarning],
  } as AnalysisDetail
}

export async function GET(
  req: NextRequest,
  { params }: { params: { demoId: string } },
) {
  const rawDemoId = typeof params.demoId === 'string' ? params.demoId.trim() : ''
  if (!rawDemoId) {
    return NextResponse.json({ detail: 'demoId is required.' }, { status: 400 })
  }

  const demoEntry = resolveDemoEntry(rawDemoId)
  if (!demoEntry) {
    return NextResponse.json({ detail: `Unknown demo "${rawDemoId}".` }, { status: 404 })
  }

  const authed = await isRequestAuthenticated(req)
  const headers = authed ? forwardAuthHeaders(req) : new Headers()
  if (!authed) {
    const bearer = issueInternalJwt({
      subject: 'demo-replay-viewer',
      email: 'demo-replay-viewer@local',
      name: 'demo-replay-viewer',
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

  const analysisId = demoEntry.analysis_id
  const curatedOnly = demoEntry.demo_type === 'manuscript_case_report'
  let result: Awaited<ReturnType<typeof buildAnalysisDetail>> | null = null
  if (!curatedOnly) {
    result = await buildAnalysisDetail({ analysisId, headers })
    if (!result.ok && 'status' in result && result.status === 404) {
      const seeded = await ensureDemoRunExists(demoEntry)
      if (seeded) {
        result = await buildAnalysisDetail({ analysisId, headers })
      }
    }
  }

  if (!result) {
    result = {
      ok: false,
      status: 404,
      body: { detail: 'Curated demo bundle only.' },
    } as Awaited<ReturnType<typeof buildAnalysisDetail>>
  }

  const bundle = loadDemoRunBundle(demoEntry.slug)
  const artifacts = bundleArtifacts(bundle)
  const artifactCount =
    typeof bundle?.artifact_count === 'number' ? bundle.artifact_count : artifacts.length

  const analysis: AnalysisDetail =
    result.ok
      ? result.detail
      : buildFallbackDetail({
          analysisId,
          demoTitle: demoEntry.title,
          slug: demoEntry.slug,
          canonicalName: demoEntry.canonical_name,
          bundleArtifactCount: artifactCount,
          curatedOnly,
          warningDetail:
            'body' in result && typeof result.body?.detail === 'string'
              ? result.body.detail
              : 'Run not found.',
        })

  const promptPack = buildPromptPack({
    demo: demoEntry,
    analysis,
    bundle,
  })
  const referenceOutput = buildReferenceOutput({
    analysis,
    demo: demoEntry,
    bundle,
  })
  const replaySteps = buildReplaySteps({
    analysis,
    demo: demoEntry,
    promptPack,
    bundle,
    referenceSummary: referenceOutput.summary,
  })
  const replaySource: 'runcard' | 'bundle_steps' | 'synthetic' =
    bundle?.replay?.source ||
    (replaySteps.length > 0 && replaySteps[0].step_id.startsWith('step_')
      ? 'runcard'
      : 'synthetic')
  const presentation = buildPresentation({
    demo: demoEntry,
    replaySteps,
    bundle,
  })
  const notes = buildTransparentEvidenceNotes({
    demo: demoEntry,
    bundle,
    replaySource,
  })
  const reproduce = buildReproduceSpec({
    demo: demoEntry,
    promptPack,
    bundle,
  })

  const bundleItems = artifacts.map((artifactPath) => {
    const cleanPath = artifactPath.path.replace(/\\/g, '/')
    const fileName = cleanPath.split('/').filter(Boolean).pop() || cleanPath
    const artifactRequestPath = artifactPath.id || cleanPath
    const preview = artifactPreview({
      slug: demoEntry.slug,
      artifactPath: artifactRequestPath,
      resolver: resolveBundleArtifactFile,
    })
    return {
      id: artifactPath.id,
      name: fileName,
      path: cleanPath,
      title: artifactPath.title || null,
      stage: artifactPath.stage || null,
      roles: artifactPath.roles || [],
      download_url: `/api/demo/bundles/${encodeURIComponent(demoEntry.slug)}/artifact?path=${encodeURIComponent(artifactRequestPath)}`,
      mime_type:
        preview?.mime_type || artifactPath.mime_type || 'application/octet-stream',
      preview: preview?.preview || '',
    }
  })

  return NextResponse.json({
    demo: {
      ...demoEntry,
      prompt_sources: buildPromptSourceFiles({
        demo: demoEntry,
        bundle,
      }),
    },
    analysis: {
      analysis_id: analysis.analysis_id,
      status: analysis.status,
      title: analysis.title,
      created_at: analysis.created_at,
      started_at: analysis.started_at,
      finished_at: analysis.finished_at,
      dataset: analysis.dataset || null,
      template: analysis.template || null,
      warnings: analysis.warnings || [],
    },
    prompt: promptPack,
    presentation,
    replay: {
      source: replaySource,
      steps: replaySteps,
    },
    reference_output: referenceOutput,
    reproduce,
    bundle: {
      available: Boolean(bundle),
      generated_at: bundle?.generated_at || null,
      artifact_count: artifactCount,
      source_run_ids: bundle?.source_run_ids || demoEntry.source_run_ids || [],
      items: bundleItems,
    },
    notes,
  })
}
