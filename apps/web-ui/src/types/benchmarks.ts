/** Benchmark Board types (Phase 1) */

export type TaskGovernanceStatus =
  | 'imported'
  | 'triaged'
  | 'validated'
  | 'active'
  | 'deprecated'
  | 'archived'

export type ValidationType =
  | 'manual_review'
  | 'ci_tests'
  | 'oracle_solution'
  | 'security_audit'
  | 'llm_judge'

export type ValidationResult = 'pass' | 'fail' | 'needs_fix'

export interface BenchmarkExpectedOutput {
  id?: string
  kind?: string
  title?: string
  visibility?: string
  format?: string
  content?: unknown
  [key: string]: unknown
}

export interface BenchmarkDataset {
  dataset_id: string
  version: string
  name: string
  description: string | null
  source_type: string
  source_ref_json: string
  status: string
  imported_at: number
  updated_at: number
}

export interface BenchmarkTaskRow {
  dataset_id: string
  task_id: string
  content_hash: string
  source_created_by_name: string | null
  source_category: string | null
  source_difficulty: string | null
  created_at: number
  updated_at: number
  gov_status: TaskGovernanceStatus | null
  gov_category: string | null
  gov_created_by_name: string | null
  owner: string | null
  tags: string[]
}

export interface BenchmarkTaskDetail {
  dataset_id: string
  task_id: string
  content_hash: string
  source_created_by_name: string | null
  source_category: string | null
  source_difficulty: string | null
  created_at: number
  updated_at: number
  task_spec: {
    schema_version: string
    task_id: string
    name?: string | null
    description?: string | null
    inputs: Record<string, unknown>
    budget?: Record<string, unknown> | null
    expected_outputs: BenchmarkExpectedOutput[]
    allowlist?: Record<string, unknown> | null
    scoring?: Record<string, unknown> | null
    tags: string[]
    metadata?: Record<string, unknown> | null
  }
  governance: {
    dataset_id: string
    task_id: string
    status: TaskGovernanceStatus
    category: string | null
    notes: string | null
    owner: string | null
    created_by_name: string | null
    created_by_email: string | null
    created_by_profile: string | null
    updated_at: number
  } | null
  validations: ValidationRecord[]
  tags: string[]
  dataset: BenchmarkDataset | null
}

export interface ValidationRecord {
  id: number
  dataset_id: string
  task_id: string
  validator: string
  type: ValidationType
  result: ValidationResult
  evidence_url: string | null
  notes: string | null
  validated_at: number
}

export interface ImportRequest {
  url: string
  dataset_id?: string
  version?: string
  overwrite_governance?: boolean
}

export interface ImportResult {
  dataset_id: string
  job_id: number
  status: string
  summary: {
    added: number
    updated: number
    skipped: number
    failed: number
    errors: string[]
  }
}

export interface TaxonomyResponse {
  statuses: string[]
  categories: string[]
  tags: string[]
  difficulties: string[]
}
