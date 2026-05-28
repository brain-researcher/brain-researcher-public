import { NextRequest, NextResponse } from 'next/server'

import { ANALYSIS_TYPES, AnalysisType, PipelineOption } from '@/config/analysis-presets'
import type { WorkflowDetail } from '@/lib/api/workflows'
import {
  inferBidsRunHintsFromPath,
  inferBoldImgPathFromBidsDir,
  inferSessionIdFromPath,
  resolveDefaultBidsRunHints,
  type DatasetBidsHintSource,
} from '@/lib/server/bids-defaults'
import {
  commitCreditsReservation,
  estimateCreditsFromRuntime,
  releaseCreditsReservation,
  reserveCredits,
  resolveCreditsIdentity,
} from '@/lib/server/credits'
import { getDataset } from '@/lib/server/dataset-catalog'
import {
  forwardAuthHeaders,
  resolveAgentBaseUrl,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'
import { buildPlannerHandoffPack } from '@/lib/launch-handoff-pack'
import {
  deriveRecipeLaunchStatus,
  type RecipeLaunchStatus,
} from '@/lib/server/launch-decision'
import {
  buildWorkflowExecutionStatus,
  workflowTargetsRequireLocalBackend,
  type WorkflowExecutionStatus,
} from '@/lib/server/workflow-execution-status'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { getWorkflowById } from '@/lib/server/workflow-catalog'
import {
  canonicalizeTemplateSelection,
  workflowIdFromReference,
  type CanonicalTemplateSelection,
} from '@/lib/workflow-template-aliases'
import type { DatasetDetailResponse } from '@/types/datasets-search'
import type {
  AnalysesListResponse,
  AnalysisCreateResponse,
  AnalysisStatus,
  AnalysisSummary,
} from '@/types/analysis'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
const RETRY_ATTEMPTS = 2
const INFERRED_BIDS_IMG = Symbol('inferredBidsImg')

// `/api/analyses` is the public browser-facing analysis facade.
// Create/list/detail/stream/share/export all resolve through Orchestrator
// job/analysis resources now. Agent remains responsible for `/act`, `/api/chat`,
// `/api/files`, `/api/datasets`, `/api/threads`, and the legacy `/api/runs`
// compatibility surface.

const CREDITS_ENFORCEMENT_ENABLED =
  process.env.BR_CREDITS_ENFORCEMENT === '0' ||
  process.env.NEXT_PUBLIC_CREDITS_ENFORCEMENT === '0'
    ? false
    : process.env.NODE_ENV !== 'test'

type OrchestratorAnalysisRecord = {
  analysis_id?: string
  job_id?: string
  run_id?: string
  state?: string
  status?: string
  created_at?: number
  started_at?: number | string | null
  finished_at?: number | string | null
  thread_id?: string | null
  project_id?: string | null
  title?: string | null
  dataset_id?: string | null
  dataset?: {
    dataset_id?: string
    name?: string
    source?: string
  } | null
  template_id?: string | null
  analysis_preset_id?: string | null
  pipeline_preset_id?: string | null
  template?: {
    template_id?: string
    analysis_id?: string
    pipeline_id?: string
    name?: string
  } | null
  has_results?: boolean
}

type OrchestratorAnalysesListResponse = {
  items?: OrchestratorAnalysisRecord[]
  count?: number
}

type OrchestratorRunResponse = {
  job_id?: string
  analysis_id?: string
  status?: string
  created_at?: number | string | null
  analysis_url?: string | null
  analysis_stream_url?: string | null
}

type PlannerStepSpec = {
  id: string
  tool: string
  consumes: Record<string, string>
  produces: Record<string, string>
  params: Record<string, unknown>
  metadata: Record<string, unknown>
  runtime_kind: 'container' | 'python' | 'api'
}

type PlannerPlan = {
  plan_id: string
  version: number
  schema_version: '1.0'
  domain: 'neuroimaging'
  modality: string[]
  resolvable: boolean
  dag: {
    steps: PlannerStepSpec[]
    artifacts: []
  }
  estimates: Record<string, number>
  warnings: string[]
  chosen_tool?: string
  selection_reason?: string
  planner_state?: Record<string, unknown>
}

type RuntimeToolCheck = {
  requested_tool_id?: string
  tool_id?: string
  status?: string
  available?: boolean
  code?: string
}

type RuntimePreflightResponse = {
  executable?: boolean
  checks?: RuntimeToolCheck[]
  warnings?: string[]
}

type LaunchPreflightResult = {
  status: 'passed' | 'warning' | 'blocked'
  detail?: string
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max)

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchWithRetry(url: string, init: RequestInit): Promise<Response> {
  let lastError: unknown = null
  for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(url, init)
      if (response.status >= 500 && attempt + 1 < RETRY_ATTEMPTS) {
        await sleep(150 * (attempt + 1))
        continue
      }
      return response
    } catch (error) {
      lastError = error
      if (attempt + 1 < RETRY_ATTEMPTS) {
        await sleep(150 * (attempt + 1))
        continue
      }
      throw lastError
    }
  }
  throw lastError ?? new Error('Unknown upstream error')
}

const toEpochSeconds = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    // Heuristic: epoch ms is ~1e12+; epoch seconds is ~1e9.
    return value > 1e11 ? Math.floor(value / 1000) : value
  }
  if (typeof value !== 'string' || !value.trim()) return null
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return null
  return Math.floor(ms / 1000)
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function normalizeConceptIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const normalized: string[] = []
  const seen = new Set<string>()
  for (const entry of value) {
    if (typeof entry !== 'string') continue
    const trimmed = entry.trim()
    if (!trimmed || seen.has(trimmed)) continue
    seen.add(trimmed)
    normalized.push(trimmed)
    if (normalized.length >= 12) break
  }
  return normalized
}

function uniqueStrings(values: unknown[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const text = normalizeId(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
  }
  return out
}

function markInferredBidsImg(record: Record<string, unknown>) {
  const metadata = record as Record<PropertyKey, unknown>
  metadata[INFERRED_BIDS_IMG] = true
}

function isInferredBidsImg(record: Record<string, unknown>): boolean {
  const metadata = record as Record<PropertyKey, unknown>
  return metadata[INFERRED_BIDS_IMG] === true
}

const CONNECTIVITY_KIND_MAP: Record<string, string> = {
  correlation: 'correlation',
  partialcorrelation: 'partial correlation',
  tangent: 'tangent',
  covariance: 'covariance',
  precision: 'precision',
}

function normalizeConnectivityKind(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const normalizedKey = trimmed.toLowerCase().replace(/[\s_-]+/g, '')
  return CONNECTIVITY_KIND_MAP[normalizedKey] ?? trimmed
}

function normalizePipelineToolId(analysisId: string, pipelineId: string, toolId: string): string {
  if (analysisId === 'connectivity' && pipelineId === 'nilearn_connectivity') {
    return 'workflow_rest_connectome_e2e'
  }
  if (toolId === 'connectivity_matrix') {
    return 'workflow_rest_connectome_e2e'
  }
  return toolId
}

function runtimeEstimateForToolId(toolId: string, fallback?: string | null): string | null {
  const explicit = normalizeId(fallback)
  if (explicit && explicit.toLowerCase() !== 'varies' && /\d/.test(explicit)) return explicit
  const normalizedToolId = normalizeId(toolId)
  if (!normalizedToolId) return explicit || null

  for (const analysis of ANALYSIS_TYPES) {
    for (const pipeline of analysis.pipelines) {
      const candidateToolId = normalizePipelineToolId(
        analysis.id,
        pipeline.id,
        pipeline.runConfig.tool,
      )
      if (candidateToolId === normalizedToolId && pipeline.estRuntime) {
        return pipeline.estRuntime
      }
    }
  }

  return explicit || null
}

function appendConceptContext(prompt: string, conceptIds: string[]): string {
  if (!conceptIds.length) return prompt
  const base = typeof prompt === 'string' ? prompt.trimEnd() : ''
  if (!base.trim()) return prompt
  const block = ['Concept context:', ...conceptIds.map((id) => `- ${id}`)].join('\n')
  return `${base}\n\n${block}\n`
}

function normalizeStatus(value: unknown): AnalysisStatus {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'claimed') return 'running'
  if (normalized === 'skipped') return 'cancelled'
  if (normalized === 'succeeded') return 'completed'
  const allowed = new Set<AnalysisStatus>([
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled',
    'cancelling',
    'retrying',
    'paused',
    'timeout',
    'unknown',
  ])
  return allowed.has(normalized as AnalysisStatus) ? (normalized as AnalysisStatus) : 'unknown'
}

function isBlockingRuntimeTool(check: RuntimeToolCheck): boolean {
  const status = (check.status ?? '').trim().toLowerCase()
  const code = (check.code ?? '').trim().toUpperCase()
  return (
    status === 'missing' ||
    status === 'blocked' ||
    status === 'not_found' ||
    status === 'not-found' ||
    code === 'UNKNOWN_TOOL_ALIAS' ||
    code === 'RUNTIME_TOOL_NOT_REGISTERED' ||
    code === 'RUNTIME_TOOL_NOT_ALLOWED'
  )
}

function buildRuntimeCheckDetail(payload: RuntimePreflightResponse): string {
  const checks = Array.isArray(payload.checks) ? payload.checks : []
  const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : []
  const missing = checks
    .filter((check) => isBlockingRuntimeTool(check))
    .map((check) => normalizeId(check.requested_tool_id) || normalizeId(check.tool_id))
    .filter(Boolean)

  const parts: string[] = []
  if (missing.length) {
    parts.push(`Missing or blocked runtime tools: ${missing.join(', ')}`)
  }
  if (warnings.length) parts.push(warnings.join(' | '))
  return parts.join('. ') || 'Runtime preflight reported this workflow is not executable.'
}

async function runLaunchPreflight(
  req: NextRequest,
  payload: Record<string, unknown>,
): Promise<LaunchPreflightResult> {
  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  try {
    const response = await fetch(`${resolveOrchestratorBaseUrl()}/api/preflight/check`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      cache: 'no-store',
    })
    if (!response.ok) {
      return {
        status: 'warning',
        detail: `Runtime preflight returned HTTP ${response.status}; proceeding without executability proof.`,
      }
    }

    const parsed = (await response.json().catch(() => null)) as RuntimePreflightResponse | null
    const preflight = parsed && typeof parsed === 'object' ? parsed : {}
    if (preflight.executable) return { status: 'passed' }
    if (
      Array.isArray(preflight.checks) &&
      preflight.checks.some((check) => isBlockingRuntimeTool(check))
    ) {
      return { status: 'blocked', detail: buildRuntimeCheckDetail(preflight) }
    }
    return { status: 'warning', detail: buildRuntimeCheckDetail(preflight) }
  } catch {
    return {
      status: 'warning',
      detail: 'Runtime preflight service is unavailable; proceeding without executability proof.',
    }
  }
}

function parseTemplateIds(body: Record<string, unknown>): CanonicalTemplateSelection | null {
  const analysisId = normalizeId(body.analysis_id)
  const pipelineId = normalizeId(body.pipeline_id)
  const templateId = normalizeId(body.template_id)

  if (analysisId && pipelineId) {
    return canonicalizeTemplateSelection({
      analysisId,
      pipelineId,
      templateId: templateId || `${analysisId}/${pipelineId}`,
    })
  }

  if (!templateId) return null
  const workflowId = workflowIdFromReference(templateId)
  if (workflowId) {
    return canonicalizeTemplateSelection({
      analysisId: 'dynamic_workflow',
      pipelineId: templateId,
      templateId,
    })
  }

  const parts = templateId.split(/[:/]/).filter(Boolean)
  if (parts.length !== 2) return null
  return canonicalizeTemplateSelection({
    analysisId: parts[0] ?? '',
    pipelineId: parts[1] ?? '',
    templateId,
  })
}

function datasetSupportsPipeline(dataset: DatasetDetailResponse, pipeline: PipelineOption) {
  if (!pipeline.modalities.length) return true
  const datasetModalities = new Set((dataset.modalities ?? []).map((m) => m.toLowerCase()))
  return pipeline.modalities.some((required) => datasetModalities.has(required.toLowerCase()))
}

function datasetSupportsModalities(dataset: DatasetDetailResponse, requiredModalities: string[]) {
  if (!requiredModalities.length) return true
  const datasetModalities = new Set((dataset.modalities ?? []).map((m) => m.toLowerCase()))
  return requiredModalities.some((required) => datasetModalities.has(required.toLowerCase()))
}

async function fetchDatasetDetail(
  req: NextRequest,
  datasetId: string,
): Promise<DatasetDetailResponse | null> {
  const origin = req.nextUrl.origin
  if (!origin) return null

  try {
    const resp = await fetch(
      `${origin}/api/catalog/datasets/${encodeURIComponent(datasetId)}`,
      { cache: 'no-store' },
    )
    if (!resp.ok) return null
    const parsed = (await resp.json().catch(() => null)) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const record = parsed as DatasetDetailResponse
    if (!record.id) return null
    return record
  } catch {
    return null
  }
}

function buildPrompt(
  dataset: DatasetDetailResponse,
  analysis: AnalysisType,
  pipeline: PipelineOption,
  datasetVersion?: string,
) {
  const sections: string[] = []
  sections.push(
    `Dataset ${dataset.name} (${dataset.id}) from ${dataset.source_repo}. Subjects: ${
      dataset.subjects_count != null ? dataset.subjects_count : 'unknown'
    }. Modalities: ${dataset.modalities.join(', ') || 'unspecified'}.`,
  )
  if (datasetVersion) {
    sections.push(`Requested dataset version: ${datasetVersion}.`)
  }
  if (dataset.description) sections.push(dataset.description)
  if (dataset.tasks?.length) sections.push(`Reported tasks/paradigms: ${dataset.tasks.join(', ')}`)
  sections.push(
    `Goal: run ${pipeline.label} as a ${analysis.label.toLowerCase()} workflow. ${pipeline.description}${
      pipeline.runConfig.promptHint ? ` ${pipeline.runConfig.promptHint}` : ''
    }`,
  )
  return sections.filter(Boolean).join('\n\n')
}

function sanitizePathToken(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '')
}

function validateConnectivityStepArgs(args: Record<string, unknown>): string | null {
  const img = normalizeId(args.img ?? args.bold_img)
  const bidsDir = normalizeId(args.bids_dir)

  if (!img && !bidsDir) {
    return 'Connectivity run requires a BOLD image path. Provide parameters.img or set parameters.bids_dir to a valid BIDS directory.'
  }
  return null
}

function validateGlmStepArgs(args: Record<string, unknown>): string | null {
  const img = normalizeId(args.img ?? args.bold_img)
  const bidsDir = normalizeId(args.bids_dir)

  if (!img && !bidsDir) {
    return 'Task GLM run requires a BOLD image path. Provide parameters.img or set parameters.bids_dir to a valid BIDS directory.'
  }
  return null
}

function isConnectivityPlanStep(stepTool: string, stepArgs: Record<string, unknown>): boolean {
  const stepAnalysisId = normalizeId(stepArgs.analysis_id)
  const stepPipelineId = normalizeId(stepArgs.pipeline_id)
  return (
    stepTool === 'workflow_rest_connectome_e2e' ||
    (stepAnalysisId === 'connectivity' && stepPipelineId === 'nilearn_connectivity')
  )
}

function isGlmPlanStep(stepTool: string, stepArgs: Record<string, unknown>): boolean {
  const stepAnalysisId = normalizeId(stepArgs.analysis_id)
  const stepPipelineId = normalizeId(stepArgs.pipeline_id)
  return (
    stepTool === 'glm_first_level' ||
    (stepAnalysisId === 'glm' && stepPipelineId === 'nilearn_glm')
  )
}

function planInputValidationErrorForExecution(plan: Record<string, unknown> | null): string | null {
  const steps = Array.isArray(plan?.steps) ? plan.steps : []
  for (const step of steps) {
    const stepRecord = safeRecord(step)
    if (!stepRecord) continue
    const stepTool = normalizeId(stepRecord.tool)
    const stepArgs = safeRecord(stepRecord.args) ?? {}
    if (isConnectivityPlanStep(stepTool, stepArgs)) {
      return validateConnectivityStepArgs(stepArgs)
    }
    if (isGlmPlanStep(stepTool, stepArgs)) {
      return validateGlmStepArgs(stepArgs)
    }
  }
  return null
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
    analysisId === 'dynamic_workflow' ||
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

  if (pipelineId === 'workflow_preprocessing_qc' || toolId === 'workflow_preprocessing_qc') {
    if (typeof merged.qc_tsv !== 'string' || !merged.qc_tsv.trim()) {
      const outputDir =
        typeof merged.output_dir === 'string' && merged.output_dir.trim()
          ? merged.output_dir
          : defaultOutputDir
      merged.qc_tsv = `${outputDir}/mriqc/group_bold.tsv`
    }
    if (typeof merged.outlier_metric !== 'string' || !merged.outlier_metric.trim()) {
      merged.outlier_metric = 'fd_mean'
    }
    if (
      typeof merged.outlier_z !== 'number' &&
      (typeof merged.outlier_z !== 'string' || !String(merged.outlier_z).trim())
    ) {
      merged.outlier_z = 2.5
    }
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
      markInferredBidsImg(merged)
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
      markInferredBidsImg(merged)
    }
  }

  return merged
}

type AgentToolRunResult = {
  status: 'success' | 'error'
  data?: Record<string, unknown>
  error?: string
}

async function runAgentTool(
  req: NextRequest,
  tool: string,
  args: Record<string, unknown>,
): Promise<AgentToolRunResult> {
  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  try {
    const upstream = await fetch(`${resolveAgentBaseUrl()}/api/tools/run`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ tool, args, arguments: args }),
      cache: 'no-store',
    })
    const raw = await upstream.text()
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    const root = safeRecord(parsed) ?? {}
    const result = safeRecord(root.result) ?? {}
    const resultStatus = normalizeId(result.status).toLowerCase()

    if (!upstream.ok || resultStatus === 'error') {
      const error =
        normalizeId(result.error) ||
        normalizeId(root.error) ||
        normalizeId(root.detail) ||
        upstream.statusText ||
        'tool_failed'
      return { status: 'error', error }
    }

    return {
      status: 'success',
      data: safeRecord(result.data) ?? {},
    }
  } catch (error) {
    return {
      status: 'error',
      error: error instanceof Error ? error.message : 'tool_failed',
    }
  }
}

async function resolveBoldImgViaAgent(
  req: NextRequest,
  bidsDir: string,
  args: Record<string, unknown>,
  dataset?: DatasetBidsHintSource | null,
): Promise<string | null> {
  if (!bidsDir) return null
  const hints = resolveDefaultBidsRunHints(dataset, args)

  const resolved = await runAgentTool(req, 'resolve_bids', {
    bids_root: bidsDir,
    subject_id: hints.subject_id,
    session_id: hints.session_id,
    task_id: hints.task_id,
    datatype: 'func',
    suffix: 'bold',
  })
  if (resolved.status !== 'success') return null

  const outputs = safeRecord(resolved.data?.outputs)
  const primary = normalizeId(outputs?.resolved_path)
  if (primary) return primary

  const resolvedPaths = Array.isArray(outputs?.resolved_paths) ? outputs?.resolved_paths : []
  for (const entry of resolvedPaths) {
    const candidate = normalizeId(entry)
    if (candidate) return candidate
  }

  return null
}

async function hydratePlanBoldInputs(
  req: NextRequest,
  plan: Record<string, unknown> | null,
  dataset?: DatasetBidsHintSource | null,
) {
  const planParams = safeRecord(plan?.parameters)
  const steps = Array.isArray(plan?.steps) ? plan.steps : []
  for (const step of steps) {
    const stepRecord = safeRecord(step)
    if (!stepRecord) continue
    const stepTool = normalizeId(stepRecord.tool)
    const stepArgs = safeRecord(stepRecord.args)
    if (!stepArgs) continue

    const isConnectivityStep = isConnectivityPlanStep(stepTool, stepArgs)
    const isGlmStep = isGlmPlanStep(stepTool, stepArgs)
    if (!isConnectivityStep && !isGlmStep) continue

    if (
      isGlmStep &&
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
      if (
        planParams &&
        (
          typeof planParams.smoothing_fwhm !== 'number' ||
          !Number.isFinite(planParams.smoothing_fwhm)
        )
      ) {
        planParams.smoothing_fwhm = stepArgs.smoothing
      }
    }

    const bidsDir = normalizeId(stepArgs.bids_dir)
    const explicitImg = normalizeId(stepArgs.img ?? stepArgs.bold_img)
    const inferredDefaultImg = isInferredBidsImg(stepArgs)

    if (explicitImg && !inferredDefaultImg) {
      const pathHints = inferBidsRunHintsFromPath(explicitImg)
      stepArgs.img = explicitImg
      if (!normalizeId(stepArgs.bold_img)) stepArgs.bold_img = explicitImg
      if (pathHints.subject_id && !normalizeId(stepArgs.subject_id ?? stepArgs.subject)) {
        stepArgs.subject_id = pathHints.subject_id
      }
      if (pathHints.task_id && !normalizeId(stepArgs.task_id ?? stepArgs.task ?? stepArgs.task_name)) {
        stepArgs.task_id = pathHints.task_id
      }
      if (pathHints.session_id && !normalizeId(stepArgs.session_id ?? stepArgs.session)) {
        stepArgs.session_id = pathHints.session_id
      }
      if (planParams) {
        planParams.img = explicitImg
        planParams.bold_img = explicitImg
        if (pathHints.subject_id && !normalizeId(planParams.subject_id ?? planParams.subject)) {
          planParams.subject_id = pathHints.subject_id
        }
        if (pathHints.task_id && !normalizeId(planParams.task_id ?? planParams.task ?? planParams.task_name)) {
          planParams.task_id = pathHints.task_id
        }
        const normalizedSession = normalizeId(stepArgs.session_id ?? stepArgs.session)
        if (normalizedSession) {
          planParams.session_id = normalizedSession
        }
      }
      continue
    }

    if (bidsDir) {
      const resolvedImg = await resolveBoldImgViaAgent(req, bidsDir, stepArgs, dataset)
      if (resolvedImg) {
        const hints = resolveDefaultBidsRunHints(dataset, stepArgs)
        stepArgs.img = resolvedImg
        if (!normalizeId(stepArgs.bold_img)) stepArgs.bold_img = resolvedImg
        if (!normalizeId(stepArgs.subject_id ?? stepArgs.subject)) stepArgs.subject_id = hints.subject_id
        if (!normalizeId(stepArgs.task_id ?? stepArgs.task ?? stepArgs.task_name)) {
          stepArgs.task_id = hints.task_id
        }
        if (!normalizeId(stepArgs.session_id ?? stepArgs.session)) {
          const inferredSession = inferSessionIdFromPath(resolvedImg)
          stepArgs.session_id = inferredSession || hints.session_id
        }
        if (planParams) {
          planParams.img = resolvedImg
          planParams.bold_img = resolvedImg
          if (!normalizeId(planParams.subject_id ?? planParams.subject)) {
            planParams.subject_id = hints.subject_id
          }
          if (!normalizeId(planParams.task_id ?? planParams.task ?? planParams.task_name)) {
            planParams.task_id = hints.task_id
          }
          const normalizedSession = normalizeId(stepArgs.session_id ?? stepArgs.session)
          if (normalizedSession) {
            planParams.session_id = normalizedSession
          }
        }
        continue
      }
    }

    if (!bidsDir) continue

    const hints = resolveDefaultBidsRunHints(dataset, stepArgs)
    if (!normalizeId(stepArgs.subject_id ?? stepArgs.subject)) stepArgs.subject_id = hints.subject_id
    if (hints.session_id && !normalizeId(stepArgs.session_id ?? stepArgs.session)) {
      stepArgs.session_id = hints.session_id
    }
    if (!normalizeId(stepArgs.task_id ?? stepArgs.task ?? stepArgs.task_name)) {
      stepArgs.task_id = hints.task_id
    }
    const fallbackImg = inferBoldImgPathFromBidsDir(bidsDir, hints)

    if (fallbackImg) {
      stepArgs.img = fallbackImg
      if (!normalizeId(stepArgs.bold_img)) stepArgs.bold_img = fallbackImg
      if (!normalizeId(stepArgs.session_id ?? stepArgs.session)) {
        const inferredSession = inferSessionIdFromPath(fallbackImg)
        if (inferredSession) stepArgs.session_id = inferredSession
      }
      if (planParams) {
        planParams.img = fallbackImg
        planParams.bold_img = fallbackImg
        if (!normalizeId(planParams.subject_id ?? planParams.subject)) {
          planParams.subject_id = hints.subject_id
        }
        if (!normalizeId(planParams.task_id ?? planParams.task ?? planParams.task_name)) {
          planParams.task_id = hints.task_id
        }
        const normalizedSession = normalizeId(stepArgs.session_id ?? stepArgs.session)
        if (normalizedSession) {
          planParams.session_id = normalizedSession
        }
      }
    }
  }
}

function buildDynamicWorkflowPrompt(
  dataset: DatasetDetailResponse,
  workflow: WorkflowDetail,
  datasetVersion?: string,
) {
  const sections: string[] = []
  sections.push(
    `Dataset ${dataset.name} (${dataset.id}) from ${dataset.source_repo}. Subjects: ${
      dataset.subjects_count != null ? dataset.subjects_count : 'unknown'
    }. Modalities: ${(dataset.modalities ?? []).join(', ') || 'unspecified'}.`,
  )
  if (datasetVersion) {
    sections.push(`Requested dataset version: ${datasetVersion}.`)
  }
  if (dataset.description) sections.push(dataset.description)
  const summary = workflow.description || workflow.impl || workflow.id
  sections.push(`Goal: run dynamic workflow ${workflow.id}. ${summary}`)
  const tools = (workflow.runtime?.steps ?? [])
    .map((step) => (typeof step.tool === 'string' ? step.tool.trim() : ''))
    .filter(Boolean)
  if (tools.length) sections.push(`Workflow steps/tools: ${tools.join(' -> ')}`)
  return sections.filter(Boolean).join('\n\n')
}

function buildParameters(
  dataset: DatasetDetailResponse,
  analysis: AnalysisType,
  pipeline: PipelineOption,
  extra: Record<string, unknown> | null,
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
  if (dataset.description) base.dataset_description = dataset.description
  if (dataset.size_human) base.dataset_size = dataset.size_human
  if (dataset.source_repo_id) base.dataset_source_repo_id = dataset.source_repo_id

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

function buildDynamicWorkflowParameters(
  dataset: DatasetDetailResponse,
  workflow: WorkflowDetail,
  extra: Record<string, unknown> | null,
) {
  const tools = (workflow.runtime?.steps ?? [])
    .map((step) => (typeof step.tool === 'string' ? step.tool.trim() : ''))
    .filter(Boolean)

  const base: Record<string, unknown> = {
    dataset_id: dataset.id,
    dataset_label: dataset.name,
    dataset_repo: dataset.source_repo,
    dataset_primary_url: dataset.primary_url,
    dataset_modalities: dataset.modalities ?? [],
    dataset_tasks: dataset.tasks ?? [],
    dataset_tags: dataset.tags ?? [],
    dataset_category: dataset.category,
    dataset_access: dataset.access_type,
    dataset_subjects: dataset.subjects_count,
    dataset_sessions: dataset.sessions_count,
    dataset_license: dataset.license,
    analysis_id: 'dynamic_workflow',
    analysis_label: 'Dynamic Workflow',
    pipeline_id: workflow.id,
    pipeline_label: workflow.description || workflow.id,
    workflow_id: workflow.id,
    workflow_stage: workflow.stage,
    workflow_tools: tools,
    tool: workflow.id,
  }
  if (dataset.description) base.dataset_description = dataset.description
  if (dataset.size_human) base.dataset_size = dataset.size_human
  if (dataset.source_repo_id) base.dataset_source_repo_id = dataset.source_repo_id

  const merged = {
    ...base,
    ...(extra ?? {}),
  }

  return applyExecutionDefaults(merged, {
    dataset,
    analysisId: 'dynamic_workflow',
    pipelineId: workflow.id,
    toolId: workflow.id,
  })
}

function buildFallbackDataset(datasetId: string, requiredModalities: string[]): DatasetDetailResponse {
  return {
    id: datasetId,
    name: datasetId,
    description: undefined,
    category: undefined,
    modalities: requiredModalities.length ? [...requiredModalities] : [],
    acquisitions: [],
    subjects_count: undefined,
    sessions_count: undefined,
    access_type: 'unknown',
    license: 'unknown',
    source_repo: 'unknown',
    source_repo_id: undefined,
    primary_url: datasetId,
    center: undefined,
    consortium: undefined,
    tags: [],
    tasks: [],
    has_derivatives: false,
    preview_media: [],
    score: undefined,
    created_at: undefined,
    updated_at: undefined,
    species: ['human'],
    disease_flags: [],
    search_blob: '',
  }
}

function findAnalysisAndPipeline(analysisId: string, pipelineId: string) {
  const analysis = ANALYSIS_TYPES.find((candidate) => candidate.id === analysisId) ?? null
  if (!analysis) return { analysis: null, pipeline: null }
  const pipeline = analysis.pipelines.find((candidate) => candidate.id === pipelineId) ?? null
  return { analysis, pipeline }
}

const RUN_PIPELINE_SET = new Set([
  'glm',
  'connectivity',
  'decoding',
  'preprocessing',
  'custom',
  'demo',
  'pipeline_builder',
  'chat',
  'copilot',
])

function firstNonEmptyText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value !== 'string') continue
    const trimmed = value.trim()
    if (trimmed) return trimmed
  }
  return ''
}

function firstStepArgs(plan: Record<string, unknown>): Record<string, unknown> {
  const steps = Array.isArray(plan.steps) ? plan.steps : []
  const firstStep = safeRecord(steps[0])
  return safeRecord(firstStep?.args) ?? {}
}

function firstStepRecord(plan: Record<string, unknown>): Record<string, unknown> {
  const steps = Array.isArray(plan.steps) ? plan.steps : []
  return safeRecord(steps[0]) ?? {}
}

function explicitPlanWorkflowCandidates(plan: Record<string, unknown>): string[] {
  const parameters = safeRecord(plan.parameters) ?? {}
  const firstStep = firstStepRecord(plan)
  const stepArgs = firstStepArgs(plan)
  const candidates: string[] = []
  const addCandidate = (value: unknown) => {
    const raw = normalizeId(value)
    if (!raw) return
    const fromReference = workflowIdFromReference(raw)
    for (const candidate of [fromReference, raw]) {
      if (!candidate || candidates.includes(candidate)) continue
      candidates.push(candidate)
    }
  }

  addCandidate(firstStep.tool)
  addCandidate(stepArgs.workflow_id)
  addCandidate(parameters.workflow_id)
  addCandidate(plan.workflow_id)
  addCandidate(stepArgs.pipeline_id)
  addCandidate(parameters.pipeline_id)
  addCandidate(plan.pipeline_id)
  addCandidate(parameters.template_id)
  addCandidate(plan.template_id)
  return candidates
}

function resolveExplicitPlanWorkflow(plan: Record<string, unknown>): WorkflowDetail | null {
  for (const workflowId of explicitPlanWorkflowCandidates(plan)) {
    const workflow = getWorkflowById(workflowId).workflow
    if (workflow) return workflow
  }
  return null
}

function variantsMultiplierFromPlan(plan: Record<string, unknown>): number {
  const parameters = safeRecord(plan.parameters) ?? {}
  const stepArgs = firstStepArgs(plan)
  const maxModels = parameters.max_models ?? stepArgs.max_models
  if (typeof maxModels !== 'number' || !Number.isFinite(maxModels)) return 1
  return Math.max(1, Math.floor(maxModels))
}

function resolvePlanTemplateIds(plan: Record<string, unknown>): {
  templateId: string
  analysisPresetId: string
  pipelinePresetId: string
} {
  const stepArgs = firstStepArgs(plan)
  const analysisPresetId =
    normalizeId(plan.analysis_id) || normalizeId(stepArgs.analysis_id)
  const pipelinePresetId =
    normalizeId(plan.pipeline_id) || normalizeId(stepArgs.pipeline_id)
  const templateId =
    normalizeId(plan.template_id) ||
    (analysisPresetId && pipelinePresetId ? `${analysisPresetId}/${pipelinePresetId}` : '')

  return { templateId, analysisPresetId, pipelinePresetId }
}

function normalizePlannerRuntimeKind(value: unknown): 'container' | 'python' | 'api' {
  const normalized = normalizeId(value).toLowerCase()
  if (normalized === 'python' || normalized === 'api') return normalized
  return 'container'
}

function workflowPlannerRuntimeKind(workflow: WorkflowDetail): 'container' | 'python' | 'api' {
  const primaryTarget = normalizeId(workflow.primary_target).toLowerCase()
  if (primaryTarget === 'python' || primaryTarget === 'api') return primaryTarget
  const supportedTargets = Array.isArray(workflow.supported_recipe_targets)
    ? workflow.supported_recipe_targets.map((target) => normalizeId(target).toLowerCase())
    : []
  if (supportedTargets.includes('python')) return 'python'
  if (supportedTargets.includes('api')) return 'api'
  return 'container'
}

function inferRunPipeline(plan: Record<string, unknown>): string {
  const direct = normalizeId(plan.pipeline).toLowerCase()
  if (RUN_PIPELINE_SET.has(direct)) return direct

  const { analysisPresetId, pipelinePresetId } = resolvePlanTemplateIds(plan)
  const firstStep = safeRecord((Array.isArray(plan.steps) ? plan.steps[0] : null) ?? null)
  const toolId = normalizeId(firstStep?.tool).toLowerCase()

  if (
    analysisPresetId === 'glm' ||
    pipelinePresetId === 'nilearn_glm' ||
    toolId === 'glm_first_level'
  ) {
    return 'glm'
  }
  if (
    analysisPresetId === 'connectivity' ||
    pipelinePresetId === 'nilearn_connectivity' ||
    toolId === 'workflow_rest_connectome_e2e' ||
    toolId === 'connectivity_matrix'
  ) {
    return 'connectivity'
  }
  if (
    analysisPresetId === 'preprocess' ||
    analysisPresetId === 'preprocessing' ||
    analysisPresetId === 'dynamic_workflow' ||
    ['fmriprep', 'qsiprep', 'mriqc', 'run_bids_app', 'workflow_preprocessing_qc'].includes(
      pipelinePresetId || toolId,
    )
  ) {
    return 'preprocessing'
  }
  if (direct === 'dataset_analysis' || direct === 'dataset-analyze' || direct === 'dataset_analyze') {
    return 'custom'
  }
  return 'custom'
}

function inferPlannerModalities(plan: Record<string, unknown>): string[] {
  const normalized: string[] = []
  const seen = new Set<string>()
  const add = (value: unknown) => {
    if (typeof value !== 'string') return
    const mapped = value.trim().toLowerCase()
    const canonical =
      mapped === 'bold'
        ? 'fmri'
        : mapped === 'structural' || mapped === 'anatomical'
          ? 'smri'
          : mapped === 'diffusion'
            ? 'dmri'
            : mapped
    if (!canonical || seen.has(canonical)) return
    if (!['fmri', 'eeg', 'meg', 'ieeg', 'dmri', 'smri', 'pet', 'multimodal', 'general'].includes(canonical)) {
      return
    }
    seen.add(canonical)
    normalized.push(canonical)
  }

  const planParameters = safeRecord(plan.parameters) ?? {}
  const modalityCandidates = [
    planParameters.modality,
    planParameters.modalities,
    firstStepArgs(plan).modality,
    firstStepArgs(plan).modalities,
  ]
  for (const candidate of modalityCandidates) {
    if (Array.isArray(candidate)) {
      candidate.forEach(add)
    } else {
      add(candidate)
    }
  }

  const datasetId =
    normalizeId(plan.dataset_id) || normalizeId(planParameters.dataset_id)
  const dataset = datasetId ? getDataset(datasetId) : null
  for (const modality of dataset?.modalities ?? []) {
    add(modality)
  }

  if (!normalized.length) {
    const pipeline = inferRunPipeline(plan)
    if (pipeline === 'glm' || pipeline === 'connectivity' || pipeline === 'preprocessing') {
      normalized.push('fmri')
    } else {
      normalized.push('general')
    }
  }

  return normalized
}

function buildCanonicalPlan(plan: Record<string, unknown>): PlannerPlan {
  const planParameters = safeRecord(plan.parameters) ?? {}
  const { templateId, analysisPresetId, pipelinePresetId } = resolvePlanTemplateIds(plan)
  const datasetId =
    normalizeId(plan.dataset_id) || normalizeId(planParameters.dataset_id) || undefined
  const fallbackTool =
    normalizeId(plan.tool) ||
    normalizeId(planParameters.tool) ||
    normalizeId(planParameters.tool_name) ||
    inferRunPipeline(plan) ||
    'dataset_analysis'
  const clientSteps = Array.isArray(plan.steps) ? plan.steps : []

  const steps: PlannerStepSpec[] =
    clientSteps.length > 0
      ? clientSteps.map((entry, index) => {
          const stepRecord = safeRecord(entry) ?? {}
          const stepArgs = safeRecord(stepRecord.args) ?? {}
          const stepMetadata = safeRecord(stepRecord.metadata) ?? {}
          return {
            id: normalizeId(stepRecord.id) || `step-${String(index + 1).padStart(3, '0')}`,
            tool: normalizeId(stepRecord.tool) || fallbackTool,
            consumes: {},
            produces: {},
            params: { ...stepArgs },
            metadata: {
              ...stepMetadata,
              ...(datasetId ? { dataset_id: datasetId } : {}),
              ...(templateId ? { template_id: templateId } : {}),
              ...(analysisPresetId ? { analysis_id: analysisPresetId } : {}),
              ...(pipelinePresetId ? { pipeline_id: pipelinePresetId } : {}),
              client_step_index: index,
            },
            runtime_kind: normalizePlannerRuntimeKind(stepRecord.runtime_kind ?? stepMetadata.runtime_kind),
          }
        })
      : [
          {
            id: 'step-001',
            tool: fallbackTool,
            consumes: {},
            produces: {},
            params: {
              ...planParameters,
              ...(datasetId ? { dataset_id: datasetId } : {}),
              ...(analysisPresetId ? { analysis_id: analysisPresetId } : {}),
              ...(pipelinePresetId ? { pipeline_id: pipelinePresetId } : {}),
              ...(templateId ? { template_id: templateId } : {}),
            },
            metadata: {
              ...(datasetId ? { dataset_id: datasetId } : {}),
              ...(templateId ? { template_id: templateId } : {}),
              ...(analysisPresetId ? { analysis_id: analysisPresetId } : {}),
              ...(pipelinePresetId ? { pipeline_id: pipelinePresetId } : {}),
              client_step_index: 0,
            },
            runtime_kind: 'container',
          },
        ]

  const planId =
    normalizeId(plan.plan_id) ||
    normalizeId(plan.analysis_id) ||
    `plan_${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}_${Math.random().toString(16).slice(2)}`}`

  return {
    plan_id: planId,
    version: 1,
    schema_version: '1.0',
    domain: 'neuroimaging',
    modality: inferPlannerModalities(plan),
    resolvable: true,
    dag: {
      steps,
      artifacts: [],
    },
    estimates: {},
    warnings: [],
    chosen_tool: steps[0]?.tool,
    selection_reason: 'web_ui_analysis_facade',
    planner_state: {
      source: 'web_ui_analysis_facade',
    },
  }
}

function extractCheckpointId(...sources: Array<Record<string, unknown> | null | undefined>): string | undefined {
  for (const source of sources) {
    if (!source) continue
    const checkpointId =
      normalizeId(source.checkpoint_id) ||
      normalizeId(source.checkpointId) ||
      normalizeId(source.resume_checkpoint_id) ||
      normalizeId(source.resumeCheckpointId)
    if (checkpointId) return checkpointId
  }
  return undefined
}

function buildAnalysisHandoffPack(
  plan: Record<string, unknown>,
  warnings: string[],
): Record<string, unknown> {
  const parameters = safeRecord(plan.parameters) ?? {}
  const steps = Array.isArray(plan.steps) ? plan.steps : []
  const firstStep = safeRecord(steps[0]) ?? {}
  const firstStepArgs = safeRecord(firstStep.args) ?? {}
  const chosenTool =
    normalizeId(firstStep.tool) ||
    normalizeId(parameters.tool) ||
    normalizeId(parameters.workflow_id) ||
    normalizeId(plan.pipeline)
  const workflowId =
    normalizeId(parameters.workflow_id) ||
    (chosenTool.startsWith('workflow_') ? chosenTool : '')
  const workflow = workflowId ? getWorkflowById(workflowId).workflow : null
  const workflowStepTools = (workflow?.runtime?.steps ?? [])
    .map((step) => normalizeId(step.tool))
    .filter(Boolean)
  const launchTrace = safeRecord(plan.launch_trace) ?? {}
  const preflightStatus = normalizeId(launchTrace.preflight_status)
  const preflightDetail = normalizeId(launchTrace.preflight_detail)
  const runtimeCheck = preflightStatus
    ? [
        {
          id: 'runtime_executable',
          label: 'Runtime executable',
          status: preflightStatus,
          ...(preflightDetail ? { detail: preflightDetail } : {}),
        },
      ]
    : []
  const inputs = {
    ...parameters,
    ...firstStepArgs,
    ...(normalizeId(plan.dataset_id) ? { dataset_id: normalizeId(plan.dataset_id) } : {}),
    ...(normalizeId(plan.dataset_version) ? { dataset_version: normalizeId(plan.dataset_version) } : {}),
  }
  const allowedTools =
    chosenTool && !chosenTool.startsWith('workflow_') ? [chosenTool] : []

  return buildPlannerHandoffPack({
    planId: normalizeId(plan.plan_id) || null,
    pipeline: normalizeId(plan.pipeline) || workflow?.stage || null,
    workflowId: workflow?.id || workflowId || null,
    chosenTool: chosenTool || null,
    datasetRef: normalizeId(plan.dataset_id) || normalizeId(parameters.dataset_id) || null,
    inputs,
    warnings,
    checks: runtimeCheck,
    allowedTools,
    approvalLevel: allowedTools.length ? 'confirm' : 'none',
    requiredTools: uniqueStrings([chosenTool, ...workflowStepTools]),
    targetRuntime: workflow?.primary_target ?? null,
    supportedRecipeTargets: workflow?.supported_recipe_targets ?? [],
    artifactContract: workflow?.artifact_contract ?? null,
    launchTrace,
    preflightStatus: preflightStatus || null,
    preflightDetail: preflightDetail || null,
  })
}

function launchUnavailableErrorForStatus(status: RecipeLaunchStatus): {
  error: string
  detail: string
} {
  if (status === 'manual_admin_only') {
    return {
      error: 'E-WORKFLOW-MANUAL-ADMIN-ONLY',
      detail:
        'This workflow is marked manual/admin only and cannot create a run from the web launch surface. Use the handoff pack instead.',
    }
  }
  return {
    error: 'E-WORKFLOW-HANDOFF-ONLY',
    detail:
      'This workflow does not advertise a launchable recipe in the current environment. Use the handoff pack instead.',
  }
}

function localBackendRequiredError(): {
  error: string
  detail: string
} {
  return {
    error: 'E-WORKFLOW-LOCAL-BACKEND-REQUIRED',
    detail:
      'Heavy workflow should run on a local backend using the generated MCP recipe. Hosted Brain Researcher will not create a normal hosted run for this workflow.',
  }
}

function attachWorkflowExecutionStatus(args: {
  plan: Record<string, unknown>
  recipeLaunchStatus: RecipeLaunchStatus | null
  runtimePreflightStatus?: LaunchPreflightResult['status'] | null
  workflow?: WorkflowDetail | null
}): WorkflowExecutionStatus {
  const handoffPack = safeRecord(args.plan.handoff_pack)
  const handoffExecution = safeRecord(handoffPack?.execution)
  const supportedTargets = uniqueStrings([
    ...(args.workflow?.supported_recipe_targets ?? []),
    ...((Array.isArray(handoffExecution?.supported_recipe_targets)
      ? handoffExecution?.supported_recipe_targets
      : []) as unknown[]),
  ])
  const executionStatus = buildWorkflowExecutionStatus({
    recipeLaunchStatus: args.recipeLaunchStatus,
    runtimePreflightStatus: args.runtimePreflightStatus ?? null,
    supportedTargets,
    recipeGenerated: Boolean(supportedTargets.length || safeRecord(handoffPack?.recipe_lookup)),
    hostedCanLaunch: args.runtimePreflightStatus === 'passed',
  })
  args.plan.execution_status = executionStatus
  if (handoffPack) {
    handoffPack.execution_status = executionStatus
    args.plan.handoff_pack = handoffPack
  }
  return executionStatus
}

function buildOrchestratorRunPayload(
  plan: Record<string, unknown>,
  projectId: string,
  threadId: string | null,
  checkpointId?: string | null,
) {
  const canonicalPlan = buildCanonicalPlan(plan)
  const planParameters = { ...(safeRecord(plan.parameters) ?? {}) }
  const launchTrace = safeRecord(plan.launch_trace)
  const handoffPack = safeRecord(plan.handoff_pack) ?? safeRecord(plan.handoff)
  const executionStatus = safeRecord(plan.execution_status)
  const parameterCheckpointId = extractCheckpointId(planParameters)
  planParameters.resume_checkpoint_id = undefined
  planParameters.resumeCheckpointId = undefined
  planParameters.checkpointId = undefined
  const resolvedCheckpointId = checkpointId || parameterCheckpointId
  if (resolvedCheckpointId) {
    planParameters.checkpoint_id = resolvedCheckpointId
  } else {
    planParameters.checkpoint_id = undefined
  }
  const prompt =
    firstNonEmptyText(plan.prompt, plan.intent, canonicalPlan.chosen_tool) || 'Analysis request'
  const datasetId =
    normalizeId(plan.dataset_id) || normalizeId(planParameters.dataset_id) || undefined
  const scenarioId =
    normalizeId(plan.scenario_id) ||
    normalizeId(plan.scenarioId) ||
    normalizeId(planParameters.scenario_id) ||
    undefined
  const attachments = Array.isArray(plan.attachments) ? plan.attachments : []
  const copilot = plan.copilot === true || planParameters.copilot === true

  return {
    prompt,
    pipeline: inferRunPipeline(plan),
    ...(datasetId ? { dataset_id: datasetId } : {}),
    project_id: projectId,
    ...(copilot ? { copilot: true } : {}),
    ...(attachments.length ? { attachments } : {}),
    parameters: {
      ...planParameters,
      _client_metadata: {
        plan_envelope: plan,
        canonical_plan: canonicalPlan,
        ...(launchTrace ? { launch_trace: launchTrace } : {}),
        ...(handoffPack ? { handoff_pack: handoffPack } : {}),
        ...(executionStatus ? { execution_status: executionStatus } : {}),
      },
    },
    ...(threadId ? { thread_id: threadId } : {}),
    ...(resolvedCheckpointId ? { checkpoint_id: resolvedCheckpointId } : {}),
    ...(scenarioId ? { scenario_id: scenarioId } : {}),
    ...(firstNonEmptyText(plan.intent, prompt) ? { intent: firstNonEmptyText(plan.intent, prompt) } : {}),
  }
}

function deriveSummary(record: OrchestratorAnalysisRecord): AnalysisSummary | null {
  const analysisId = normalizeId(record.analysis_id ?? record.job_id ?? record.run_id)
  if (!analysisId) return null

  const datasetId =
    normalizeId(record.dataset?.dataset_id) || normalizeId(record.dataset_id) || undefined
  const projectId = normalizeId(record.project_id) || 'default'

  const analysisPresetId =
    normalizeId(record.template?.analysis_id) || normalizeId(record.analysis_preset_id)
  const pipelinePresetId =
    normalizeId(record.template?.pipeline_id) || normalizeId(record.pipeline_preset_id)
  const templateId =
    normalizeId(record.template?.template_id) ||
    normalizeId(record.template_id) ||
    (analysisPresetId && pipelinePresetId ? `${analysisPresetId}/${pipelinePresetId}` : undefined)

  const dataset = datasetId ? getDataset(datasetId) : null

  const templateName = (() => {
    if (typeof record.template?.name === 'string' && record.template.name.trim()) {
      return record.template.name.trim()
    }
    if (!analysisPresetId || !pipelinePresetId) return undefined
    const { analysis, pipeline } = findAnalysisAndPipeline(analysisPresetId, pipelinePresetId)
    if (!analysis || !pipeline) return undefined
    return `${analysis.label} · ${pipeline.label}`
  })()

  const title =
    firstNonEmptyText(record.title, templateName) || `Analysis ${analysisId.slice(0, 8)}`

  return {
    analysis_id: analysisId,
    run_id: normalizeId(record.run_id) || analysisId,
    job_id: normalizeId(record.job_id) || analysisId,
    thread_id: normalizeId(record.thread_id) || null,
    project_id: projectId,
    status: normalizeStatus(record.status ?? record.state),
    created_at: toEpochSeconds(record.created_at),
    started_at: toEpochSeconds(record.started_at),
    finished_at: toEpochSeconds(record.finished_at),
    title,
    dataset:
      record.dataset?.dataset_id || record.dataset?.name || record.dataset?.source
        ? {
            dataset_id: record.dataset?.dataset_id || dataset?.id || datasetId,
            name: record.dataset?.name || dataset?.name,
            source: record.dataset?.source || dataset?.source_repo,
          }
        : dataset
          ? { dataset_id: dataset.id, name: dataset.name, source: dataset.source_repo }
          : datasetId
            ? { dataset_id: datasetId }
            : undefined,
    template: templateId
      ? {
          template_id: templateId,
          analysis_id: analysisPresetId,
          pipeline_id: pipelinePresetId,
          name: templateName,
        }
      : undefined,
    has_results: typeof record.has_results === 'boolean' ? record.has_results : undefined,
  }
}

export async function GET(req: NextRequest) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
  }

  const limit = clamp(Number(req.nextUrl.searchParams.get('limit')) || 50, 1, 250)
  const projectId = normalizeId(req.nextUrl.searchParams.get('project_id')) || ''
  const includeId = normalizeId(req.nextUrl.searchParams.get('include_id')) || ''

  const headers = forwardAuthHeaders(req)
  const query = new URLSearchParams({ limit: String(limit) })
  if (projectId) query.set('project_id', projectId)
  if (includeId) query.set('include_id', includeId)

  let upstream: Response
  try {
    upstream = await fetchWithRetry(
      `${resolveOrchestratorBaseUrl()}/api/analyses?${query.toString()}`,
      {
        method: 'GET',
        headers,
        cache: 'no-store',
      },
    )
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to list analyses' },
      { status: 503 },
    )
  }

  const raw = await upstream.text()
  if (!upstream.ok) {
    return new NextResponse(raw, {
      status: upstream.status,
      headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' },
    })
  }

  let parsed: OrchestratorAnalysesListResponse
  try {
    parsed = JSON.parse(raw) as OrchestratorAnalysesListResponse
  } catch {
    return NextResponse.json(
      { error: 'E-UPSTREAM-PARSE', detail: 'Upstream returned invalid JSON' },
      { status: 502 },
    )
  }

  const items: AnalysisSummary[] = []
  for (const record of parsed.items ?? []) {
    const summary = deriveSummary(record)
    if (summary) items.push(summary)
  }

  const response: AnalysesListResponse = {
    items,
    count: typeof parsed.count === 'number' ? parsed.count : items.length,
    next_cursor: null,
  }
  return NextResponse.json(response)
}

export async function POST(req: NextRequest) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
  }

  let bodyRaw: unknown
  try {
    bodyRaw = await req.json()
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON payload.' }, { status: 400 })
  }

  const body = safeRecord(bodyRaw) ?? {}
  const warnings: string[] = []

  const datasetId = normalizeId(body.dataset_id)
  const datasetVersion = normalizeId(body.dataset_version)
  const requestedProjectId = normalizeId(body.project_id)
  const projectId = requestedProjectId || 'default'
  const promptOverride = normalizeId(body.prompt)
  const titleOverride = normalizeId(body.title)
  const conceptIds = normalizeConceptIds(body.concept_ids ?? body.concepts)

  const threadPayload = safeRecord(body.thread)
  const threadModeRaw = normalizeId(threadPayload?.mode)
  const threadIdFromClient = normalizeId(threadPayload?.thread_id)

  const threadIdCandidate: string | null | { error: string } = (() => {
    if (threadModeRaw === 'none') return null
    if (threadModeRaw === 'reuse') {
      if (!threadIdFromClient) {
        return { error: 'thread.thread_id is required when thread.mode=reuse' }
      }
      return threadIdFromClient
    }
    const uuid =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    return uuid
  })()

  if (
    typeof threadIdCandidate === 'object' &&
    threadIdCandidate &&
    'error' in threadIdCandidate
  ) {
    return NextResponse.json({ detail: threadIdCandidate.error }, { status: 400 })
  }
  const threadIdToUse: string | null =
    typeof threadIdCandidate === 'string' ? threadIdCandidate : null

  const explicitPlan = safeRecord(body.plan)
  const checkpointId = extractCheckpointId(
    body,
    safeRecord(body.parameters),
    threadPayload,
    explicitPlan,
    safeRecord(explicitPlan?.parameters),
  )

  let plan: Record<string, unknown> | null = null
  let planDataset: DatasetDetailResponse | null = null
  let estimatedCredits: number | null = null
  let launchPreflightPayload: Record<string, unknown> | null = null
  let createsExecutableRun = false
  let recipeLaunchStatus: RecipeLaunchStatus | null = null
  let workflowForExecutionStatus: WorkflowDetail | null = null
  let runtimePreflightStatus: LaunchPreflightResult['status'] | null = null

  if (explicitPlan) {
    const clonedPlan: Record<string, unknown> = { ...explicitPlan }
    if (conceptIds.length) {
      const existingPrompt = typeof clonedPlan.prompt === 'string' ? clonedPlan.prompt : ''
      const basePrompt = existingPrompt.trim() ? existingPrompt : promptOverride
      if (basePrompt) {
        clonedPlan.prompt = appendConceptContext(basePrompt, conceptIds)
      }
    }
    clonedPlan.project_id =
      requestedProjectId ||
      (typeof clonedPlan.project_id === 'string' && clonedPlan.project_id.trim()
        ? clonedPlan.project_id.trim()
        : projectId)
    clonedPlan.launch_trace = {
      requested_analysis_id: normalizeId(body.analysis_id) || null,
      requested_pipeline_id: normalizeId(body.pipeline_id) || null,
      requested_template_id: normalizeId(body.template_id) || null,
      canonical_analysis_id: normalizeId(clonedPlan.analysis_id) || null,
      canonical_pipeline_id: normalizeId(clonedPlan.pipeline_id) || null,
      canonical_template_id: normalizeId(clonedPlan.template_id) || null,
      canonicalized: false,
      dataset_id: datasetId || normalizeId(clonedPlan.dataset_id) || null,
      template_source: 'explicit_plan',
      workflow_found: null,
    }
    const explicitWorkflow = resolveExplicitPlanWorkflow(clonedPlan)
    if (explicitWorkflow) {
      workflowForExecutionStatus = explicitWorkflow
      recipeLaunchStatus = deriveRecipeLaunchStatus(explicitWorkflow)
      createsExecutableRun = recipeLaunchStatus === 'launchable'
      estimatedCredits = estimateCreditsFromRuntime(
        runtimeEstimateForToolId(explicitWorkflow.id, explicitWorkflow.est_runtime),
        { variantsMultiplier: variantsMultiplierFromPlan(clonedPlan) },
      )
      const existingTrace = safeRecord(clonedPlan.launch_trace) ?? {}
      clonedPlan.launch_trace = {
        ...existingTrace,
        canonical_analysis_id:
          normalizeId(existingTrace.canonical_analysis_id) ||
          normalizeId(clonedPlan.analysis_id) ||
          'dynamic_workflow',
        canonical_pipeline_id:
          normalizeId(existingTrace.canonical_pipeline_id) || explicitWorkflow.id,
        canonical_template_id:
          normalizeId(existingTrace.canonical_template_id) ||
          `dynamic_workflow/${explicitWorkflow.id}`,
        template_source: 'workflow_catalog',
        workflow_found: true,
        launch_status: recipeLaunchStatus,
      }
    }
    plan = clonedPlan
  } else {
    const template = parseTemplateIds(body)
    if (!template) {
      return NextResponse.json(
        {
          detail:
            'Provide either plan (object) or template_id (analysis_id/pipeline_id) along with dataset_id.',
        },
        { status: 400 },
      )
    }
    if (!datasetId) {
      return NextResponse.json({ detail: 'dataset_id is required.' }, { status: 400 })
    }

    const datasetFromCatalog = getDataset(datasetId)
    const datasetFromApi = datasetFromCatalog ? null : await fetchDatasetDetail(req, datasetId)
    const dataset = datasetFromCatalog ?? datasetFromApi
    if (!dataset) {
      warnings.push(`Dataset ${datasetId} was not found in the local catalog.`)
    } else if (datasetFromApi) {
      warnings.push(`Dataset ${datasetId} resolved via API catalog lookup.`)
    }

    const { analysis, pipeline } = findAnalysisAndPipeline(template.analysisId, template.pipelineId)
    const dynamicWorkflow =
      template.analysisId === 'dynamic_workflow'
        ? getWorkflowById(template.pipelineId).workflow
        : null
    const launchTraceBase = {
      requested_analysis_id: template.requestedAnalysisId || null,
      requested_pipeline_id: template.requestedPipelineId || null,
      requested_template_id: template.requestedTemplateId || null,
      canonical_analysis_id: template.analysisId,
      canonical_pipeline_id: template.pipelineId,
      canonical_template_id: template.templateId,
      canonicalized: template.canonicalized,
      canonicalization_reason: template.canonicalizationReason || null,
      dataset_id: datasetId || null,
      template_source: dynamicWorkflow
        ? 'workflow_catalog'
        : analysis && pipeline
          ? 'analysis_preset'
          : 'unknown',
      workflow_found:
        template.analysisId === 'dynamic_workflow' ? Boolean(dynamicWorkflow) : null,
    }

    const extraParams =
      safeRecord(body.parameters) ?? safeRecord((body as Record<string, unknown>).params)

    if (!analysis || !pipeline) {
      if (!dynamicWorkflow) {
        return NextResponse.json({ detail: 'Unknown analysis template.' }, { status: 400 })
      }

      if (
        dataset &&
        !datasetSupportsModalities(dataset, dynamicWorkflow.modalities ?? [])
      ) {
        return NextResponse.json(
          {
            detail: `Template dynamic_workflow/${dynamicWorkflow.id} requires ${
              (dynamicWorkflow.modalities ?? []).length
                ? (dynamicWorkflow.modalities ?? []).join(', ')
                : 'specific'
            } modalities, but dataset ${dataset.id} only reports ${(dataset.modalities ?? []).join(', ') || 'none'}.`,
          },
          { status: 400 },
        )
      }

      const safeDataset: DatasetDetailResponse =
        dataset ?? buildFallbackDataset(datasetId, dynamicWorkflow.modalities ?? [])
      workflowForExecutionStatus = dynamicWorkflow
      planDataset = safeDataset
      const parameters = buildDynamicWorkflowParameters(
        safeDataset,
        dynamicWorkflow,
        extraParams,
      )
      recipeLaunchStatus = deriveRecipeLaunchStatus(dynamicWorkflow)
      createsExecutableRun = recipeLaunchStatus === 'launchable'
      const variantsMultiplier =
        template.analysisId === 'multiverse_glm' &&
        typeof parameters.max_models === 'number' &&
        Number.isFinite(parameters.max_models)
          ? Math.max(1, Math.floor(parameters.max_models))
          : 1
      estimatedCredits = estimateCreditsFromRuntime(
        runtimeEstimateForToolId(dynamicWorkflow.id, dynamicWorkflow.est_runtime),
        { variantsMultiplier },
      )
      const prompt = appendConceptContext(
        promptOverride ||
          buildDynamicWorkflowPrompt(
            safeDataset,
            dynamicWorkflow,
            datasetVersion || undefined,
          ),
        conceptIds,
      )
      const intent = titleOverride || `Dynamic Workflow · ${dynamicWorkflow.description || dynamicWorkflow.id}`
      const templateId = `dynamic_workflow/${dynamicWorkflow.id}`

      plan = {
        type: 'dataset_analysis',
        prompt,
        pipeline: 'preprocessing',
        project_id: projectId,
        dataset_id: safeDataset.id,
        launch_trace: {
          ...launchTraceBase,
          workflow_found: true,
          launch_status: recipeLaunchStatus,
        },
        ...(datasetVersion ? { dataset_version: datasetVersion } : {}),
        template_id: templateId,
        parameters,
        intent,
        steps: [
          {
            tool: dynamicWorkflow.id,
            runtime_kind: workflowPlannerRuntimeKind(dynamicWorkflow),
            args: {
              dataset_id: safeDataset.id,
              ...(datasetVersion ? { dataset_version: datasetVersion } : {}),
              analysis_id: 'dynamic_workflow',
              pipeline_id: dynamicWorkflow.id,
              ...parameters,
            },
          },
        ],
      }
      launchPreflightPayload = { workflow_id: dynamicWorkflow.id }
    } else {
      if (!pipeline.runConfig) {
        return NextResponse.json({ detail: 'Template is missing execution metadata.' }, { status: 500 })
      }
      if (dataset && !datasetSupportsPipeline(dataset, pipeline)) {
        return NextResponse.json(
          {
            detail: `Template ${template.templateId} requires ${
              pipeline.modalities.length ? pipeline.modalities.join(', ') : 'specific'
            } modalities, but dataset ${dataset.id} only reports ${dataset.modalities.join(', ') || 'none'}.`,
          },
          { status: 400 },
        )
      }

      const safeDataset: DatasetDetailResponse =
        dataset ?? buildFallbackDataset(datasetId, pipeline.modalities.length ? [...pipeline.modalities] : [])
      planDataset = safeDataset
      const toolId = normalizePipelineToolId(
        analysis.id,
        pipeline.id,
        pipeline.runConfig.tool,
      )
      const parameters = buildParameters(safeDataset, analysis, pipeline, extraParams)
      createsExecutableRun = true
      const variantsMultiplier =
        analysis.id === 'multiverse_glm' &&
        typeof parameters.max_models === 'number' &&
        Number.isFinite(parameters.max_models)
          ? Math.max(1, Math.floor(parameters.max_models))
          : 1
      estimatedCredits = estimateCreditsFromRuntime(
        runtimeEstimateForToolId(toolId, pipeline.estRuntime),
        { variantsMultiplier },
      )

      const prompt = appendConceptContext(
        promptOverride ||
          buildPrompt(safeDataset, analysis, pipeline, datasetVersion || undefined),
        conceptIds,
      )
      const intent = titleOverride || `${analysis.label} · ${pipeline.label}`

      plan = {
        type: 'dataset_analysis',
        prompt,
        pipeline: pipeline.runConfig.pipelineType,
        project_id: projectId,
        dataset_id: safeDataset.id,
        launch_trace: launchTraceBase,
        ...(datasetVersion ? { dataset_version: datasetVersion } : {}),
        template_id: template.templateId,
        parameters,
        intent,
        steps: [
          {
            tool: toolId || 'dataset_analyze',
            args: {
              dataset_id: safeDataset.id,
              ...(datasetVersion ? { dataset_version: datasetVersion } : {}),
              analysis_id: analysis.id,
              pipeline_id: pipeline.id,
              ...parameters,
            },
          },
        ],
      }
      launchPreflightPayload = null
    }
  }

  const isE2eRequest =
    process.env.NODE_ENV !== 'production' && req.cookies.get('br_e2e_auth')?.value === '1'
  if (plan && isE2eRequest) {
    plan['e2e'] = true
  }
  if (plan) {
    plan.project_id = normalizeId(plan['project_id']) || projectId
  }

  await hydratePlanBoldInputs(req, plan, planDataset)

  const planInputError = planInputValidationErrorForExecution(plan)
  if (planInputError) {
    return NextResponse.json({ detail: planInputError }, { status: 400 })
  }

  if (
    recipeLaunchStatus &&
    recipeLaunchStatus !== 'launchable' &&
    plan
  ) {
    const existingTrace = safeRecord(plan.launch_trace) ?? {}
    plan.launch_trace = {
      ...existingTrace,
      launch_status: recipeLaunchStatus,
    }
    const handoffPack = buildAnalysisHandoffPack(plan, warnings)
    plan.handoff_pack = handoffPack
    const executionStatus = attachWorkflowExecutionStatus({
      plan,
      recipeLaunchStatus,
      runtimePreflightStatus,
      workflow: workflowForExecutionStatus,
    })
    const error = launchUnavailableErrorForStatus(recipeLaunchStatus)
    return NextResponse.json(
      {
        ...error,
        launch_trace: plan.launch_trace,
        handoff_pack: handoffPack,
        execution_status: executionStatus,
      },
      { status: 409 },
    )
  }

  if (
    plan &&
    recipeLaunchStatus === 'launchable' &&
    workflowTargetsRequireLocalBackend(workflowForExecutionStatus?.supported_recipe_targets)
  ) {
    const existingTrace = safeRecord(plan.launch_trace) ?? {}
    plan.launch_trace = {
      ...existingTrace,
      launch_status: recipeLaunchStatus,
      hosted_launch_status: 'local_backend_required',
    }
    const handoffPack = buildAnalysisHandoffPack(plan, warnings)
    plan.handoff_pack = handoffPack
    const executionStatus = attachWorkflowExecutionStatus({
      plan,
      recipeLaunchStatus,
      runtimePreflightStatus,
      workflow: workflowForExecutionStatus,
    })
    const error = localBackendRequiredError()
    return NextResponse.json(
      {
        ...error,
        launch_trace: plan.launch_trace,
        handoff_pack: handoffPack,
        execution_status: executionStatus,
      },
      { status: 409 },
    )
  }

  if (plan && launchPreflightPayload) {
    const preflight = await runLaunchPreflight(req, launchPreflightPayload)
    runtimePreflightStatus = preflight.status
    const existingTrace = safeRecord(plan.launch_trace) ?? {}
    plan.launch_trace = {
      ...existingTrace,
      preflight_status: preflight.status,
      ...(preflight.detail ? { preflight_detail: preflight.detail } : {}),
    }
    if (preflight.status === 'blocked') {
      const handoffPack = buildAnalysisHandoffPack(plan, warnings)
      plan.handoff_pack = handoffPack
      const executionStatus = attachWorkflowExecutionStatus({
        plan,
        recipeLaunchStatus,
        runtimePreflightStatus,
        workflow: workflowForExecutionStatus,
      })
      return NextResponse.json(
        {
          error: 'E-LAUNCH-PREFLIGHT-BLOCKED',
          detail: preflight.detail || 'Runtime preflight blocked this workflow.',
          launch_trace: plan.launch_trace,
          handoff_pack: handoffPack,
          execution_status: executionStatus,
        },
        { status: 409 },
      )
    }
    if (preflight.status === 'warning' && preflight.detail) {
      warnings.push(preflight.detail)
    }
  }

  if (plan) {
    plan.handoff_pack = buildAnalysisHandoffPack(plan, warnings)
    attachWorkflowExecutionStatus({
      plan,
      recipeLaunchStatus,
      runtimePreflightStatus,
      workflow: workflowForExecutionStatus,
    })
  }

  if (
    CREDITS_ENFORCEMENT_ENABLED &&
    createsExecutableRun &&
    estimatedCredits == null
  ) {
    const handoffPack = safeRecord(plan?.handoff_pack) ?? undefined
    const launchTrace = safeRecord(plan?.launch_trace) ?? undefined
    const executionStatus = safeRecord(plan?.execution_status) ?? undefined
    return NextResponse.json(
      {
        error: 'E-CREDIT-ESTIMATE-UNAVAILABLE',
        detail:
          'Credit estimate unavailable for this launchable workflow; run creation is blocked until this pipeline has an estimate or is marked handoff-only.',
        ...(launchTrace ? { launch_trace: launchTrace } : {}),
        ...(handoffPack ? { handoff_pack: handoffPack } : {}),
        ...(executionStatus ? { execution_status: executionStatus } : {}),
      },
      { status: 409 },
    )
  }

  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  let reservationId: string | null = null
  if (CREDITS_ENFORCEMENT_ENABLED && estimatedCredits != null && estimatedCredits > 0) {
    const identity = await resolveCreditsIdentity(req)
    const reservation = await reserveCredits(req, identity, estimatedCredits, {
      source: 'analyses.create',
      project_id: projectId,
      dataset_id: datasetId || null,
      analysis_id: normalizeId(body.analysis_id) || null,
      pipeline_id: normalizeId(body.pipeline_id) || null,
    })
    if ('status' in reservation) {
      if (reservation.status === 402) {
        return NextResponse.json(
          { detail: reservation.detail || 'Insufficient credits.' },
          { status: 402 },
        )
      }
      warnings.push(
        `Credits reservation unavailable (${reservation.status}); proceeding without enforcement.`,
      )
    } else {
      reservationId = reservation.reservation.reservation_id
    }
  }

  let upstream: Response
  const orchestratorPayload = buildOrchestratorRunPayload(
    plan,
    projectId,
    threadIdToUse,
    checkpointId,
  )
  try {
    upstream = await fetch(`${resolveOrchestratorBaseUrl()}/run`, {
      method: 'POST',
      headers,
      body: JSON.stringify(orchestratorPayload),
      cache: 'no-store',
    })
  } catch {
    if (reservationId) {
      await releaseCreditsReservation(req, reservationId, {
        reason: 'run_create_transport_failure',
      })
    }
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to create analysis' },
      { status: 503 },
    )
  }

  const raw = await upstream.text()
  let parsed: OrchestratorRunResponse | null = null
  try {
    parsed = raw ? (JSON.parse(raw) as OrchestratorRunResponse) : null
  } catch {
    parsed = null
  }

  if (!upstream.ok) {
    if (reservationId) {
      await releaseCreditsReservation(req, reservationId, {
        reason: 'run_create_upstream_rejected',
      })
    }
    const failureTrace = {
      ...(safeRecord(plan?.launch_trace) ?? {}),
      upstream_status: upstream.status,
      upstream_rejected: true,
    }
    const failureHandoff = safeRecord(plan?.handoff_pack) ?? undefined
    const failureExecutionStatus = safeRecord(plan?.execution_status) ?? undefined
    if (parsed && typeof parsed === 'object') {
      const errorBody = parsed as any
      const detail = errorBody?.detail || errorBody?.error || 'Failed to create analysis.'
      return NextResponse.json(
        {
          detail,
          launch_trace: failureTrace,
          ...(failureHandoff ? { handoff_pack: failureHandoff } : {}),
          ...(failureExecutionStatus ? { execution_status: failureExecutionStatus } : {}),
        },
        { status: upstream.status },
      )
    }
    return NextResponse.json(
      {
        detail: raw || 'Failed to create analysis.',
        launch_trace: failureTrace,
        ...(failureHandoff ? { handoff_pack: failureHandoff } : {}),
        ...(failureExecutionStatus ? { execution_status: failureExecutionStatus } : {}),
      },
      { status: upstream.status },
    )
  }

  const analysisId = normalizeId(parsed?.analysis_id ?? parsed?.job_id)
  if (!analysisId) {
    warnings.push('Upstream did not return analysis_id/job_id; analysis_id may be unavailable.')
  }

  if (reservationId) {
    const committed = await commitCreditsReservation(req, reservationId, {
      run_id: analysisId || null,
      source: 'analyses.create',
    })
    if (!committed) {
      warnings.push('Credits commit failed; reservation was released.')
      await releaseCreditsReservation(req, reservationId, {
        reason: 'commit_failed_release',
        run_id: analysisId || null,
      })
    }
  }

  const response: AnalysisCreateResponse = {
    analysis_id: analysisId,
    run_id: normalizeId(parsed?.job_id) || analysisId || undefined,
    job_id: normalizeId(parsed?.job_id) || analysisId || undefined,
    thread_id: threadIdToUse ? String(threadIdToUse) : null,
    status: normalizeStatus(parsed?.status ?? 'queued'),
    created_at: parsed?.created_at ?? null,
    links: analysisId
      ? {
          analysis:
            firstNonEmptyText(parsed?.analysis_url) ||
            `/api/analyses/${encodeURIComponent(analysisId)}`,
          stream:
            firstNonEmptyText(parsed?.analysis_stream_url) ||
            `/api/analyses/${encodeURIComponent(analysisId)}/stream`,
        }
      : undefined,
    warnings: warnings.length ? warnings : undefined,
    handoff_pack: safeRecord(plan?.handoff_pack) ?? undefined,
    execution_status: (safeRecord(plan?.execution_status) ?? undefined) as
      | WorkflowExecutionStatus
      | undefined,
  }

  return NextResponse.json(response, { status: 201 })
}
