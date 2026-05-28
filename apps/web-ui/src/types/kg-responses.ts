/**
 * Type definitions for Knowledge Graph and Agent API responses
 */

/**
 * Pipeline template from BR-KG
 * Represents a PipelineTemplate node with its relationships
 */
export interface KGPipeline {
  id: string
  name: string
  description?: string
  ops: string[]  // Operation IDs linked via HAS_STEP
  preferred_families: string[]  // ToolFamily IDs linked via USES_FAMILY
  datasets: string[]  // Dataset IDs linked via RECOMMENDED_FOR
  modalities?: string[]  // Supported modalities (fMRI, dMRI, etc.)
  metadata?: Record<string, any>
}

/**
 * Tool from /agent/debug/kg/tools endpoint
 * Includes KG hint metadata and promotion status
 */
export interface KGTool {
  id: string
  name: string
  family: string  // ToolFamily ID
  is_promoted: boolean  // Whether this tool is promoted in KG
  runtime_estimate_seconds?: number
  kg_tool_count?: number  // Number of tools in KG for this family
  description?: string
  version?: string
  parameters?: Record<string, any>
  metadata?: Record<string, any>
}

/**
 * Tool family with coverage statistics
 * Used for displaying family→operation tool counts
 */
export interface KGToolFamily {
  id: string
  name: string
  tool_count: number  // Number of tools implementing this family
  operations: string[]  // Operations this family can handle
  is_preferred?: boolean  // Whether this is a preferred family for a pipeline
}

/**
 * Coverage statistics for a specific operation
 */
export interface OperationCoverage {
  operation_id: string
  operation_name: string
  families: Array<{
    family_id: string
    family_name: string
    tool_count: number
    is_preferred: boolean
  }>
  total_tools: number
}

/**
 * Plan candidate from Agent planner
 */
export interface PlanCandidate {
  tool: string  // Tool ID
  tool_id?: string // Alternate key from catalog planner
  tool_name?: string
  family?: string
  source?: string  // 'catalog' | 'kg' | other
  available?: boolean
  unavailable_reason?: { code?: string; detail?: string }
  explanation?: string
  kg_score?: number
  prior_success_rate?: number
  prior_latency_score?: number
  prior_failure_penalty?: number
  failure_penalty?: number
  failed_on_count?: number
  failure_last_seen?: number | string | null
  evidence_layer?: string
  evidence_n?: number
  // Intent-router debug rows use `score`; catalog planner uses `final_score`.
  score?: number
  final_score?: number
  reasons?: any[]
  metadata?: {
    is_promoted?: boolean
    kg_hint_score?: number
    catalog_score?: number
  }
}

export interface PlannerEvent {
  event_type: string
  ts: number
  event_id?: string
  payload?: Record<string, any>
  diff?: Record<string, any>
}

export interface PlannerState {
  hypotheses: any[]
  branches: any[]
  rejected: string[]
  pending: string[]
  selected_branch_id?: string | null
  selected_tool_ids?: string[]
}

export interface ViolationLocation {
  component?: string | null
  stage?: string | null
  step_id?: string | null
  path?: string | null
}

export interface EvidenceRef {
  type?: string
  uri?: string | null
  summary?: string | null
  pointer?: string | null
}

export interface Violation {
  schema_version?: string
  code: string
  message: string
  severity?: 'info' | 'warn' | 'error' | 'critical'
  blocking?: boolean
  where?: ViolationLocation | null
  evidence?: EvidenceRef[]
  suggested_fix?: string | null
  details?: Record<string, any>
}

export interface RunSummary {
  plan_conf?: number
  branch_conf?: Array<Record<string, any>>
  step_conf?: Array<Record<string, any>>
  uncertainty_penalty?: number
  notes?: string[]
}

/**
 * Response from /agent/plan endpoint with debug information
 */
export interface AgentPlanResponse {
  chosen_tool: string  // Selected tool ID
  chosen_tool_name?: string
  chosen_family?: string
  selection_reasons?: any[]  // Reasons for selection (when debug_selection=true)
  mask_reasons?: Violation[]  // Default-on constraint/masking reasons (Violation model)
  candidates?: PlanCandidate[]  // All evaluated candidates
  planner_events?: PlannerEvent[]
  planner_state?: PlannerState
  run_summary?: RunSummary
  plan_conf?: number
  confidence_score?: number
  steps?: Array<{
    step_id: string
    tool: string
    operation: string
    parameters?: Record<string, any>
    inputs?: Record<string, any>
    outputs?: Record<string, any>
  }>
  metadata?: {
    use_kg_hints?: boolean
    kg_hint_weight?: number
    promoted_weight?: number
    selection_time_ms?: number
    is_promoted?: boolean
    kg_hint_score?: number
  }
  error?: string
}

/**
 * Request payload for /agent/plan endpoint
 */
export interface PlanRequest {
  pipeline: string  // Pipeline ID (e.g., "fmriprep")
  domain?: string  // Default: "neuroimaging"
  modality: string[]  // e.g., ["fMRI", "dMRI"]
  inputs?: Record<string, any>  // Optional input specifications
  debug_selection?: boolean  // Enable selection reasons and additional debug metadata
  use_kg_hints?: boolean  // Whether to use KG hints for selection
  kg_hint_weight?: number  // Weight for KG hints (0-1)
  promoted_weight?: number  // Weight for promoted tools (0-1)
}

/**
 * Response from /api/kg/pipelines endpoint
 */
export interface KGPipelinesResponse {
  pipelines: KGPipeline[]
  total_count?: number
}

/**
 * Response from /api/kg/tools endpoint
 */
export interface KGToolsResponse {
  tools: KGTool[]
  grouped_by_family?: Record<string, KGTool[]>  // Tools grouped by family ID
  total_count?: number
  operation?: string  // The operation these tools are for
  pipeline?: string  // The pipeline context (if provided)
}

/**
 * Response from /api/kg/coverage endpoint (future use)
 */
export interface KGCoverageResponse {
  operation_coverage: OperationCoverage[]
  family_stats: KGToolFamily[]
  total_operations: number
  total_families: number
  total_tools: number
}
