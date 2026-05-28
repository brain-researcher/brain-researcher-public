import { NextRequest, NextResponse } from "next/server"

import { buildOrchestratorRunPayload } from "@/lib/server/orchestrator-run-payload"
import { ANALYSIS_TYPES, AnalysisType, PipelineOption } from "@/config/analysis-presets"
import {
  inferBoldImgPathFromBidsDir,
  inferSessionIdFromPath,
  resolveDefaultBidsRunHints,
  type DatasetBidsHintSource,
} from "@/lib/server/bids-defaults"
import { getDataset } from "@/lib/server/dataset-catalog"
import {
  forwardAuthHeaders,
  resolveAgentBaseUrl,
  resolveOrchestratorBaseUrl,
} from "@/lib/server/downstream"
import { DatasetDetailResponse } from "@/types/datasets-search"

type RunFromDatasetRequest = {
  dataset_id?: string
  analysis_id?: string
  pipeline_id?: string
  params?: Record<string, unknown>
}

type OrchestratorRunResponse = {
  analysis_id?: string
  run_id?: string
  job_id?: string
  status?: string
  error?: string
  detail?: string
  [key: string]: unknown
}

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

// Compatibility route name only. Dataset-triggered run creation now normalizes
// to the Orchestrator `/run` path via the shared analyses payload builder.

const CONNECTIVITY_KIND_MAP: Record<string, string> = {
  correlation: "correlation",
  partialcorrelation: "partial correlation",
  tangent: "tangent",
  covariance: "covariance",
  precision: "precision",
}

function normalizeId(value: unknown): string {
  if (typeof value !== "string") return ""
  return value.trim()
}

function datasetSupportsPipeline(dataset: DatasetDetailResponse, pipeline: PipelineOption) {
  if (!pipeline.modalities.length) {
    return true
  }
  const datasetModalities = new Set((dataset.modalities ?? []).map((modality) => modality.toLowerCase()))
  return pipeline.modalities.some((required) => datasetModalities.has(required.toLowerCase()))
}

function normalizePipelineToolId(analysisId: string, pipelineId: string, toolId: string): string {
  if (analysisId === "connectivity" && pipelineId === "nilearn_connectivity") {
    return "workflow_rest_connectome_e2e"
  }
  if (toolId === "connectivity_matrix") {
    return "workflow_rest_connectome_e2e"
  }
  return toolId
}

function normalizeConnectivityKind(value: unknown): string | null {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const normalizedKey = trimmed.toLowerCase().replace(/[\s_-]+/g, "")
  return CONNECTIVITY_KIND_MAP[normalizedKey] ?? trimmed
}

function sanitizePathToken(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '')
}

function validateConnectivityArgs(args: Record<string, unknown>): string | null {
  const img = normalizeId(args.img ?? args.bold_img)
  const bidsDir = normalizeId(args.bids_dir)

  if (!img && !bidsDir) {
    return "Connectivity run requires a BOLD image path. Provide params.img or set params.bids_dir to a valid BIDS directory."
  }

  return null
}

function validateGlmArgs(args: Record<string, unknown>): string | null {
  const img = normalizeId(args.img ?? args.bold_img)
  const bidsDir = normalizeId(args.bids_dir)

  if (!img && !bidsDir) {
    return "Task GLM run requires a BOLD image path. Provide params.img or set params.bids_dir to a valid BIDS directory."
  }

  return null
}

function isConnectivityStep(toolId: string, analysisId: string, pipelineId: string): boolean {
  return (
    toolId === "workflow_rest_connectome_e2e" ||
    (analysisId === "connectivity" && pipelineId === "nilearn_connectivity")
  )
}

function isGlmStep(toolId: string, analysisId: string, pipelineId: string): boolean {
  return (
    toolId === "glm_first_level" ||
    (analysisId === "glm" && pipelineId === "nilearn_glm")
  )
}

function resolveDatasetPathHints(dataset: DatasetDetailResponse): {
  datasetToken: string
  defaultBidsDir: string
  defaultOutputDirRoot: string
} {
  const openNeuroRoot = process.env.OPENNEURO_ROOT || '/app/data/openneuro'
  const sharedRoot = process.env.BR_SHARED_DATA_ROOT || '/app/data/shared'
  const openNeuroMatch = String(dataset.id || '').match(/^ds:openneuro:(.+)$/i)
  const primaryUrl = typeof dataset.primary_url === 'string' ? dataset.primary_url.trim() : ''

  const datasetToken = sanitizePathToken(openNeuroMatch?.[1] || dataset.id || 'dataset')
  const defaultBidsDir =
    openNeuroMatch?.[1]
      ? `${openNeuroRoot}/${openNeuroMatch[1]}`
      : primaryUrl.startsWith('/')
        ? primaryUrl
        : `${openNeuroRoot}/${datasetToken}`

  return {
    datasetToken,
    defaultBidsDir,
    defaultOutputDirRoot: `${sharedRoot}/runs`,
  }
}

function applyExecutionDefaults(
  input: Record<string, unknown>,
  context: {
    dataset: DatasetDetailResponse
    analysisId: string
    pipelineId: string
    toolId: string
  },
) {
  const merged: Record<string, unknown> = { ...input }
  const { dataset, analysisId, pipelineId } = context
  const toolId = normalizePipelineToolId(analysisId, pipelineId, context.toolId)
  const { datasetToken, defaultBidsDir, defaultOutputDirRoot } = resolveDatasetPathHints(dataset)
  const pipelineToken = sanitizePathToken(pipelineId || toolId || 'pipeline')
  const defaultOutputDir = `${defaultOutputDirRoot}/${datasetToken}/${pipelineToken}`

  const needsBidsDefaults =
    ['preprocess', 'preprocessing'].includes(analysisId) ||
    ['fmriprep', 'qsiprep', 'mriqc', 'run_bids_app', 'workflow_preprocessing_qc'].includes(toolId)

  if (needsBidsDefaults) {
    if (typeof merged.bids_dir !== 'string' || !merged.bids_dir.trim()) {
      merged.bids_dir = defaultBidsDir
    }
    if (typeof merged.output_dir !== 'string' || !merged.output_dir.trim()) {
      merged.output_dir = defaultOutputDir
    }
  }

  if (toolId === 'run_bids_app' && (typeof merged.app !== 'string' || !String(merged.app).trim())) {
    if (pipelineId === 'fmriprep') merged.app = 'fmriprep'
    else if (pipelineId === 'qsiprep') merged.app = 'qsiprep'
    else if (pipelineId === 'mriqc') merged.app = 'mriqc'
  }

  const isConnectivityWorkflow =
    pipelineId === 'nilearn_connectivity' ||
    toolId === 'workflow_rest_connectome_e2e' ||
    toolId === 'connectivity_matrix'

  if (isConnectivityWorkflow) {
    if (typeof merged.bids_dir !== 'string' || !merged.bids_dir.trim()) {
      merged.bids_dir = defaultBidsDir
    }
    if (typeof merged.output_dir !== 'string' || !merged.output_dir.trim()) {
      merged.output_dir = `outputs/${pipelineToken || 'connectivity'}`
    }

    const legacyAtlas =
      typeof merged.atlas === 'string' && merged.atlas.trim() ? merged.atlas.trim() : null
    if (
      (
        typeof merged.atlas_name !== 'string' ||
        !merged.atlas_name.trim() ||
        merged.atlas_name.trim() === 'Schaefer2018_200'
      ) &&
      legacyAtlas
    ) {
      merged.atlas_name = legacyAtlas
    }
    if (typeof merged.atlas_name !== 'string' || !merged.atlas_name.trim()) {
      merged.atlas_name = 'Schaefer2018_200'
    }

    const legacyConnectivityKind =
      normalizeConnectivityKind(merged.connectivity_metric) ||
      normalizeConnectivityKind(merged.connectivity_kind)
    if (
      (
        typeof merged.connectivity_kind !== 'string' ||
        !merged.connectivity_kind.trim() ||
        merged.connectivity_kind.trim() === 'correlation'
      ) &&
      legacyConnectivityKind
    ) {
      merged.connectivity_kind = legacyConnectivityKind
    }
    if (
      typeof merged.connectivity_kind !== 'string' ||
      !merged.connectivity_kind.trim()
    ) {
      merged.connectivity_kind = 'correlation'
    } else {
      merged.connectivity_kind =
        normalizeConnectivityKind(merged.connectivity_kind) || merged.connectivity_kind
    }

    const explicitImg =
      typeof merged.img === 'string' && merged.img.trim()
        ? merged.img.trim()
        : typeof merged.bold_img === 'string' && merged.bold_img.trim()
          ? merged.bold_img.trim()
          : ''

    if (explicitImg) {
      merged.img = explicitImg
    } else {
      const bidsDir =
        typeof merged.bids_dir === 'string' && merged.bids_dir.trim()
          ? merged.bids_dir.trim()
          : defaultBidsDir
      const hints = resolveDefaultBidsRunHints(dataset, merged)
      if (!normalizeId(merged.subject_id ?? merged.subject)) merged.subject_id = hints.subject_id
      if (hints.session_id && !normalizeId(merged.session_id ?? merged.session)) {
        merged.session_id = hints.session_id
      }
      if (!normalizeId(merged.task_id ?? merged.task ?? merged.task_name)) {
        merged.task_id = hints.task_id
      }
      merged.img = inferBoldImgPathFromBidsDir(bidsDir, hints)
    }
  }

  const isGlmWorkflow = pipelineId === 'nilearn_glm' || toolId === 'glm_first_level'
  if (isGlmWorkflow) {
    if (typeof merged.bids_dir !== 'string' || !merged.bids_dir.trim()) {
      merged.bids_dir = defaultBidsDir
    }
    if (typeof merged.output_dir !== 'string' || !merged.output_dir.trim()) {
      merged.output_dir = `outputs/${pipelineToken || 'nilearn_glm'}`
    }
    if (
      (typeof merged.smoothing_fwhm !== 'number' ||
        !Number.isFinite(merged.smoothing_fwhm)) &&
      (typeof merged.smoothing === 'number' ||
        (typeof merged.smoothing === 'string' && merged.smoothing.trim()))
    ) {
      merged.smoothing_fwhm = merged.smoothing
    }

    const explicitImg =
      typeof merged.img === 'string' && merged.img.trim()
        ? merged.img.trim()
        : typeof merged.bold_img === 'string' && merged.bold_img.trim()
          ? merged.bold_img.trim()
          : ''

    if (explicitImg) {
      merged.img = explicitImg
    } else {
      const bidsDir =
        typeof merged.bids_dir === 'string' && merged.bids_dir.trim()
          ? merged.bids_dir.trim()
          : defaultBidsDir
      const hints = resolveDefaultBidsRunHints(dataset, merged)
      if (!normalizeId(merged.subject_id ?? merged.subject)) merged.subject_id = hints.subject_id
      if (hints.session_id && !normalizeId(merged.session_id ?? merged.session)) {
        merged.session_id = hints.session_id
      }
      if (!normalizeId(merged.task_id ?? merged.task ?? merged.task_name)) {
        merged.task_id = hints.task_id
      }
      merged.img = inferBoldImgPathFromBidsDir(bidsDir, hints)
    }
  }

  return merged
}

type AgentToolRunResult = {
  status: "success" | "error"
  data?: Record<string, unknown>
  error?: string
}

async function runAgentTool(
  request: NextRequest,
  tool: string,
  args: Record<string, unknown>,
): Promise<AgentToolRunResult> {
  const headers = forwardAuthHeaders(request)
  headers.set("content-type", "application/json")

  try {
    const upstream = await fetch(`${resolveAgentBaseUrl()}/api/tools/run`, {
      method: "POST",
      headers,
      body: JSON.stringify({ tool, args, arguments: args }),
      cache: "no-store",
    })

    const raw = await upstream.text()
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    const root = safeObject(parsed) ?? {}
    const result = safeObject(root.result) ?? {}
    const resultStatus = normalizeId(result.status).toLowerCase()

    if (!upstream.ok || resultStatus === "error") {
      const error =
        normalizeId(result.error) ||
        normalizeId(root.error) ||
        normalizeId(root.detail) ||
        upstream.statusText ||
        "tool_failed"
      return { status: "error", error }
    }

    return {
      status: "success",
      data: safeObject(result.data) ?? {},
    }
  } catch (error) {
    return {
      status: "error",
      error: error instanceof Error ? error.message : "tool_failed",
    }
  }
}

async function resolveBoldImgViaAgent(
  request: NextRequest,
  bidsDir: string,
  args: Record<string, unknown>,
  dataset?: DatasetBidsHintSource | null,
): Promise<string | null> {
  if (!bidsDir) return null
  const hints = resolveDefaultBidsRunHints(dataset, args)

  const resolved = await runAgentTool(request, "resolve_bids", {
    bids_root: bidsDir,
    subject_id: hints.subject_id,
    session_id: hints.session_id,
    task_id: hints.task_id,
    datatype: "func",
    suffix: "bold",
  })

  if (resolved.status !== "success") return null
  const outputs = safeObject(resolved.data?.outputs)
  const primary = normalizeId(outputs?.resolved_path)
  if (primary) return primary
  const paths = Array.isArray(outputs?.resolved_paths) ? outputs?.resolved_paths : []
  for (const entry of paths) {
    const candidate = normalizeId(entry)
    if (candidate) return candidate
  }
  return null
}

async function hydrateFmriStepArgs(
  request: NextRequest,
  args: Record<string, unknown>,
  dataset?: DatasetBidsHintSource | null,
) {
  const bidsDir = normalizeId(args.bids_dir)
  const explicitImg = normalizeId(args.img ?? args.bold_img)

  if (bidsDir) {
    const resolvedImg = await resolveBoldImgViaAgent(request, bidsDir, args, dataset)
    if (resolvedImg) {
      const hints = resolveDefaultBidsRunHints(dataset, args)
      args.img = resolvedImg
      if (!normalizeId(args.bold_img)) args.bold_img = resolvedImg
      if (!normalizeId(args.subject_id ?? args.subject)) args.subject_id = hints.subject_id
      if (!normalizeId(args.task_id ?? args.task ?? args.task_name)) args.task_id = hints.task_id
      if (!normalizeId(args.session_id ?? args.session)) {
        const inferredSession = inferSessionIdFromPath(resolvedImg)
        args.session_id = inferredSession || hints.session_id
      }
      return
    }
  }

  if (explicitImg) {
    args.img = explicitImg
    if (!normalizeId(args.bold_img)) args.bold_img = explicitImg
    if (!normalizeId(args.session_id ?? args.session)) {
      const inferredSession = inferSessionIdFromPath(explicitImg)
      if (inferredSession) args.session_id = inferredSession
    }
    return
  }

  if (!bidsDir) return

  const hints = resolveDefaultBidsRunHints(dataset, args)
  if (!normalizeId(args.subject_id ?? args.subject)) args.subject_id = hints.subject_id
  if (hints.session_id && !normalizeId(args.session_id ?? args.session)) {
    args.session_id = hints.session_id
  }
  if (!normalizeId(args.task_id ?? args.task ?? args.task_name)) args.task_id = hints.task_id
  const fallbackImg = inferBoldImgPathFromBidsDir(bidsDir, hints)

  if (fallbackImg) {
    args.img = fallbackImg
    if (!normalizeId(args.bold_img)) args.bold_img = fallbackImg
    if (!normalizeId(args.session_id ?? args.session)) {
      const inferredSession = inferSessionIdFromPath(fallbackImg)
      if (inferredSession) args.session_id = inferredSession
    }
  }
}

function buildPrompt(dataset: DatasetDetailResponse, analysis: AnalysisType, pipeline: PipelineOption) {
  const sections: string[] = []
  sections.push(
    `Dataset ${dataset.name} (${dataset.id}) from ${dataset.source_repo}. Subjects: ${
      dataset.subjects_count != null ? dataset.subjects_count : "unknown"
    }. Modalities: ${dataset.modalities.join(", ") || "unspecified"}.`,
  )
  if (dataset.description) {
    sections.push(dataset.description)
  }
  if (dataset.tasks?.length) {
    sections.push(`Reported tasks/paradigms: ${dataset.tasks.join(", ")}`)
  }
  sections.push(
    `Goal: run ${pipeline.label} as a ${analysis.label.toLowerCase()} workflow. ${pipeline.description}${
      pipeline.runConfig.promptHint ? ` ${pipeline.runConfig.promptHint}` : ""
    }`,
  )
  return sections.filter(Boolean).join("\n\n")
}

function safeObject(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined
  }
  return value as Record<string, unknown>
}

function buildParameters(
  dataset: DatasetDetailResponse,
  analysis: AnalysisType,
  pipeline: PipelineOption,
  extra: Record<string, unknown> | undefined,
) {
  const toolId = normalizePipelineToolId(analysis.id, pipeline.id, pipeline.runConfig.tool)
  const base: Record<string, unknown> = {
    dataset_id: dataset.id,
    dataset_label: dataset.name,
    dataset_repo: dataset.source_repo,
    dataset_primary_url: dataset.primary_url,
    dataset_modalities: dataset.modalities,
    dataset_tasks: dataset.tasks,
    dataset_tags: dataset.tags,
    dataset_category: dataset.category,
    dataset_access: dataset.access_type,
    dataset_subjects: dataset.subjects_count,
    dataset_sessions: dataset.sessions_count,
    dataset_license: dataset.license,
    analysis_id: analysis.id,
    analysis_label: analysis.label,
    pipeline_id: pipeline.id,
    pipeline_label: pipeline.label,
    tool: toolId,
  }
  if (dataset.description) {
    base.dataset_description = dataset.description
  }
  if (dataset.size_human) {
    base.dataset_size = dataset.size_human
  }
  if (dataset.source_repo_id) {
    base.dataset_source_repo_id = dataset.source_repo_id
  }
  const merged = {
    ...base,
    ...(pipeline.runConfig.defaultParameters ?? {}),
    ...(extra ?? {}),
  }

  return applyExecutionDefaults(merged, {
    dataset,
    analysisId: analysis.id,
    pipelineId: pipeline.id,
    toolId,
  })
}

function findAnalysisAndPipeline(analysisId: string, pipelineId: string) {
  const analysis = ANALYSIS_TYPES.find((candidate) => candidate.id === analysisId)
  if (!analysis) {
    return { analysis: null, pipeline: null }
  }
  const pipeline = analysis.pipelines.find((candidate) => candidate.id === pipelineId) || null
  return { analysis, pipeline }
}

export async function POST(request: NextRequest) {
  let payload: RunFromDatasetRequest
  try {
    payload = await request.json()
  } catch (error) {
    return NextResponse.json({ detail: "Invalid JSON payload." }, { status: 400 })
  }

  const datasetId = normalizeId(payload.dataset_id)
  const analysisId = normalizeId(payload.analysis_id)
  const pipelineId = normalizeId(payload.pipeline_id)

  if (!datasetId || !analysisId || !pipelineId) {
    return NextResponse.json(
      { detail: "dataset_id, analysis_id, and pipeline_id are required." },
      { status: 400 },
    )
  }

  const dataset = getDataset(datasetId)
  if (!dataset) {
    return NextResponse.json({ detail: `Dataset ${datasetId} was not found.` }, { status: 404 })
  }

  const { analysis, pipeline } = findAnalysisAndPipeline(analysisId, pipelineId)
  if (!analysis || !pipeline) {
    return NextResponse.json({ detail: "Unknown analysis or pipeline selection." }, { status: 400 })
  }
  if (!pipeline.runConfig) {
    return NextResponse.json({ detail: "Pipeline is missing execution metadata." }, { status: 500 })
  }
  if (!datasetSupportsPipeline(dataset, pipeline)) {
    return NextResponse.json(
      {
        detail: `Pipeline ${pipeline.label} requires ${
          pipeline.modalities.length ? pipeline.modalities.join(", ") : "specific"
        } modalities, but dataset ${dataset.id} only reports ${dataset.modalities.join(", ") || "none"}.`,
      },
      { status: 400 },
    )
  }

  const prompt = buildPrompt(dataset, analysis, pipeline)
  const extraParams = safeObject(payload.params)
  const parameters = buildParameters(dataset, analysis, pipeline, extraParams)

  // Build the plan object for the analyses/orchestrator execution path.
  const toolId = normalizePipelineToolId(analysis.id, pipeline.id, pipeline.runConfig.tool)
  const plan = {
    type: "dataset_analysis",
    prompt,
    pipeline: pipeline.runConfig.pipelineType,
    dataset_id: dataset.id,
    parameters,
    intent: `${analysis.label} · ${pipeline.label}`,
    steps: [
      {
        tool: toolId || "dataset_analyze",
        args: {
          dataset_id: dataset.id,
          analysis_id: analysis.id,
          pipeline_id: pipeline.id,
          ...parameters,
        },
      },
    ],
  }

  const isConnectivityWorkflow = isConnectivityStep(toolId, analysis.id, pipeline.id)
  const isGlmWorkflow = isGlmStep(toolId, analysis.id, pipeline.id)
  if (isConnectivityWorkflow || isGlmWorkflow) {
    const stepArgs = (plan.steps?.[0]?.args ?? {}) as Record<string, unknown>
    await hydrateFmriStepArgs(request, stepArgs, dataset)
    if (
      isGlmWorkflow &&
      (
        typeof stepArgs.smoothing_fwhm !== 'number' ||
        !Number.isFinite(stepArgs.smoothing_fwhm)
      ) &&
      (
        typeof stepArgs.smoothing === 'number' ||
        (typeof stepArgs.smoothing === 'string' && stepArgs.smoothing.trim())
      )
    ) {
      stepArgs.smoothing_fwhm = stepArgs.smoothing
    }
    const normalizedImg = normalizeId(stepArgs.img ?? stepArgs.bold_img)
    if (normalizedImg) {
      const planParams = safeObject(plan.parameters)
      if (planParams) {
        planParams.img = normalizedImg
        planParams.bold_img = normalizedImg
        const normalizedSubject = normalizeId(stepArgs.subject_id ?? stepArgs.subject)
        if (normalizedSubject && !normalizeId(planParams.subject_id ?? planParams.subject)) {
          planParams.subject_id = normalizedSubject
        }
        const normalizedTask = normalizeId(stepArgs.task_id ?? stepArgs.task ?? stepArgs.task_name)
        if (normalizedTask && !normalizeId(planParams.task_id ?? planParams.task ?? planParams.task_name)) {
          planParams.task_id = normalizedTask
        }
        const normalizedSession = normalizeId(stepArgs.session_id ?? stepArgs.session)
        if (normalizedSession) {
          planParams.session_id = normalizedSession
        }
        if (
          isGlmWorkflow &&
          (
            typeof planParams.smoothing_fwhm !== 'number' ||
            !Number.isFinite(planParams.smoothing_fwhm)
          ) &&
          (
            typeof stepArgs.smoothing_fwhm === 'number' ||
            (typeof stepArgs.smoothing_fwhm === 'string' &&
              stepArgs.smoothing_fwhm.trim())
          )
        ) {
          planParams.smoothing_fwhm = stepArgs.smoothing_fwhm
        }
      }
    }
  }

  const stepArgs = (plan.steps?.[0]?.args ?? {}) as Record<string, unknown>
  const inputError = isConnectivityWorkflow
    ? validateConnectivityArgs(stepArgs)
    : isGlmWorkflow
      ? validateGlmArgs(stepArgs)
      : null
  if (inputError) {
    return NextResponse.json({ detail: inputError }, { status: 400 })
  }

  try {
    const headers = forwardAuthHeaders(request)
    headers.set("content-type", "application/json")
    // Compatibility route name only. Dataset-triggered run creation now
    // normalizes to the Orchestrator `/run` path via the shared analyses
    // payload builder.
    const orchestratorPayload = buildOrchestratorRunPayload(plan, "default", null)

    const orchestratorResponse = await fetch(`${resolveOrchestratorBaseUrl()}/run`, {
      method: "POST",
      headers,
      body: JSON.stringify(orchestratorPayload),
      cache: "no-store",
    })
    const rawBody = await orchestratorResponse.text()
    let parsed: OrchestratorRunResponse = {}
    if (rawBody) {
      try {
        parsed = JSON.parse(rawBody)
      } catch {
        parsed = { detail: rawBody }
      }
    }

    if (!orchestratorResponse.ok) {
      const detail =
        (parsed.detail as string) ||
        (parsed.error as string) ||
        orchestratorResponse.statusText ||
        "Failed to create run."
      return NextResponse.json({ detail }, { status: orchestratorResponse.status })
    }

    const runId = parsed.analysis_id || parsed.job_id || parsed.run_id || null
    const status = parsed.status ?? "queued"
    return NextResponse.json(
      {
        run_id: runId,
        job_id: parsed.job_id || runId,
        status,
        raw: parsed,
      },
      { status: 201 },
    )
  } catch (error) {
    console.error("Failed to create run from dataset", error)
    return NextResponse.json({ detail: "Unable to reach orchestrator service." }, { status: 502 })
  }
}
