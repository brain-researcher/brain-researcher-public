import { HOSTED_BLOCKED_MCP_AVAILABLE } from '@/lib/mcp-recipe-handoff'

export type LaunchDecisionStatus =
  | 'runnable'
  | 'runnable_with_warning'
  | 'blocked'
  | 'handoff_only'
  | 'manual_admin_only'

export type RecipeLaunchStatus =
  | 'launchable'
  | 'handoff_only'
  | 'manual_admin_only'

export type LaunchDecisionCode =
  | 'ready'
  | 'warning'
  | 'blocked_auth'
  | 'blocked_credit'
  | 'blocked_missing_runtime'
  | 'blocked_inputs'
  | 'blocked_data'
  | 'blocked_selection'
  | 'handoff_only'
  | 'manual_admin_only'

export type LaunchDecisionCheck = {
  id?: string
  label?: string
  status?: string
  detail?: string
}

export type RuntimeGuidanceForLaunchDecision = {
  kind?: string | null
  summary?: string | null
  supported_recipe_targets?: string[] | null
}

export type LaunchDecision = {
  status: LaunchDecisionStatus
  code: LaunchDecisionCode
  can_launch: boolean
  primary_action: 'launch' | 'sign_in' | 'grant_credits' | 'handoff' | 'fix_inputs'
  reason: string
}

type RecipeLaunchWorkflow = {
  supported_recipe_targets?: string[] | null
  execution_recipe_available?: boolean | null
  agent_mode?: string | null
  launch_status?: string | null
}

function normalizeText(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : ''
}

export function guidanceRequiresHandoff(
  guidance?: RuntimeGuidanceForLaunchDecision | null,
): boolean {
  const kind = normalizeText(guidance?.kind)
  const targets = Array.isArray(guidance?.supported_recipe_targets)
    ? guidance.supported_recipe_targets.map((target) => normalizeText(target)).filter(Boolean)
    : []
  return kind.includes('handoff') || kind.includes('recipe') || targets.length > 0
}

export function deriveRecipeLaunchStatus(
  workflow?: RecipeLaunchWorkflow | null,
): RecipeLaunchStatus | null {
  if (!workflow) return null
  const launchStatus = normalizeText(workflow.launch_status)
  const agentMode = normalizeText(workflow.agent_mode)
  const hasRecipeTargetsField = Array.isArray(workflow.supported_recipe_targets)
  const targets = hasRecipeTargetsField
    ? workflow.supported_recipe_targets?.map((target) => normalizeText(target)).filter(Boolean) ?? []
    : []

  if (launchStatus === 'manual_admin_only' || agentMode === 'manual_admin_only') {
    return 'manual_admin_only'
  }
  if (launchStatus === 'handoff_only' || agentMode === 'handoff_only') {
    return 'handoff_only'
  }
  if (workflow.execution_recipe_available === false || (hasRecipeTargetsField && targets.length === 0)) {
    return 'handoff_only'
  }
  return 'launchable'
}

function blockedCodeForCheck(check: LaunchDecisionCheck): LaunchDecisionCode {
  const id = String(check.id || '').trim().toLowerCase()
  const detail = String(check.detail || '').trim().toLowerCase()
  if (detail.includes('sign in') || detail.includes('authentication')) return 'blocked_auth'
  if (id.includes('credit')) return 'blocked_credit'
  if (id.includes('runtime')) return 'blocked_missing_runtime'
  if (id.includes('input')) return 'blocked_inputs'
  if (id.includes('data') || id.includes('resource')) return 'blocked_data'
  if (id.includes('selection') || id.includes('pipeline') || id.includes('analysis')) {
    return 'blocked_selection'
  }
  return 'blocked_inputs'
}

export function deriveLaunchDecision(args: {
  checks: LaunchDecisionCheck[]
  recipeLaunchStatus?: RecipeLaunchStatus | null
  runtimeGuidance?: RuntimeGuidanceForLaunchDecision | null
  mcpRecipeAvailable?: boolean
}): LaunchDecision {
  const recipeStatus = args.recipeLaunchStatus ?? null
  if (recipeStatus === 'manual_admin_only') {
    return {
      status: 'manual_admin_only',
      code: 'manual_admin_only',
      can_launch: false,
      primary_action: 'handoff',
      reason: 'This workflow is marked manual/admin only in the executable workflow registry.',
    }
  }
  if (recipeStatus === 'handoff_only') {
    return {
      status: 'handoff_only',
      code: 'handoff_only',
      can_launch: false,
      primary_action: 'handoff',
      reason:
        'This workflow is handoff-only: long-running or container workflows should run from the recipe in a local, Neurodesk, Slurm, or coding-agent environment instead of the hosted UI.',
    }
  }
  if (guidanceRequiresHandoff(args.runtimeGuidance)) {
    return {
      status: 'handoff_only',
      code: 'handoff_only',
      can_launch: false,
      primary_action: 'handoff',
      reason:
        args.runtimeGuidance?.summary ||
        'This workflow is handoff-only in the current runtime: run the recipe locally, in Neurodesk or Slurm, or from a coding agent instead of the hosted UI.',
    }
  }

  const blocked = args.checks.find((check) => check.status === 'blocked')
  if (blocked) {
    const code = blockedCodeForCheck(blocked)
    const reason =
      blocked.detail ||
      blocked.label ||
      'Resolve blocked launch checks before creating a run.'
    const shouldPreferHandoff =
      args.mcpRecipeAvailable === true &&
      (code === 'blocked_credit' ||
        code === 'blocked_data' ||
        code === 'blocked_missing_runtime')
    return {
      status: 'blocked',
      code,
      can_launch: false,
      primary_action:
        shouldPreferHandoff
          ? 'handoff'
          : code === 'blocked_auth'
          ? 'sign_in'
          : code === 'blocked_credit'
            ? 'grant_credits'
            : 'fix_inputs',
      reason: shouldPreferHandoff ? `${reason} ${HOSTED_BLOCKED_MCP_AVAILABLE}` : reason,
    }
  }

  const warning = args.checks.find((check) => check.status === 'warning')
  if (warning) {
    return {
      status: 'runnable_with_warning',
      code: 'warning',
      can_launch: true,
      primary_action: 'launch',
      reason:
        warning.detail ||
        warning.label ||
        'Launch is allowed, but one or more checks could not be fully verified.',
    }
  }

  return {
    status: 'runnable',
    code: 'ready',
    can_launch: true,
    primary_action: 'launch',
    reason: 'All required launch checks passed.',
  }
}
