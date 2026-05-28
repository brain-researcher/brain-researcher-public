import type { RecipeLaunchStatus } from '@/lib/server/launch-decision'

export type WorkflowExecutionStatus = {
  recipe_generated: boolean
  runtime_available: boolean
  hosted_executed: boolean
  artifact_verified: boolean
  runtime_scope: 'hosted_preflight'
  recommended_backend: 'hosted' | 'local_backend' | 'manual_admin' | 'unresolved'
  message: string
}

type RuntimePreflightStatus = 'pending' | 'passed' | 'warning' | 'blocked' | null

const HEAVY_RUNTIME_TARGETS = new Set(['neurodesk', 'container', 'slurm'])

function normalizeTargets(targets?: string[] | null): string[] {
  if (!Array.isArray(targets)) return []
  return targets.map((target) => target.trim().toLowerCase()).filter(Boolean)
}

export function workflowTargetsRequireLocalBackend(targets?: string[] | null): boolean {
  return normalizeTargets(targets).some((target) => HEAVY_RUNTIME_TARGETS.has(target))
}

export function buildWorkflowExecutionStatus(args: {
  recipeLaunchStatus?: RecipeLaunchStatus | null
  runtimePreflightStatus?: RuntimePreflightStatus
  supportedTargets?: string[] | null
  recipeCall?: string | null
  recipeGenerated?: boolean
  hostedCanLaunch?: boolean
}): WorkflowExecutionStatus {
  const localBackendRequired =
    args.recipeLaunchStatus === 'handoff_only' ||
    workflowTargetsRequireLocalBackend(args.supportedTargets)
  const recipeGenerated =
    typeof args.recipeGenerated === 'boolean' ? args.recipeGenerated : Boolean(args.recipeCall)
  const runtimeAvailable = args.runtimePreflightStatus === 'passed'

  if (args.recipeLaunchStatus === 'manual_admin_only') {
    return {
      recipe_generated: recipeGenerated,
      runtime_available: runtimeAvailable,
      hosted_executed: false,
      artifact_verified: false,
      runtime_scope: 'hosted_preflight',
      recommended_backend: 'manual_admin',
      message:
        'This workflow is manual/admin-only. Brain Researcher can prepare handoff context, but hosted execution and artifact verification are not claimed by this status.',
    }
  }

  if (localBackendRequired) {
    return {
      recipe_generated: recipeGenerated,
      runtime_available: runtimeAvailable,
      hosted_executed: false,
      artifact_verified: false,
      runtime_scope: 'hosted_preflight',
      recommended_backend: 'local_backend',
      message:
        'Heavy workflow should run on a local backend using the generated MCP recipe. Hosted Brain Researcher does not mark this as executed or artifact-verified until observed artifacts are returned.',
    }
  }

  if (args.hostedCanLaunch && runtimeAvailable) {
    return {
      recipe_generated: recipeGenerated,
      runtime_available: true,
      hosted_executed: false,
      artifact_verified: false,
      runtime_scope: 'hosted_preflight',
      recommended_backend: 'hosted',
      message:
        'Hosted runtime preflight is available. This status does not mean the workflow has executed or produced verified artifacts.',
    }
  }

  return {
    recipe_generated: recipeGenerated,
    runtime_available: runtimeAvailable,
    hosted_executed: false,
    artifact_verified: false,
    runtime_scope: 'hosted_preflight',
    recommended_backend: recipeGenerated ? 'local_backend' : 'unresolved',
    message:
      'This status describes launch and handoff readiness only. It has not executed the workflow or verified artifacts.',
  }
}
