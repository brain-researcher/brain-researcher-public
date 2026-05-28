import fs from 'fs'
import path from 'path'
import yaml from 'js-yaml'

import type {
  WorkflowInputsSchema,
  WorkflowParameterContract,
  WorkflowCatalogResponse,
  WorkflowDetail,
  WorkflowSummary,
} from '@/lib/api/workflows'

type CatalogWorkflow = {
  id: string
  stage?: string
  cost_tier?: string
  origin?: string
  lifecycle?: 'draft' | 'active' | 'deprecated'
  execution_story_kind?: string
  supported_recipe_targets?: string[]
  primary_target?: string
  artifact_contract?: Record<string, unknown>
  description?: string
  impl?: string
  modalities?: string[]
  est_runtime?: string
  resource_profile?: {
    est_runtime?: string
  }
  params?: {
    schema?: WorkflowInputsSchema
    defaults?: Record<string, unknown>
  }
  runtime?: {
    kind?: string
    steps?: Array<{
      id?: string
      tool: string
      params?: Record<string, unknown>
    }>
  }
}

type CatalogData = {
  version?: string
  workflows?: CatalogWorkflow[]
}

const CATALOG_FILENAME = path.join('configs', 'workflows', 'workflow_catalog.yaml')

function resolveCatalogPath(): { path: string; candidates: string[] } {
  const override =
    process.env.PROJECT_ROOT ||
    process.env.NEXT_PUBLIC_PROJECT_ROOT ||
    process.env.WORKFLOW_CATALOG_PATH

  const candidates = [
    override ? path.resolve(override, CATALOG_FILENAME) : null,
    override ? path.resolve(override) : null,
    path.resolve(process.cwd(), CATALOG_FILENAME),
    path.resolve(process.cwd(), '..', CATALOG_FILENAME),
    path.resolve(process.cwd(), '..', '..', CATALOG_FILENAME),
    path.resolve(process.cwd(), '..', '..', '..', CATALOG_FILENAME),
  ].filter(Boolean) as string[]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return { path: candidate, candidates }
    }
  }

  return { path: candidates[0] || path.resolve(process.cwd(), CATALOG_FILENAME), candidates }
}

function loadCatalog(): { version: string; workflows: CatalogWorkflow[] } {
  try {
    const resolved = resolveCatalogPath()
    if (!fs.existsSync(resolved.path)) {
      console.warn(
        `[workflow-catalog] File not found: ${resolved.path} (cwd=${process.cwd()}, tried=${resolved.candidates.join(', ')})`,
      )
      return { version: 'unknown', workflows: [] }
    }

    const raw = fs.readFileSync(resolved.path, 'utf-8')
    const parsed = yaml.load(raw) as CatalogData | null
    const workflows = Array.isArray(parsed?.workflows) ? parsed!.workflows! : []
    const version = parsed?.version ? String(parsed.version) : 'unknown'
    return { version, workflows }
  } catch (err) {
    const resolved = resolveCatalogPath()
    console.error(`[workflow-catalog] Error loading catalog from ${resolved.path}:`, err)
    return { version: 'unknown', workflows: [] }
  }
}

function normalizeModalities(value?: string[]): string[] {
  if (!Array.isArray(value)) return []
  return value.map((entry) => String(entry)).filter(Boolean)
}

function normalizeStringList(value?: string[]): string[] {
  if (!Array.isArray(value)) return []
  return value.map((entry) => String(entry).trim()).filter(Boolean)
}

function toSummary(workflow: CatalogWorkflow): WorkflowSummary {
  const supportedRecipeTargets = normalizeStringList(workflow.supported_recipe_targets)
  const executionRecipeAvailable = supportedRecipeTargets.length > 0
  const estRuntime = workflow.est_runtime || workflow.resource_profile?.est_runtime
  return {
    id: workflow.id,
    stage: workflow.stage || 'unknown',
    cost_tier: workflow.cost_tier || 'moderate',
    origin: workflow.origin,
    lifecycle: workflow.lifecycle,
    description: workflow.description || workflow.impl || 'Workflow from catalog',
    modalities: normalizeModalities(workflow.modalities),
    est_runtime: estRuntime,
    execution_story_kind: workflow.execution_story_kind,
    supported_recipe_targets: supportedRecipeTargets,
    primary_target: workflow.primary_target,
    execution_recipe_available: executionRecipeAvailable,
    agent_mode: executionRecipeAvailable ? 'local_recipe' : 'manual_admin_only',
    launch_status: executionRecipeAvailable ? 'recipe_launchable' : 'manual_admin_only',
    artifact_contract: workflow.artifact_contract,
  }
}

function normalizeParameterContract(
  value: CatalogWorkflow['params'],
): WorkflowParameterContract | undefined {
  if (!value || typeof value !== 'object') return undefined
  const out: WorkflowParameterContract = {}
  if (value.schema && typeof value.schema === 'object') {
    out.schema = value.schema
  }
  if (value.defaults && typeof value.defaults === 'object') {
    out.defaults = value.defaults
  }
  if (!out.schema && !out.defaults) return undefined
  return out
}

function toDetail(workflow: CatalogWorkflow): WorkflowDetail {
  return {
    ...toSummary(workflow),
    impl: workflow.impl || workflow.description || '',
    params: normalizeParameterContract(workflow.params),
    runtime: workflow.runtime
      ? {
          kind: workflow.runtime.kind || 'declarative_workflow',
          steps: (workflow.runtime.steps || []).map((step) => ({
            id: step.id || step.tool,
            tool: step.tool,
            params: step.params || {},
          })),
        }
      : undefined,
  }
}

export function listWorkflows(filters?: {
  stage?: string
  cost_tier?: string
  modality?: string
  limit?: number
  offset?: number
}): WorkflowCatalogResponse {
  const { version, workflows } = loadCatalog()
  let filtered = workflows

  if (filters?.stage) {
    const stage = filters.stage.toLowerCase()
    filtered = filtered.filter((wf) => (wf.stage || '').toLowerCase() === stage)
  }

  if (filters?.cost_tier) {
    const tier = filters.cost_tier.toLowerCase()
    filtered = filtered.filter((wf) => (wf.cost_tier || '').toLowerCase() === tier)
  }

  if (filters?.modality) {
    const modality = filters.modality.toLowerCase()
    filtered = filtered.filter((wf) =>
      normalizeModalities(wf.modalities)
        .map((m) => m.toLowerCase())
        .includes(modality)
    )
  }

  const offset = Math.max(0, filters?.offset ?? 0)
  const limit = Math.max(1, Math.min(filters?.limit ?? 100, 500))
  const paged = filtered.slice(offset, offset + limit)

  return {
    workflows: paged.map(toSummary),
    count: filtered.length,
    version,
  }
}

export function getWorkflowById(id: string): { workflow: WorkflowDetail | null; version: string } {
  const { version, workflows } = loadCatalog()
  const match = workflows.find((wf) => wf.id === id)
  return {
    workflow: match ? toDetail(match) : null,
    version,
  }
}

export function listWorkflowStages(): string[] {
  const { workflows } = loadCatalog()
  const stages = new Set<string>()
  workflows.forEach((wf) => {
    if (wf.stage) stages.add(wf.stage)
  })
  return Array.from(stages).sort()
}
