import {
  buildMcpRecipeCallText,
  selectMcpRecipeTarget,
} from '@/lib/mcp-recipe-handoff'

export type LatestPlanPromptOptions = {
  planId?: string | null
  threadId?: string | null
  workflowId?: string | null
  workflowLabel?: string | null
  datasetId?: string | null
  datasetVersion?: string | null
  handoffPack?: Record<string, unknown> | null
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function buildContextSentence(options: LatestPlanPromptOptions): string {
  const handoff = normalizeRecord(options.handoffPack)
  const workflowLabel =
    normalizeText(options.workflowLabel) ||
    normalizeText(options.workflowId) ||
    normalizeText(handoff?.workflow_id) ||
    normalizeText(handoff?.chosen_tool)
  const datasetId = normalizeText(options.datasetId) || normalizeText(handoff?.dataset_ref)
  const datasetVersion = normalizeText(options.datasetVersion)
  const parts: string[] = []
  if (workflowLabel) parts.push(`workflow "${workflowLabel}"`)
  if (datasetId) {
    parts.push(`dataset "${datasetVersion ? `${datasetId}:${datasetVersion}` : datasetId}"`)
  }
  return parts.length ? ` Context: ${parts.join(', ')}.` : ''
}

function normalizeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function buildPackSentence(handoffPack: Record<string, unknown> | null | undefined): string {
  const handoff = normalizeRecord(handoffPack)
  if (!handoff) return ''
  const schemaVersion = normalizeText(handoff.schema_version)
  if (schemaVersion !== 'br-plan-handoff-v1') return ''
  const workflowId = normalizeText(handoff.workflow_id) || normalizeText(handoff.chosen_tool)
  const execution = normalizeRecord(handoff.execution)
  const recipeLookup = normalizeRecord(handoff.recipe_lookup)
  const targetRuntime = selectMcpRecipeTarget({
    targetRuntime: recipeLookup?.target_runtime || execution?.target_runtime,
    supportedTargets: execution?.supported_recipe_targets,
  })
  const parts = ['Use the br-plan-handoff-v1 pack as the execution contract']
  if (workflowId) parts.push(`workflow_id=${workflowId}`)
  if (targetRuntime) parts.push(`target_runtime=${targetRuntime}`)
  return ` ${parts.join('; ')}.`
}

function buildRecipeCallSentence(options: LatestPlanPromptOptions): string {
  const handoff = normalizeRecord(options.handoffPack)
  const recipeLookup = normalizeRecord(handoff?.recipe_lookup)
  const execution = normalizeRecord(handoff?.execution)
  const workflowId =
    normalizeText(recipeLookup?.tool_id) ||
    normalizeText(handoff?.workflow_id) ||
    normalizeText(options.workflowId) ||
    normalizeText(handoff?.chosen_tool) ||
    normalizeText(options.workflowLabel)
  const datasetId = normalizeText(options.datasetId) || normalizeText(handoff?.dataset_ref)
  const params = normalizeRecord(recipeLookup?.params) || {}
  const callText = buildMcpRecipeCallText({
    workflowId,
    targetRuntime: recipeLookup?.target_runtime || execution?.target_runtime,
    supportedTargets: execution?.supported_recipe_targets,
    datasetId,
    params,
  })
  return callText ? ` Preferred MCP recipe call:\n${callText}` : ''
}

export function buildLatestPlanContinuationPrompt(
  options: LatestPlanPromptOptions = {},
): string {
  const planId = normalizeText(options.planId)
  const threadId = normalizeText(options.threadId)
  const workflowId = normalizeText(options.workflowId)
  const workflowLabel = normalizeText(options.workflowLabel)
  const datasetId = normalizeText(options.datasetId)
  const contextSentence = buildContextSentence(options)
  const packSentence = buildPackSentence(options.handoffPack)
  const recipeCallSentence = buildRecipeCallSentence(options)

  if (planId && threadId) {
    return `Continue from Brain Researcher plan ${planId} for thread "${threadId}".${contextSentence}${packSentence} Call get_latest_plan(thread_id="${threadId}") to fetch the validated handoff block before you execute.${recipeCallSentence}`
  }

  if (planId) {
    return `Continue from Brain Researcher plan ${planId}.${contextSentence}${packSentence} Call get_latest_plan() to fetch the validated handoff block before you execute.${recipeCallSentence}`
  }

  if (threadId) {
    return `Continue from my Brain Researcher plan for thread "${threadId}".${contextSentence}${packSentence} Call get_latest_plan(thread_id="${threadId}") to fetch the validated handoff block before you execute.${recipeCallSentence}`
  }

  if (workflowId || workflowLabel || datasetId || options.handoffPack) {
    return `Continue from this Brain Researcher workflow handoff.${contextSentence}${packSentence} Use Brain Researcher MCP to fetch the execution recipe and verify runtime requirements before you execute.${recipeCallSentence}`
  }

  return 'Continue from my Brain Researcher plan. Call get_latest_plan() to fetch the latest validated handoff block before you execute.'
}
