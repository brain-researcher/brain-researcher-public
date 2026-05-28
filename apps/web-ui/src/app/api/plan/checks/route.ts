import { NextRequest, NextResponse } from 'next/server'

import { GET as getDatasetResources } from '@/app/api/catalog/datasets/[datasetId]/resources/route'
import { ANALYSIS_TYPES, AnalysisType, PipelineOption } from '@/config/analysis-presets'
import type { WorkflowDetail } from '@/lib/api/workflows'
import {
  inferBoldImgPathFromBidsDir,
  resolveDefaultBidsRunHints,
} from '@/lib/server/bids-defaults'
import { getDataset } from '@/lib/server/dataset-catalog'
import {
  estimateCreditsFromRuntime,
  getCreditsBalance,
  resolveCreditsIdentity,
} from '@/lib/server/credits'
import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import {
  buildPlannerHandoffPack,
  type PlannerHandoffPack,
} from '@/lib/launch-handoff-pack'
import { buildLatestPlanContinuationPrompt } from '@/lib/mcp-plan-handoff'
import {
  buildMcpRecipeCallText,
  selectMcpRecipeTarget,
} from '@/lib/mcp-recipe-handoff'
import {
  deriveRecipeLaunchStatus,
  deriveLaunchDecision,
  guidanceRequiresHandoff,
  type LaunchDecision,
  type RecipeLaunchStatus,
} from '@/lib/server/launch-decision'
import {
  buildWorkflowExecutionStatus,
  type WorkflowExecutionStatus,
} from '@/lib/server/workflow-execution-status'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { canonicalizeTemplateSelection } from '@/lib/workflow-template-aliases'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

type PlanCheckStatus = 'pending' | 'passed' | 'warning' | 'blocked'

type PlanCheck = {
  id: string
  label: string
  status: PlanCheckStatus
  detail?: string
}

type PlanChecksResponse = {
  checks: PlanCheck[]
  launch_decision: LaunchDecision
  capability: WorkflowCapabilityContract
  execution_status: WorkflowExecutionStatus
  estimate?: {
    runtime?: string
    credits?: number | null
  }
  context?: {
    dataset_version?: string
  }
  effective_config?: EffectiveRunConfig
  guidance?: EnvironmentSetupGuidance | null
  handoff_pack?: PlannerHandoffPack
}

type WorkflowCapabilityContract = {
  schema_version: 'br-workflow-capability-v1'
  canonical_workflow_id: string | null
  hosted_launch: {
    status: LaunchDecision['status']
    code: LaunchDecision['code']
    can_launch: boolean
    primary_action: LaunchDecision['primary_action']
    reason: string
  }
  mcp_recipe: {
    status: 'available' | 'unavailable' | 'manual_admin_only'
    supported_targets: string[]
    preferred_target: string | null
    recipe_call: string | null
    handoff_prompt: string
  }
  unsupported_reasons: string[]
  credits: {
    status: PlanCheckStatus | 'unknown'
    detail?: string
    estimated_credits?: number | null
  }
  dataset_readiness: {
    status: PlanCheckStatus | 'unknown'
    detail?: string
  }
  execution_status: WorkflowExecutionStatus
}

type ParameterOrigin = 'base' | 'default' | 'user' | 'inferred'

type EffectiveRunConfigEntry = {
  key: string
  origin: ParameterOrigin
  value: unknown
}

type EffectiveRunConfig = {
  analysis_id: string
  pipeline_id: string
  pipeline_label?: string
  pipeline_type?: string
  tool_id: string
  dataset_id: string
  dataset_version?: string
  parameters: EffectiveRunConfigEntry[]
  parameter_values: Record<string, unknown>
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
  guidance?: EnvironmentSetupGuidance | null
}

type EnvironmentSetupAction = {
  id?: string
  label?: string
  href?: string
  external?: boolean
}

type EnvironmentSetupGuidance = {
  kind?: string
  access_mode?: string
  runtime_target?: string
  install_path?: string
  summary?: string
  detail?: string | null
  next_action_url?: string | null
  docs_urls?: string[]
  required_modules?: string[]
  required_env_vars?: string[]
  container_images?: Record<string, string>
  supported_recipe_targets?: string[]
  workflow_id?: string | null
  actions?: EnvironmentSetupAction[]
}

type ResourcesReadinessPayload = {
  readiness?: {
    status?: string
    reason?: string
    local_path_available?: boolean
  }
  required_files?: {
    all_required_passed?: boolean
  }
  source_access?: {
    bucket_check?: {
      state?: string
      message?: string
    }
  }
  unavailable?: boolean
  error?: string
}

const RESOURCES_FETCH_TIMEOUT_MS = 2500
const READINESS_WARNING_FALLBACK_DETAIL =
  'We could not confirm underlying file accessibility. You can continue, but the run may fail at runtime if required data is missing.'

const CONNECTIVITY_KIND_MAP: Record<string, string> = {
  correlation: 'correlation',
  partialcorrelation: 'partial correlation',
  tangent: 'tangent',
  covariance: 'covariance',
  precision: 'precision',
}

const SENSITIVE_PARAM_KEY_PATTERN =
  /(token|secret|password|passwd|api[_-]?key|authorization|cookie|credential|private[_-]?key)/i

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function normalizeTaskLabel(task: string) {
  return task.trim().toLowerCase().replace(/[^a-z0-9]+/g, '')
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

function canonicalWorkflowIdForLaunchPolicy(
  analysisId: string,
  pipelineId: string,
  toolId: string,
): string | null {
  const normalizedToolId = normalizePipelineToolId(analysisId, pipelineId, toolId)
  if (normalizedToolId.startsWith('workflow_')) return normalizedToolId

  if (analysisId === 'preprocess') {
    if (pipelineId === 'fmriprep') return 'workflow_fmriprep_preprocessing'
    if (pipelineId === 'mriqc') return 'workflow_mriqc'
    if (pipelineId === 'qsiprep') return 'workflow_qsiprep'
  }

  return null
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

function sanitizePathToken(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '')
}

function creditEstimateUnavailableDetail(recipeLaunchStatus: RecipeLaunchStatus | null): string {
  if (recipeLaunchStatus === 'manual_admin_only') {
    return 'Credit estimate unavailable for this manual/admin-only workflow; use handoff instead.'
  }
  if (recipeLaunchStatus === 'handoff_only') {
    return 'Credit estimate unavailable for this handoff-only workflow; proceed with caution.'
  }
  return 'Credit estimate unavailable for this launchable workflow; configure a runtime estimate or use handoff instead.'
}

function findPlanCheck(checks: PlanCheck[], id: string): PlanCheck | null {
  return checks.find((check) => check.id === id) ?? null
}

function buildUnsupportedReasons(args: {
  checks: PlanCheck[]
  guidance?: EnvironmentSetupGuidance | null
}): string[] {
  const reasons = new Set<string>()
  for (const check of args.checks) {
    if (check.status !== 'blocked' && check.status !== 'warning') continue
    const detail = check.detail?.trim()
    if (detail) reasons.add(`${check.label}: ${detail}`)
  }
  const guidance = args.guidance
  if (guidance?.summary?.trim()) reasons.add(guidance.summary.trim())
  if (guidance?.detail?.trim()) reasons.add(guidance.detail.trim())
  if (guidance?.required_env_vars?.length) {
    reasons.add(`Required env vars: ${guidance.required_env_vars.join(', ')}`)
  }
  return Array.from(reasons)
}

function buildWorkflowCapabilityContract(args: {
  checks: PlanCheck[]
  launchDecision: LaunchDecision
  recipeLaunchStatus: RecipeLaunchStatus | null
  runtimePreflightStatus: PlanCheckStatus | null
  workflow?: WorkflowDetail | null
  handoffPack: PlannerHandoffPack
  guidance?: EnvironmentSetupGuidance | null
  estimatedCredits?: number | null
  datasetId?: string | null
  datasetVersion?: string | null
}): WorkflowCapabilityContract {
  const supportedTargets = args.workflow?.supported_recipe_targets ?? []
  const recipeAvailable = supportedTargets.length > 0 && args.recipeLaunchStatus !== 'manual_admin_only'
  const preferredTarget = recipeAvailable
    ? selectMcpRecipeTarget({
        targetRuntime: args.workflow?.primary_target ?? args.handoffPack.recipe_lookup?.target_runtime,
        supportedTargets,
      })
    : null
  const workflowId = args.handoffPack.workflow_id || args.workflow?.id || null
  const recipeCall =
    recipeAvailable && workflowId
      ? buildMcpRecipeCallText({
          workflowId,
          targetRuntime: preferredTarget,
          supportedTargets,
          datasetId: args.datasetId ?? args.handoffPack.dataset_ref,
          params: args.handoffPack.recipe_lookup?.params,
        })
      : null
  const executionStatus = buildWorkflowExecutionStatus({
    recipeLaunchStatus: args.recipeLaunchStatus,
    runtimePreflightStatus: args.runtimePreflightStatus,
    supportedTargets,
    recipeCall,
    hostedCanLaunch: args.launchDecision.can_launch,
  })
  const handoffPrompt = buildLatestPlanContinuationPrompt({
    workflowLabel: workflowId,
    datasetId: args.datasetId ?? args.handoffPack.dataset_ref,
    datasetVersion: args.datasetVersion,
    handoffPack: args.handoffPack,
  })
  const creditCheck = findPlanCheck(args.checks, 'credits_sufficient')
  const datasetReadinessCheck =
    findPlanCheck(args.checks, 'data_validated') ||
    findPlanCheck(args.checks, 'resource_readiness') ||
    findPlanCheck(args.checks, 'dataset_ready')

  return {
    schema_version: 'br-workflow-capability-v1',
    canonical_workflow_id: workflowId,
    hosted_launch: {
      status: args.launchDecision.status,
      code: args.launchDecision.code,
      can_launch: args.launchDecision.can_launch,
      primary_action: args.launchDecision.primary_action,
      reason: args.launchDecision.reason,
    },
    mcp_recipe: {
      status:
        args.recipeLaunchStatus === 'manual_admin_only'
          ? 'manual_admin_only'
          : recipeAvailable
            ? 'available'
            : 'unavailable',
      supported_targets: supportedTargets,
      preferred_target: preferredTarget,
      recipe_call: recipeCall,
      handoff_prompt: handoffPrompt,
    },
    unsupported_reasons: buildUnsupportedReasons({
      checks: args.checks,
      guidance: args.guidance,
    }),
    credits: {
      status: creditCheck?.status ?? 'unknown',
      detail: creditCheck?.detail,
      estimated_credits: args.estimatedCredits ?? null,
    },
    dataset_readiness: {
      status: datasetReadinessCheck?.status ?? 'unknown',
      detail: datasetReadinessCheck?.detail,
    },
    execution_status: executionStatus,
  }
}

function resolveDatasetPathHints(dataset: {
  id: string
  primary_url?: string
}): {
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
    dataset: { id: string; primary_url?: string }
    analysisId: string
    pipelineId: string
    toolId: string
  },
): Record<string, unknown> {
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

function isConfiguredValue(value: unknown): boolean {
  if (value == null) return false
  if (typeof value === 'string') return value.trim().length > 0
  return true
}

function valuesEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true
  const leftPrimitive =
    left == null ||
    typeof left === 'string' ||
    typeof left === 'number' ||
    typeof left === 'boolean'
  const rightPrimitive =
    right == null ||
    typeof right === 'string' ||
    typeof right === 'number' ||
    typeof right === 'boolean'
  if (leftPrimitive || rightPrimitive) return false
  try {
    return JSON.stringify(left) === JSON.stringify(right)
  } catch {
    return false
  }
}

function isSensitiveKey(key: string): boolean {
  return SENSITIVE_PARAM_KEY_PATTERN.test(key)
}

function sanitizeValueByKey(key: string, value: unknown): unknown {
  if (!isSensitiveKey(key)) return value
  if (value == null) return value
  return '[redacted]'
}

function sanitizeEffectiveValue(key: string, value: unknown): unknown {
  const redacted = sanitizeValueByKey(key, value)
  if (redacted === '[redacted]') return redacted

  if (Array.isArray(value)) {
    return value.map((entry) => sanitizeEffectiveValue('', entry))
  }

  if (value && typeof value === 'object') {
    const nested: Record<string, unknown> = {}
    for (const [nestedKey, nestedValue] of Object.entries(value as Record<string, unknown>)) {
      nested[nestedKey] = sanitizeEffectiveValue(nestedKey, nestedValue)
    }
    return nested
  }

  return value
}

function sanitizeEffectiveValues(
  values: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values)) {
    out[key] = sanitizeEffectiveValue(key, value)
  }
  return out
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

function collectOriginsMap(
  base: Record<string, unknown>,
  defaults: Record<string, unknown>,
  user: Record<string, unknown>,
  effective: Record<string, unknown>,
): Record<string, ParameterOrigin> {
  const origins: Record<string, ParameterOrigin> = {}
  for (const key of Object.keys(effective)) {
    const userHasSameKey = Object.prototype.hasOwnProperty.call(user, key)
    const defaultHasSameKey = Object.prototype.hasOwnProperty.call(defaults, key)
    const baseHasSameKey = Object.prototype.hasOwnProperty.call(base, key)

    const userValue = userHasSameKey ? user[key] : undefined
    const defaultValue = defaultHasSameKey ? defaults[key] : undefined
    const baseValue = baseHasSameKey ? base[key] : undefined
    const effectiveValue = effective[key]

    const userAliasValue =
      key === 'atlas_name'
        ? user.atlas
        : key === 'connectivity_kind'
          ? user.connectivity_metric
          : key === 'smoothing_fwhm'
            ? user.smoothing
            : undefined

    if (
      userHasSameKey &&
      isConfiguredValue(userValue) &&
      valuesEqual(effectiveValue, userValue)
    ) {
      origins[key] = 'user'
    } else if (
      userAliasValue !== undefined &&
      isConfiguredValue(userAliasValue)
    ) {
      origins[key] = 'user'
    } else if (
      defaultHasSameKey &&
      isConfiguredValue(defaultValue) &&
      valuesEqual(effectiveValue, defaultValue)
    ) {
      origins[key] = 'default'
    } else if (baseHasSameKey && valuesEqual(effectiveValue, baseValue)) {
      origins[key] = 'base'
    } else {
      origins[key] = 'inferred'
    }
  }
  return origins
}

function toEffectiveConfigEntries(
  effective: Record<string, unknown>,
  origins: Record<string, ParameterOrigin>,
): EffectiveRunConfigEntry[] {
  return Object.keys(effective)
    .sort()
    .map((key) => ({
      key,
      value: sanitizeEffectiveValues({ [key]: effective[key] })[key],
      origin: origins[key] || 'inferred',
    }))
}

function buildStaticEffectiveConfig(args: {
  dataset: ReturnType<typeof getDataset>
  datasetVersion: string
  analysis: AnalysisType
  pipeline: PipelineOption
  userParameters: Record<string, unknown>
}): EffectiveRunConfig | null {
  const { dataset, datasetVersion, analysis, pipeline, userParameters } = args
  if (!dataset || !pipeline.runConfig) return null
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
  if (datasetVersion) base.dataset_version = datasetVersion

  const defaults = { ...(pipeline.runConfig.defaultParameters ?? {}) }
  const merged = {
    ...base,
    ...defaults,
    ...userParameters,
  }
  const effective = applyExecutionDefaults(merged, {
    dataset,
    analysisId: analysis.id,
    pipelineId: pipeline.id,
    toolId,
  })
  const origins = collectOriginsMap(base, defaults, userParameters, effective)

  return {
    analysis_id: analysis.id,
    pipeline_id: pipeline.id,
    pipeline_label: pipeline.label,
    pipeline_type: pipeline.runConfig.pipelineType,
    tool_id: toolId,
    dataset_id: dataset.id,
    dataset_version: datasetVersion || undefined,
    parameter_values: sanitizeEffectiveValues(effective),
    parameters: toEffectiveConfigEntries(effective, origins),
  }
}

function buildDynamicEffectiveConfig(args: {
  dataset: ReturnType<typeof getDataset>
  datasetVersion: string
  workflow: WorkflowDetail
  userParameters: Record<string, unknown>
}): EffectiveRunConfig | null {
  const { dataset, datasetVersion, workflow, userParameters } = args
  if (!dataset) return null
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
  if (datasetVersion) base.dataset_version = datasetVersion
  const defaults: Record<string, unknown> = {}
  const merged = {
    ...base,
    ...userParameters,
  }
  const effective = applyExecutionDefaults(merged, {
    dataset,
    analysisId: 'dynamic_workflow',
    pipelineId: workflow.id,
    toolId: workflow.id,
  })
  const origins = collectOriginsMap(base, defaults, userParameters, effective)
  return {
    analysis_id: 'dynamic_workflow',
    pipeline_id: workflow.id,
    pipeline_label: workflow.description || workflow.id,
    pipeline_type: 'dynamic_workflow',
    tool_id: workflow.id,
    dataset_id: dataset.id,
    dataset_version: datasetVersion || undefined,
    parameter_values: sanitizeEffectiveValues(effective),
    parameters: toEffectiveConfigEntries(effective, origins),
  }
}
function normalizedLower(value: unknown): string {
  return normalizeId(value).toLowerCase()
}

function buildReadinessWarningDetail(base?: string): string {
  const trimmed = normalizeId(base)
  return trimmed
    ? `${trimmed} ${READINESS_WARNING_FALLBACK_DETAIL}`
    : READINESS_WARNING_FALLBACK_DETAIL
}

async function buildDataValidatedCheck(args: {
  req: NextRequest
  datasetId: string
  datasetVersion: string
  authed: boolean
}): Promise<PlanCheck> {
  const { req, datasetId, datasetVersion, authed } = args

  const timeoutController = new AbortController()
  const url = new URL(
    `/api/catalog/datasets/${encodeURIComponent(datasetId)}/resources`,
    req.nextUrl.origin,
  )
  if (datasetVersion) {
    url.searchParams.set('datasetVersion', datasetVersion)
  }
  url.searchParams.set('checkSourceAccess', 'false')
  const resourcesReq = new NextRequest(url.toString(), {
    method: 'GET',
    headers: new Headers(req.headers),
    signal: timeoutController.signal,
  })
  const timeoutErrorMessage = `Resource readiness check timed out after ${RESOURCES_FETCH_TIMEOUT_MS}ms.`
  let timeoutHandle: ReturnType<typeof setTimeout> | undefined

  try {
    const timeoutError = Object.assign(
      new Error(timeoutErrorMessage),
      { name: 'AbortError' },
    )
    const timeoutPromise = new Promise<never>((_resolve, reject) => {
      timeoutHandle = setTimeout(() => {
        timeoutController.abort(timeoutError)
        reject(timeoutError)
      }, RESOURCES_FETCH_TIMEOUT_MS)
    })

    const response = await Promise.race([
      getDatasetResources(resourcesReq, { params: { datasetId } }),
      timeoutPromise,
    ])

    if (!response.ok) {
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'warning',
        detail: buildReadinessWarningDetail(
          `Resource readiness check returned HTTP ${response.status}.`,
        ),
      }
    }

    const payload = (await response.json().catch(() => null)) as ResourcesReadinessPayload | null
    if (!payload || typeof payload !== 'object') {
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'warning',
        detail: buildReadinessWarningDetail(
          'Resource readiness response could not be parsed.',
        ),
      }
    }

    const readinessStatus = normalizedLower(payload.readiness?.status)
    const readinessReason = normalizeId(payload.readiness?.reason)
    const localPathAvailable = payload.readiness?.local_path_available === true
    const bucketState = normalizedLower(payload.source_access?.bucket_check?.state)
    const bucketMessage = normalizeId(payload.source_access?.bucket_check?.message)
    const requiredFilesPassed = payload.required_files?.all_required_passed
    const unavailable = payload.unavailable === true

    const readinessPassed = readinessStatus === 'ready' || readinessStatus === 'healed'
    const bucketExplicitInaccessible =
      bucketState === 'verified_absent' || bucketState === 'permission_denied'

    const explicitInaccessible =
      readinessStatus === 'blocked' ||
      requiredFilesPassed === false ||
      (!authed && readinessStatus === 'auth_required') ||
      (!readinessPassed && bucketExplicitInaccessible)

    if (explicitInaccessible) {
      let detail = readinessReason
      if (!detail && bucketMessage) detail = bucketMessage
      if (!detail && requiredFilesPassed === false) {
        detail = 'Required files for this dataset are missing or inaccessible.'
      }
      if (!detail && !authed && readinessStatus === 'auth_required') {
        detail = 'Sign in to run backend readiness checks.'
      }
      if (!detail) detail = 'Dataset resources are not currently accessible.'
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'blocked',
        detail,
      }
    }

    if (readinessPassed) {
      if (bucketExplicitInaccessible) {
        return {
          id: 'data_validated',
          label: 'Data validated',
          status: 'warning',
          detail: buildReadinessWarningDetail(
            readinessReason || bucketMessage || 'Source access checks are inconsistent.',
          ),
        }
      }
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'passed',
        detail: readinessReason
          ? readinessReason
          : datasetVersion
            ? `Dataset found. Requested version: ${datasetVersion}.`
            : 'Dataset readiness checks passed.',
      }
    }

    if (authed && readinessStatus === 'auth_required') {
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'warning',
        detail: buildReadinessWarningDetail(
          'Readiness service reported auth_required despite authenticated session.',
        ),
      }
    }

    if (readinessStatus === 'partial' && localPathAvailable) {
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'warning',
        detail: buildReadinessWarningDetail(
          readinessReason ||
            'Mounted dataset path is available, but full dataset readiness has non-blocking notes.',
        ),
      }
    }

    if (
      unavailable ||
      !readinessStatus ||
      readinessStatus === 'unknown' ||
      bucketState === 'unknown' ||
      bucketState === 'unreachable'
    ) {
      return {
        id: 'data_validated',
        label: 'Data validated',
        status: 'warning',
        detail: buildReadinessWarningDetail(readinessReason || bucketMessage),
      }
    }

    return {
      id: 'data_validated',
      label: 'Data validated',
      status: 'warning',
      detail: buildReadinessWarningDetail(readinessReason),
    }
  } catch (error) {
    const timeoutLike =
      error instanceof Error &&
      (error.name === 'AbortError' || error.message.toLowerCase().includes('abort'))
    return {
      id: 'data_validated',
      label: 'Data validated',
      status: 'warning',
      detail: buildReadinessWarningDetail(
        timeoutLike
          ? timeoutErrorMessage
          : 'Resource readiness check failed unexpectedly.',
      ),
    }
  } finally {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle)
    }
  }
}

function datasetSupportsModalities(datasetModalities: string[], requiredModalities: string[]) {
  if (!requiredModalities.length) return true
  const datasetSet = new Set(datasetModalities.map((m) => m.toLowerCase()))
  return requiredModalities.some((required) => datasetSet.has(required.toLowerCase()))
}

function buildRuntimeCheckDetail(payload: RuntimePreflightResponse): string {
  const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : []
  const checks = Array.isArray(payload.checks) ? payload.checks : []
  const missing = checks
    .filter(
      (check) =>
        check.status === 'missing' ||
        check.code === 'UNKNOWN_TOOL_ALIAS' ||
        check.code === 'RUNTIME_TOOL_NOT_REGISTERED',
    )
    .map((check) => check.requested_tool_id || check.tool_id)
  const blocked = checks
    .filter((check) => check.status === 'blocked' || check.code === 'RUNTIME_TOOL_NOT_ALLOWED')
    .map((check) => check.requested_tool_id || check.tool_id)
  const unavailable = checks
    .filter(
      (check) =>
        check.status &&
        check.status !== 'available' &&
        check.status !== 'missing' &&
        check.status !== 'blocked',
    )
    .map((check) => check.tool_id)

  const parts: string[] = []
  if (missing.length) parts.push(`Missing runtime tools: ${missing.join(', ')}`)
  if (blocked.length) parts.push(`Blocked by allowlist: ${blocked.join(', ')}`)
  if (unavailable.length) parts.push(`Unavailable runtime tools: ${unavailable.join(', ')}`)
  if (warnings.length) parts.push(warnings.join(' | '))
  if (!parts.length) parts.push('Runtime executability check failed.')
  return parts.join('. ')
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

export async function POST(req: NextRequest) {
  let bodyRaw: unknown
  try {
    bodyRaw = await req.json()
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON payload.' }, { status: 400 })
  }

  const body = safeRecord(bodyRaw) ?? {}
  const datasetId = normalizeId(body.dataset_id)
  const datasetVersion =
    normalizeId(body.dataset_version) || normalizeId(body.datasetVersion)
  const selection = canonicalizeTemplateSelection({
    analysisId: normalizeId(body.analysis_id),
    pipelineId: normalizeId(body.pipeline_id),
    templateId: normalizeId(body.template_id),
  })
  const analysisId = selection.analysisId
  const pipelineId = selection.pipelineId
  const parameters = safeRecord(body.parameters) ?? {}

  const authed = await isRequestAuthenticated(req)

  const checks: PlanCheck[] = []

  if (!authed) {
    checks.push({
      id: 'authenticated',
      label: 'Signed in',
      status: 'blocked',
      detail: 'Sign in to run analyses.',
    })
  }

  const dataset = datasetId ? getDataset(datasetId) : null
  if (!datasetId) {
    checks.push({
      id: 'data_validated',
      label: 'Data validated',
      status: 'blocked',
      detail: 'Select a dataset.',
    })
  } else if (!dataset) {
    checks.push({
      id: 'data_validated',
      label: 'Data validated',
      status: 'blocked',
      detail: `Dataset not found: ${datasetId}`,
    })
  } else {
    checks.push(
      await buildDataValidatedCheck({
        req,
        datasetId,
        datasetVersion,
        authed,
      }),
    )
  }

  const analysis = analysisId
    ? ANALYSIS_TYPES.find((candidate) => candidate.id === analysisId) ?? null
    : null
  const pipeline = analysis?.pipelines.find((candidate) => candidate.id === pipelineId) ?? null
  const dynamicWorkflow =
    analysisId === 'dynamic_workflow' && pipelineId ? getWorkflowById(pipelineId).workflow : null

  if (!analysisId || !pipelineId) {
    checks.push({
      id: 'workflow_compatible',
      label: 'Workflow compatible',
      status: 'blocked',
      detail: 'Select an analysis type and pipeline.',
    })
  } else if (analysisId === 'dynamic_workflow') {
    if (!dynamicWorkflow) {
      checks.push({
        id: 'workflow_compatible',
        label: 'Workflow compatible',
        status: 'blocked',
        detail: `Dynamic workflow not found: ${pipelineId}`,
      })
    } else if (
      dataset &&
      !datasetSupportsModalities(dataset.modalities ?? [], dynamicWorkflow.modalities ?? [])
    ) {
      checks.push({
        id: 'workflow_compatible',
        label: 'Workflow compatible',
        status: 'blocked',
        detail: `Pipeline requires modalities: ${(dynamicWorkflow.modalities ?? []).join(', ') || '—'}; dataset provides: ${
          (dataset.modalities ?? []).join(', ') || '—'
        }.`,
      })
    } else {
      checks.push({ id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' })
    }
  } else if (!analysis || !pipeline) {
    checks.push({
      id: 'workflow_compatible',
      label: 'Workflow compatible',
      status: 'blocked',
      detail: 'Selected analysis or pipeline is not available.',
    })
  } else if (dataset && !datasetSupportsModalities(dataset.modalities ?? [], pipeline.modalities ?? [])) {
    checks.push({
      id: 'workflow_compatible',
      label: 'Workflow compatible',
      status: 'blocked',
      detail: `Pipeline requires modalities: ${(pipeline.modalities ?? []).join(', ') || '—'}; dataset provides: ${
        (dataset.modalities ?? []).join(', ') || '—'
      }.`,
    })
  } else {
    checks.push({ id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' })
  }

  if (!analysisId) {
    checks.push({
      id: 'inputs_provided',
      label: 'All inputs provided',
      status: 'blocked',
      detail: 'Select an analysis type.',
    })
  } else if (!pipelineId) {
    checks.push({
      id: 'inputs_provided',
      label: 'All inputs provided',
      status: 'blocked',
      detail: 'Select a pipeline.',
    })
  } else {
    checks.push({ id: 'inputs_provided', label: 'All inputs provided', status: 'passed' })
  }

  if (analysisId === 'multiverse_glm' && dataset) {
    const taskRaw = normalizeId(parameters.task)
    const normalizedTask = taskRaw ? normalizeTaskLabel(taskRaw) : ''
    const allowedTasks = Array.isArray(dataset.tasks)
      ? dataset.tasks
          .map((task) => normalizeTaskLabel(task))
          .filter((task) => task.length > 0)
      : []
    const allowed = new Set(allowedTasks)
    const hasCatalogTaskContext = allowed.size > 0

    if (!normalizedTask) {
      checks.push({
        id: 'task',
        label: 'Task selected',
        status: 'blocked',
        detail: hasCatalogTaskContext
          ? 'Select a task for multiverse analysis.'
          : 'Dataset metadata does not list tasks. Enter a task explicitly to run multiverse analysis.',
      })
    } else if (hasCatalogTaskContext && !allowed.has(normalizedTask)) {
      checks.push({
        id: 'task',
        label: 'Task selected',
        status: 'warning',
        detail: 'Selected task was not found in the dataset metadata. Proceed with caution.',
      })
    } else if (!hasCatalogTaskContext) {
      checks.push({
        id: 'task',
        label: 'Task selected',
        status: 'warning',
        detail:
          'Dataset metadata does not list tasks. Proceeding with manually specified task; verify task context carefully.',
      })
    } else {
      checks.push({ id: 'task', label: 'Task selected', status: 'passed' })
    }
  }

  if (analysisId === 'multiverse_glm') {
    const maxModels = parameters.max_models
    if (
      typeof maxModels === 'number' &&
      Number.isFinite(maxModels) &&
      (maxModels < 1 || maxModels > 20)
    ) {
      checks.push({
        id: 'max_models',
        label: 'Max models is in range',
        status: 'warning',
        detail: 'Max models should be between 1 and 20.',
      })
    }
  }

  const handoffToolIdForEstimate =
    dynamicWorkflow?.id ||
    (analysis && pipeline?.runConfig
      ? normalizePipelineToolId(analysis.id, pipeline.id, pipeline.runConfig.tool)
      : pipelineId)
  const estimatedRuntime =
    pipeline?.estRuntime || runtimeEstimateForToolId(handoffToolIdForEstimate, dynamicWorkflow?.est_runtime)
  const variantsMultiplier =
    analysisId === 'multiverse_glm' &&
    typeof parameters.max_models === 'number' &&
    Number.isFinite(parameters.max_models)
      ? Math.max(1, Math.floor(parameters.max_models))
      : 1
  const estimatedCredits = estimateCreditsFromRuntime(estimatedRuntime, { variantsMultiplier })
  const policyWorkflowId =
    analysisId && pipelineId
      ? canonicalWorkflowIdForLaunchPolicy(analysisId, pipelineId, handoffToolIdForEstimate)
      : null
  const workflowForLaunchPolicy =
    dynamicWorkflow ?? (policyWorkflowId ? getWorkflowById(policyWorkflowId).workflow : null)
  const recipeLaunchStatus = deriveRecipeLaunchStatus(workflowForLaunchPolicy)
  const registryCreatesExecutableRun =
    recipeLaunchStatus !== 'handoff_only' && recipeLaunchStatus !== 'manual_admin_only'

  let runtimeGuidance: EnvironmentSetupGuidance | null = null
  let runtimePreflightStatus: PlanCheckStatus | null = null
  let runtimePreflightDetail: string | null = null
  const workflowCompatible = checks.find((check) => check.id === 'workflow_compatible')
  if (workflowCompatible?.status === 'passed') {
    try {
      const orchestratorBase = resolveOrchestratorBaseUrl()
      const headers = forwardAuthHeaders(req)
      headers.set('content-type', 'application/json')

      const runtimePayload =
        analysisId === 'dynamic_workflow'
          ? { workflow_id: pipelineId }
          : { tool_ids: pipeline?.runConfig?.tool ? [pipeline.runConfig.tool] : [] }

      const runtimeResponse = await fetch(`${orchestratorBase}/api/preflight/check`, {
        method: 'POST',
        headers,
        body: JSON.stringify(runtimePayload),
        cache: 'no-store',
      })

      if (!runtimeResponse.ok) {
        throw new Error(`upstream status=${runtimeResponse.status}`)
      }

      const payload = (await runtimeResponse.json()) as RuntimePreflightResponse
      if (payload.executable) {
        runtimePreflightStatus = 'passed'
        checks.push({
          id: 'runtime_executable',
          label: 'Runtime executable',
          status: 'passed',
        })
      } else if (
        Array.isArray(payload.checks) &&
        payload.checks.some((check) => isBlockingRuntimeTool(check))
      ) {
        runtimePreflightStatus = 'blocked'
        runtimePreflightDetail = buildRuntimeCheckDetail(payload)
        checks.push({
          id: 'runtime_executable',
          label: 'Runtime executable',
          status: 'blocked',
          detail: runtimePreflightDetail,
        })
      } else {
        runtimePreflightStatus = 'warning'
        runtimePreflightDetail = buildRuntimeCheckDetail(payload)
        checks.push({
          id: 'runtime_executable',
          label: 'Runtime executable',
          status: 'warning',
          detail: runtimePreflightDetail,
        })
      }
      runtimeGuidance = payload.guidance ?? null
    } catch {
      runtimePreflightStatus = 'warning'
      runtimePreflightDetail =
        'Runtime preflight service is unavailable; proceeding without executability proof.'
      checks.push({
        id: 'runtime_executable',
        label: 'Runtime executable',
        status: 'warning',
        detail: runtimePreflightDetail,
      })
    }
  }

  let effectiveConfig: EffectiveRunConfig | null = null
  if (dataset && analysisId && pipelineId) {
    if (analysisId === 'dynamic_workflow' && dynamicWorkflow) {
      effectiveConfig = buildDynamicEffectiveConfig({
        dataset,
        datasetVersion,
        workflow: dynamicWorkflow,
        userParameters: parameters,
      })
    } else if (analysis && pipeline) {
      effectiveConfig = buildStaticEffectiveConfig({
        dataset,
        datasetVersion,
        analysis,
        pipeline,
        userParameters: parameters,
      })
    }
  }

  if (!analysisId || !pipelineId) {
    checks.push({
      id: 'credits_sufficient',
      label: 'Credits sufficient',
      status: 'blocked',
      detail: 'Select an analysis and pipeline to estimate credit usage.',
    })
  } else if (!authed) {
    checks.push({
      id: 'credits_sufficient',
      label: 'Credits sufficient',
      status: 'blocked',
      detail: 'Sign in to verify your available credits.',
    })
  } else if (estimatedCredits == null) {
    const createsExecutableRun =
      registryCreatesExecutableRun && !guidanceRequiresHandoff(runtimeGuidance)
    checks.push({
      id: 'credits_sufficient',
      label: 'Credits sufficient',
      status: createsExecutableRun ? 'blocked' : 'warning',
      detail: creditEstimateUnavailableDetail(recipeLaunchStatus),
    })
  } else {
    try {
      const identity = await resolveCreditsIdentity(req)
      const balance = await getCreditsBalance(req, identity)
      if (!balance) {
        checks.push({
          id: 'credits_sufficient',
          label: 'Credits sufficient',
          status: 'warning',
          detail: 'Credits service is unavailable; unable to validate balance.',
        })
      } else if (balance.balance < estimatedCredits) {
        checks.push({
          id: 'credits_sufficient',
          label: 'Credits sufficient',
          status: 'blocked',
          detail: `Need ${estimatedCredits.toLocaleString()} credits; available ${balance.balance.toLocaleString()}.`,
        })
      } else {
        checks.push({
          id: 'credits_sufficient',
          label: 'Credits sufficient',
          status: 'passed',
          detail: `Estimated ${estimatedCredits.toLocaleString()} credits; available ${balance.balance.toLocaleString()}.`,
        })
      }
    } catch {
      checks.push({
        id: 'credits_sufficient',
        label: 'Credits sufficient',
        status: 'warning',
        detail: 'Credits validation failed unexpectedly; try again.',
      })
    }
  }

  const handoffToolId = workflowForLaunchPolicy?.id || handoffToolIdForEstimate
  const workflowForHandoff = workflowForLaunchPolicy
  const workflowStepTools = (workflowForHandoff?.runtime?.steps ?? [])
    .map((step) => normalizeId(step.tool))
    .filter(Boolean)
  const handoffInputs =
    effectiveConfig?.parameter_values ??
    {
      ...(datasetId ? { dataset_id: datasetId } : {}),
      ...(datasetVersion ? { dataset_version: datasetVersion } : {}),
      ...parameters,
    }
  const launchTrace = {
    requested_analysis_id: selection.requestedAnalysisId || null,
    requested_pipeline_id: selection.requestedPipelineId || null,
    requested_template_id: selection.requestedTemplateId || null,
    canonical_analysis_id: analysisId || null,
    canonical_pipeline_id: pipelineId || null,
    canonical_template_id: selection.templateId || null,
    canonicalized: selection.canonicalized,
    canonicalization_reason: selection.canonicalizationReason || null,
    dataset_id: datasetId || null,
    template_source: dynamicWorkflow
      ? 'workflow_catalog'
      : analysis && pipeline
        ? 'analysis_preset'
        : 'unknown',
    workflow_found: analysisId === 'dynamic_workflow' ? Boolean(dynamicWorkflow) : null,
    preflight_status: runtimePreflightStatus,
    ...(runtimePreflightDetail ? { preflight_detail: runtimePreflightDetail } : {}),
  }
  const handoffAllowedTools =
    handoffToolId && !handoffToolId.startsWith('workflow_') ? [handoffToolId] : []
  const handoffPack = buildPlannerHandoffPack({
    pipeline: pipeline?.runConfig?.pipelineType || workflowForHandoff?.stage || analysisId || null,
    workflowId: workflowForHandoff?.id || (handoffToolId.startsWith('workflow_') ? handoffToolId : null),
    chosenTool: handoffToolId || null,
    datasetRef: datasetId || null,
    inputs: handoffInputs,
    checks,
    warnings: checks
      .filter((check) => check.status === 'warning' || check.status === 'blocked')
      .map((check) => `${check.label}: ${check.detail || check.status}`),
    allowedTools: handoffAllowedTools,
    approvalLevel: handoffAllowedTools.length ? 'confirm' : 'none',
    requiredTools: uniqueStrings([handoffToolId, ...workflowStepTools]),
    targetRuntime: workflowForHandoff?.primary_target ?? null,
    supportedRecipeTargets: workflowForHandoff?.supported_recipe_targets ?? [],
    artifactContract: workflowForHandoff?.artifact_contract ?? null,
    launchTrace,
    effectiveConfig: effectiveConfig ? (effectiveConfig as unknown as Record<string, unknown>) : null,
    preflightStatus: runtimePreflightStatus,
    preflightDetail: runtimePreflightDetail,
  })
  const launchDecision = deriveLaunchDecision({
    checks,
    recipeLaunchStatus,
    runtimeGuidance,
    mcpRecipeAvailable: Boolean(workflowForHandoff?.supported_recipe_targets?.length),
  })
  const capability = buildWorkflowCapabilityContract({
    checks,
    launchDecision,
    recipeLaunchStatus,
    runtimePreflightStatus,
    workflow: workflowForHandoff,
    handoffPack,
    guidance: runtimeGuidance,
    estimatedCredits,
    datasetId,
    datasetVersion,
  })

  const response: PlanChecksResponse = {
    checks,
    launch_decision: launchDecision,
    capability,
    execution_status: capability.execution_status,
    estimate: estimatedRuntime
      ? { runtime: estimatedRuntime, credits: estimatedCredits }
      : { credits: estimatedCredits },
    context: datasetVersion ? { dataset_version: datasetVersion } : undefined,
    effective_config: effectiveConfig ?? undefined,
    guidance: runtimeGuidance,
    handoff_pack: handoffPack,
  }

  return NextResponse.json(response)
}
