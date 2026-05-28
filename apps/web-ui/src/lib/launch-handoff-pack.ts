export const PLAN_HANDOFF_SCHEMA_VERSION = 'br-plan-handoff-v1' as const

export type LaunchHandoffCheck = {
  id: string
  label?: string
  status?: string
  detail?: string
}

export type LaunchHandoffBackend = {
  kind: 'brain_researcher_orchestrator'
  submit_route: '/run'
  preflight_route?: '/api/preflight/check'
  tool_id?: string | null
  workflow_id?: string | null
  required_tools?: string[]
  target_runtime?: string | null
  supported_recipe_targets?: string[]
  artifact_contract?: Record<string, unknown> | null
  preflight_status?: string | null
  preflight_detail?: string | null
}

export type LaunchRecipeLookup = {
  tool_name: 'get_execution_recipe'
  tool_id: string
  target_runtime?: string | null
  params: Record<string, unknown>
}

export type PlannerHandoffPack = {
  schema_version: typeof PLAN_HANDOFF_SCHEMA_VERSION
  plan_id?: string | null
  version?: number | null
  pipeline?: string | null
  workflow_id?: string | null
  chosen_tool?: string | null
  dataset_ref?: string | null
  inputs: Record<string, unknown>
  warnings: string[]
  validation_summary: Record<string, unknown>
  approval_level: 'none' | 'confirm' | 'admin' | string
  allowed_tools: string[]
  run_mode_hint?: string | null
  execution: LaunchHandoffBackend
  recipe_lookup?: LaunchRecipeLookup
  checks?: LaunchHandoffCheck[]
  launch_trace?: Record<string, unknown>
  effective_config?: Record<string, unknown>
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function normalizeStringList(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const text = normalizeText(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
  }
  return out
}

function normalizeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

const SENSITIVE_HANDOFF_KEY_PATTERN =
  /(token|secret|password|passwd|api[_-]?key|authorization|cookie|credential|private[_-]?key)/i

function sanitizeHandoffValue(key: string, value: unknown): unknown {
  if (SENSITIVE_HANDOFF_KEY_PATTERN.test(key)) {
    return value == null ? value : '[redacted]'
  }
  if (Array.isArray(value)) {
    return value.map((entry) => sanitizeHandoffValue('', entry))
  }
  if (value && typeof value === 'object') {
    const record = normalizeRecord(value)
    if (!record) return value
    return Object.fromEntries(
      Object.entries(record).map(([nestedKey, nestedValue]) => [
        nestedKey,
        sanitizeHandoffValue(nestedKey, nestedValue),
      ]),
    )
  }
  return value
}

function sanitizeHandoffRecord(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => [key, sanitizeHandoffValue(key, entry)]),
  )
}

function cleanChecks(checks: LaunchHandoffCheck[] | undefined): LaunchHandoffCheck[] {
  if (!Array.isArray(checks)) return []
  return checks
    .map((check) => {
      const id = normalizeText(check.id)
      if (!id) return null
      const cleaned: LaunchHandoffCheck = { id }
      const label = normalizeText(check.label)
      const status = normalizeText(check.status)
      const detail = normalizeText(check.detail)
      if (label) cleaned.label = label
      if (status) cleaned.status = status
      if (detail) cleaned.detail = detail
      return cleaned
    })
    .filter(Boolean) as LaunchHandoffCheck[]
}

function inferRunModeHint(args: {
  runModeHint?: string | null
  chosenTool?: string | null
  allowedTools: string[]
  approvalLevel: string
}): string {
  const explicit = normalizeText(args.runModeHint)
  if (explicit) return explicit
  if (args.approvalLevel === 'admin') return 'admin_only'
  if (args.chosenTool?.startsWith('workflow_')) return 'recipe_required'
  if (!args.allowedTools.length) return 'manual_review'
  if (args.approvalLevel === 'confirm') return 'confirm_before_execute'
  return 'direct_execute'
}

export function buildPlannerHandoffPack(args: {
  planId?: string | null
  version?: number | null
  pipeline?: string | null
  workflowId?: string | null
  chosenTool?: string | null
  datasetRef?: string | null
  inputs?: Record<string, unknown> | null
  warnings?: string[]
  checks?: LaunchHandoffCheck[]
  approvalLevel?: 'none' | 'confirm' | 'admin' | string
  allowedTools?: string[]
  runModeHint?: string | null
  requiredTools?: string[]
  targetRuntime?: string | null
  supportedRecipeTargets?: string[]
  artifactContract?: Record<string, unknown> | null
  launchTrace?: Record<string, unknown> | null
  effectiveConfig?: Record<string, unknown> | null
  preflightStatus?: string | null
  preflightDetail?: string | null
}): PlannerHandoffPack {
  const workflowId = normalizeText(args.workflowId)
  const chosenTool = normalizeText(args.chosenTool) || workflowId
  const inputs = sanitizeHandoffRecord(normalizeRecord(args.inputs) ?? {})
  const allowedTools = normalizeStringList(args.allowedTools)
  const requiredTools = normalizeStringList(args.requiredTools)
  const supportedRecipeTargets = normalizeStringList(args.supportedRecipeTargets)
  const targetRuntime =
    normalizeText(args.targetRuntime) ||
    supportedRecipeTargets[0] ||
    (workflowId ? 'python' : null)
  const approvalLevel = normalizeText(args.approvalLevel) || 'none'
  const runModeHint = inferRunModeHint({
    runModeHint: args.runModeHint,
    chosenTool,
    allowedTools,
    approvalLevel,
  })
  const checks = cleanChecks(args.checks)
  const warnings = normalizeStringList(args.warnings)
  const blockingChecks = checks.filter((check) => check.status === 'blocked')

  const backend: LaunchHandoffBackend = {
    kind: 'brain_researcher_orchestrator',
    submit_route: '/run',
    preflight_route: '/api/preflight/check',
    tool_id: chosenTool,
    workflow_id: workflowId,
    required_tools: requiredTools,
    target_runtime: targetRuntime,
    supported_recipe_targets: supportedRecipeTargets,
    artifact_contract: args.artifactContract ?? null,
    preflight_status: normalizeText(args.preflightStatus),
    preflight_detail: normalizeText(args.preflightDetail),
  }

  const handoff: PlannerHandoffPack = {
    schema_version: PLAN_HANDOFF_SCHEMA_VERSION,
    plan_id: normalizeText(args.planId),
    version: typeof args.version === 'number' ? args.version : null,
    pipeline: normalizeText(args.pipeline),
    workflow_id: workflowId,
    chosen_tool: chosenTool,
    dataset_ref: normalizeText(args.datasetRef),
    inputs,
    warnings,
    validation_summary: {
      warning_count: warnings.length,
      blocked_check_count: blockingChecks.length,
      check_count: checks.length,
    },
    approval_level: approvalLevel,
    allowed_tools: allowedTools,
    run_mode_hint: runModeHint,
    execution: backend,
  }

  if (workflowId || chosenTool) {
    handoff.recipe_lookup = {
      tool_name: 'get_execution_recipe',
      tool_id: workflowId || chosenTool || '',
      target_runtime: targetRuntime,
      params: inputs,
    }
  }
  if (checks.length) handoff.checks = checks
  if (args.launchTrace) handoff.launch_trace = args.launchTrace
  if (args.effectiveConfig) handoff.effective_config = sanitizeHandoffRecord(args.effectiveConfig)
  return handoff
}
