export type RepairHandoff = {
  required: boolean
  reason: string | null
}

export type RepairProposal = {
  narrative: string
  jsonBlock: string
  planPatch: Record<string, unknown> | null
  recipePatchPreview: unknown
  validationIntent: string | null
  handoff: RepairHandoff | null
}

export type RepairDraftStorageV1 = {
  version: 1
  updated_at: number
  dataset_id?: string | null
  dataset_version?: string | null
  concept_ids?: string[]
  intent?: string
  intent_touched?: boolean
  analysis_id?: string | null
  pipeline_id?: string | null
  task?: string | null
  max_models?: number
  parameter_overrides?: Record<string, unknown>
}

export type RepairMessageMetadata = {
  repair_request: true
  repair_context: {
    run_id: string | null
    analysis_id: string | null
    tool_name: string | null
    error_type: string | null
    repair_attempt_count: number
    failing_step: {
      id: string | null
      name: string | null
      tool: string | null
      status: string | null
      error: string | null
    } | null
  }
}

type DraftFallbackContext = {
  datasetId?: string | null
  datasetVersion?: string | null
  analysisId?: string | null
  pipelineId?: string | null
  intent?: string | null
}

const JSON_FENCE_PATTERN = /```json\s*([\s\S]*?)```/i

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized.length > 0 ? normalized : null
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function normalizeHandoff(value: unknown): RepairHandoff | null {
  const record = asRecord(value)
  if (!record) return null
  return {
    required: Boolean(record.required),
    reason: asString(record.reason),
  }
}

function parseDraft(raw: string | null): RepairDraftStorageV1 | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<RepairDraftStorageV1>
    if (parsed.version !== 1) return null
    return {
      version: 1,
      updated_at:
        typeof parsed.updated_at === 'number' && Number.isFinite(parsed.updated_at)
          ? parsed.updated_at
          : 0,
      dataset_id: typeof parsed.dataset_id === 'string' ? parsed.dataset_id : parsed.dataset_id ?? null,
      dataset_version:
        typeof parsed.dataset_version === 'string'
          ? parsed.dataset_version
          : parsed.dataset_version === null
            ? null
            : undefined,
      concept_ids: Array.isArray(parsed.concept_ids)
        ? parsed.concept_ids.filter((value): value is string => typeof value === 'string')
        : [],
      intent: typeof parsed.intent === 'string' ? parsed.intent : undefined,
      intent_touched: Boolean(parsed.intent_touched),
      analysis_id: typeof parsed.analysis_id === 'string' ? parsed.analysis_id : parsed.analysis_id ?? null,
      pipeline_id: typeof parsed.pipeline_id === 'string' ? parsed.pipeline_id : parsed.pipeline_id ?? null,
      task: typeof parsed.task === 'string' ? parsed.task : parsed.task ?? null,
      max_models:
        typeof parsed.max_models === 'number' && Number.isFinite(parsed.max_models)
          ? parsed.max_models
          : undefined,
      parameter_overrides: asRecord(parsed.parameter_overrides) ?? undefined,
    }
  } catch {
    return null
  }
}

export function stripFirstJsonFence(content: string): string {
  const match = JSON_FENCE_PATTERN.exec(content)
  if (!match || typeof match.index !== 'number') return content
  const before = content.slice(0, match.index)
  const after = content.slice(match.index + match[0].length)
  return `${before}${after}`.replace(/\n{3,}/g, '\n\n').trim()
}

export function extractRepairProposal(content: string): RepairProposal | null {
  const match = JSON_FENCE_PATTERN.exec(content)
  if (!match) return null

  let parsed: unknown
  try {
    parsed = JSON.parse(match[1])
  } catch {
    return null
  }

  const record = asRecord(parsed)
  if (!record) return null

  const planPatch = asRecord(record.plan_patch)
  const hasKnownFields =
    Boolean(planPatch) ||
    Object.prototype.hasOwnProperty.call(record, 'recipe_patch_preview') ||
    Object.prototype.hasOwnProperty.call(record, 'validation_intent') ||
    Object.prototype.hasOwnProperty.call(record, 'handoff')

  if (!hasKnownFields) return null

  return {
    narrative: stripFirstJsonFence(content),
    jsonBlock: match[1].trim(),
    planPatch,
    recipePatchPreview: record.recipe_patch_preview,
    validationIntent: asString(record.validation_intent),
    handoff: normalizeHandoff(record.handoff),
  }
}

export function buildRepairMessageMetadata(
  repairContext: unknown,
): RepairMessageMetadata | undefined {
  const record = asRecord(repairContext)
  if (!record) return undefined
  const failingStep = asRecord(record.failing_step)
  return {
    repair_request: true,
    repair_context: {
      run_id: asString(record.run_id),
      analysis_id: asString(record.analysis_id),
      tool_name: asString(record.tool_name),
      error_type: asString(record.error_type),
      repair_attempt_count: asFiniteNumber(record.repair_attempt_count) ?? 0,
      failing_step: failingStep
        ? {
            id: asString(failingStep.id),
            name: asString(failingStep.name),
            tool: asString(failingStep.tool),
            status: asString(failingStep.status),
            error: asString(failingStep.error),
          }
        : null,
    },
  }
}

export function applyRepairPlanPatchToDraft(
  rawDraft: string | null,
  planPatch: unknown,
  fallback: DraftFallbackContext = {},
): RepairDraftStorageV1 | null {
  const patch = asRecord(planPatch)
  if (!patch) return null

  const baseDraft =
    parseDraft(rawDraft) ?? {
      version: 1 as const,
      updated_at: 0,
      dataset_id: fallback.datasetId ?? null,
      dataset_version: fallback.datasetVersion ?? null,
      analysis_id: fallback.analysisId ?? null,
      pipeline_id: fallback.pipelineId ?? null,
      intent: fallback.intent ?? undefined,
      intent_touched: Boolean(fallback.intent && fallback.intent.trim()),
      concept_ids: [],
    }

  const nextDraft: RepairDraftStorageV1 = {
    ...baseDraft,
    version: 1,
    updated_at: Date.now(),
    dataset_id: baseDraft.dataset_id ?? fallback.datasetId ?? null,
    dataset_version: baseDraft.dataset_version ?? fallback.datasetVersion ?? null,
    analysis_id: baseDraft.analysis_id ?? fallback.analysisId ?? null,
    pipeline_id: baseDraft.pipeline_id ?? fallback.pipelineId ?? null,
    intent: baseDraft.intent ?? fallback.intent ?? undefined,
    intent_touched:
      baseDraft.intent_touched ?? Boolean((baseDraft.intent ?? fallback.intent ?? '').trim()),
  }

  const datasetId = asString(patch.dataset_id ?? patch.datasetId)
  if (datasetId !== null) nextDraft.dataset_id = datasetId

  const datasetVersion = asString(patch.dataset_version ?? patch.datasetVersion)
  if (datasetVersion !== null) nextDraft.dataset_version = datasetVersion

  const analysisId = asString(patch.analysis_id ?? patch.analysisId)
  if (analysisId !== null) nextDraft.analysis_id = analysisId

  const pipelineId = asString(patch.pipeline_id ?? patch.pipelineId)
  if (pipelineId !== null) nextDraft.pipeline_id = pipelineId

  const task = asString(patch.task)
  if (task !== null) nextDraft.task = task

  const intent = asString(patch.intent ?? patch.title)
  if (intent !== null) {
    nextDraft.intent = intent
    nextDraft.intent_touched = true
  }

  const maxModels = asFiniteNumber(patch.max_models ?? patch.maxModels)
  if (maxModels !== null) {
    nextDraft.max_models = Math.max(1, Math.floor(maxModels))
  }

  if (Array.isArray(patch.concept_ids)) {
    nextDraft.concept_ids = patch.concept_ids
      .filter((value): value is string => typeof value === 'string')
      .map((value) => value.trim())
      .filter(Boolean)
      .slice(0, 12)
  }

  const parameterOverrides =
    asRecord(patch.parameter_overrides) ||
    asRecord(patch.parameterOverrides) ||
    asRecord(patch.parameter_values) ||
    asRecord(patch.parameterValues)
  if (parameterOverrides) {
    nextDraft.parameter_overrides = {
      ...(baseDraft.parameter_overrides ?? {}),
      ...parameterOverrides,
    }
  }

  return nextDraft
}
