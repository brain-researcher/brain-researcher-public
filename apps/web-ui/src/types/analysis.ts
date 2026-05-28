export type AnalysisStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'cancelling'
  | 'retrying'
  | 'paused'
  | 'timeout'
  | 'review_blocked'
  | 'unknown'

export type AnalysisThreadMode = 'new' | 'reuse' | 'none'

export type AnalysisCreateThread = {
  mode?: AnalysisThreadMode
  thread_id?: string
  title?: string
}

export type AnalysisCreateRequest = {
  title?: string
  prompt?: string
  project_id?: string

  dataset_id?: string

  template_id?: string
  analysis_id?: string
  pipeline_id?: string

  parameters?: Record<string, unknown>

  plan?: Record<string, unknown>

  thread?: AnalysisCreateThread
}

export type AnalysisCreateResponse = {
  analysis_id: string
  run_id?: string
  job_id?: string
  thread_id?: string | null
  status: AnalysisStatus
  created_at?: number | string | null
  links?: {
    analysis?: string
    stream?: string
  }
  warnings?: string[]
  handoff_pack?: Record<string, unknown>
  execution_status?: Record<string, unknown>
}

export type AnalysisSummary = {
  analysis_id: string
  run_id?: string
  job_id?: string
  thread_id?: string | null
  project_id?: string
  status: AnalysisStatus
  created_at?: number | null
  started_at?: number | null
  finished_at?: number | null
  title?: string
  dataset?: {
    dataset_id?: string
    name?: string
    source?: string
  }
  template?: {
    template_id?: string
    analysis_id?: string
    pipeline_id?: string
    name?: string
  }
  has_results?: boolean
}

export type AnalysisPreflightSnapshot = {
  status?: string | null
  detail?: string | null
  route?: string | null
  checks?: Array<Record<string, unknown>>
}

export type AnalysisStepSummary = {
  id?: string
  name: string
  status?: string
  tool?: string
  detail?: string
}

export type AnalysisLogSummary = {
  name: string
  path?: string
  url?: string
  kind?: string
}

export type AnalysesListResponse = {
  items: AnalysisSummary[]
  count: number
  next_cursor?: string | null
}

export type AnalysisDetail = AnalysisSummary & {
  plan?: Record<string, unknown> | null
  parameters?: Record<string, unknown> | null
  methods?: { text?: string; generated?: boolean } | string | null
  artifacts?: unknown | null
  runcard?: unknown | null
  job?: Record<string, unknown> | null
  handoff_pack?: Record<string, unknown> | null
  execution_status?: Record<string, unknown> | null
  artifact_contract?: Record<string, unknown> | null
  preflight?: AnalysisPreflightSnapshot | null
  launch_trace?: Record<string, unknown> | null
  steps_summary?: AnalysisStepSummary[]
  logs_summary?: AnalysisLogSummary[]
  warnings?: string[]
}
