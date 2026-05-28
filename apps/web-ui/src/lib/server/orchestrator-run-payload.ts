import { getDataset } from '@/lib/server/dataset-catalog'

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

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeId(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

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

export function buildOrchestratorRunPayload(
  plan: Record<string, unknown>,
  projectId: string,
  threadId: string | null,
  checkpointId?: string | null,
) {
  const canonicalPlan = buildCanonicalPlan(plan)
  const planParameters = { ...(safeRecord(plan.parameters) ?? {}) }
  const launchTrace = safeRecord(plan.launch_trace)
  const handoffPack = safeRecord(plan.handoff_pack) ?? safeRecord(plan.handoff)
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
      },
    },
    ...(threadId ? { thread_id: threadId } : {}),
    ...(resolvedCheckpointId ? { checkpoint_id: resolvedCheckpointId } : {}),
    ...(scenarioId ? { scenario_id: scenarioId } : {}),
    ...(firstNonEmptyText(plan.intent, prompt) ? { intent: firstNonEmptyText(plan.intent, prompt) } : {}),
  }
}
