/**
 * API client for the Workflow Catalog backend endpoint.
 * Fetches available workflows from /api/workflows dynamically.
 */

export interface WorkflowSummary {
  id: string
  stage: string
  cost_tier: string
  origin?: string
  description: string
  modalities: string[]
  est_runtime?: string
  lifecycle?: 'draft' | 'active' | 'deprecated'
  execution_story_kind?: string
  supported_recipe_targets?: string[]
  primary_target?: string
  execution_recipe_available?: boolean
  agent_mode?: 'local_recipe' | 'manual_admin_only' | string
  launch_status?: 'recipe_launchable' | 'manual_admin_only'
  artifact_contract?: Record<string, unknown>
}

export type WorkflowParamPrimitiveType =
  | 'string'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'array'
  | 'object'

export interface WorkflowInputProperty {
  type?: WorkflowParamPrimitiveType
  title?: string
  description?: string
  enum?: unknown[]
  default?: unknown
  minimum?: number
  maximum?: number
  ui_component?: string
  example?: unknown
}

export interface WorkflowInputsSchema {
  type?: 'object'
  required?: string[]
  properties?: Record<string, WorkflowInputProperty>
}

export interface WorkflowParameterContract {
  schema?: WorkflowInputsSchema
  defaults?: Record<string, unknown>
}

export interface WorkflowDetail extends WorkflowSummary {
  impl: string
  runtime?: {
    kind: string
    steps: Array<{
      id: string
      tool: string
      params: Record<string, unknown>
    }>
  }
  params?: WorkflowParameterContract
}

export interface WorkflowCatalogResponse {
  workflows: WorkflowSummary[]
  count: number
  version: string
}

export interface WorkflowFilters {
  stage?: string
  cost_tier?: string
  modality?: string
  limit?: number
  offset?: number
}

// Map stage names to user-friendly labels
export const STAGE_LABELS: Record<string, string> = {
  preprocessing: 'Preprocessing & QC',
  connectivity: 'Connectivity',
  glm: 'Task GLM',
  decoding: 'Decoding & ML',
  dmri: 'Diffusion MRI',
  dwi: 'Diffusion MRI',
  eeg: 'EEG',
  ephys: 'Electrophysiology',
  meg: 'MEG',
  ieeg: 'iEEG',
  pet: 'PET',
  dataset: 'Dataset',
  encoding: 'Encoding Models',
  unknown: 'Other',
}

// Map cost tiers to colors for badges
export const COST_TIER_COLORS: Record<string, string> = {
  cheap: 'bg-green-100 text-green-800',
  moderate: 'bg-yellow-100 text-yellow-800',
  expensive: 'bg-red-100 text-red-800',
}
