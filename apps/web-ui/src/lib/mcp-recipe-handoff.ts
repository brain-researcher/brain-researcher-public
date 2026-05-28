export const MCP_RECIPE_TARGETS = ['python', 'neurodesk', 'container', 'slurm'] as const

export type McpRecipeTarget = (typeof MCP_RECIPE_TARGETS)[number]

export const MCP_RECIPE_ACTION_LABEL = 'Get MCP recipe'
export const MCP_RUN_ACTION_LABEL = 'Run via MCP in Codex/Cursor'
export const HOSTED_BLOCKED_MCP_AVAILABLE = 'Hosted launch blocked; MCP recipe available.'

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function normalizeMcpRecipeTarget(
  value: unknown,
  fallback: McpRecipeTarget = 'python',
): McpRecipeTarget {
  const normalized = normalizeText(value)?.toLowerCase()
  if (MCP_RECIPE_TARGETS.includes(normalized as McpRecipeTarget)) {
    return normalized as McpRecipeTarget
  }
  return fallback
}

export function selectMcpRecipeTarget(args: {
  targetRuntime?: unknown
  supportedTargets?: unknown
  fallback?: McpRecipeTarget
}): McpRecipeTarget {
  const fallback = args.fallback ?? 'python'
  const target = normalizeText(args.targetRuntime)
  if (target && MCP_RECIPE_TARGETS.includes(target.toLowerCase() as McpRecipeTarget)) {
    return target.toLowerCase() as McpRecipeTarget
  }
  if (Array.isArray(args.supportedTargets)) {
    for (const candidate of args.supportedTargets) {
      const normalized = normalizeText(candidate)?.toLowerCase()
      if (MCP_RECIPE_TARGETS.includes(normalized as McpRecipeTarget)) {
        return normalized as McpRecipeTarget
      }
    }
  }
  return fallback
}

export function normalizeDatasetIdForMcpRecipe(value: unknown): string | null {
  const datasetId = normalizeText(value)
  if (!datasetId) return null
  const openNeuroMatch = datasetId.match(/^ds:openneuro:(ds\d+)$/i)
  if (openNeuroMatch) return openNeuroMatch[1]
  return datasetId
}

function serializeRecipeParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params)
  if (!entries.length) return '{}'
  return `{${entries
    .map(([key, value]) => `${JSON.stringify(key)}: ${JSON.stringify(value)}`)
    .join(', ')}}`
}

export function buildMcpRecipeCallText(args: {
  workflowId?: unknown
  targetRuntime?: unknown
  supportedTargets?: unknown
  datasetId?: unknown
  params?: Record<string, unknown> | null
}): string | null {
  const workflowId = normalizeText(args.workflowId)
  if (!workflowId) return null

  const params = { ...(args.params ?? {}) }
  const datasetId = normalizeDatasetIdForMcpRecipe(args.datasetId)
  if (typeof params.dataset_id === 'string') {
    params.dataset_id = normalizeDatasetIdForMcpRecipe(params.dataset_id) || params.dataset_id
  } else if (datasetId) {
    params.dataset_id = datasetId
  }
  const targetRuntime = selectMcpRecipeTarget({
    targetRuntime: args.targetRuntime,
    supportedTargets: args.supportedTargets,
  })

  return [
    'get_execution_recipe(',
    `    tool_id=${JSON.stringify(workflowId)},`,
    `    target_runtime=${JSON.stringify(targetRuntime)},`,
    `    params=${serializeRecipeParams(params)}`,
    ')',
  ].join('\n')
}
