export interface DatasetPreview {
  kind: string
  uri: string
  label?: string
}

export interface DatasetPhenotypeSummary {
  name: string
  column?: string
  category: string
  measurement_type?: string
  total_observations: number
  unique_subjects?: number
  distinct_values?: number
  value_counts?: Record<string, number>
  numeric_summary?: {
    min?: number
    max?: number
    mean?: number
    median?: number
  }
}

export interface DatasetResourceAddresses {
  dataset_ref: string
  source_kind: "openneuro" | "other"
  exists_summary?: {
    dataset_in_catalog?: boolean
    local_bids_available?: boolean
    source_repo?: string
    source_repo_id?: string
    source_version?: string
    derivatives_count?: number
    version_selection_mode?: "metadata_only" | "full_resolution"
  }
  versions?: Array<{
    id: string
    label: string
    source: "catalog" | "source_repo" | "mounted" | "default"
    availability: "available" | "unknown" | "unavailable"
    recommended?: boolean
  }>
  default_version?: string
  selected_version?: string
  dataset_summary?: {
    dataset_id?: string
    name?: string
    subjects_count?: number
    sessions_count?: number
    modalities?: string[]
    tasks?: string[]
    source_repo?: string
    source_repo_id?: string
    access_type?: string
    source_version?: string
  }
  storage_summary?: {
    bids_path_available?: boolean
    bids_path?: string
    size_bytes?: number
    size_human?: string
    available_derivatives?: string[]
    derivatives?: Array<{
      kind: string
      path?: string
      available: boolean
    }>
  }
  files_summary?: {
    analysis_goal?: string
    required_total?: number
    required_passed?: number
    all_required_passed?: boolean
    total_matched_files?: number
    missing_patterns?: string[]
    groups?: Array<{
      name?: string
      patterns: string[]
      counts: Record<string, number>
      min_matches: number
      optional: boolean
      passed: boolean
    }>
  }
  mount_trace?: Array<{
    stage: string
    kind: string
    hit: boolean
    root?: string
    candidate?: string
    note?: string
  }>
  addresses: {
    openneuro_url?: string
    s3_uri?: string
    source_repo_url?: string
  }
  source_access?: {
    provider?: "openneuro" | "s3" | "http" | "other"
    bucket_uri?: string
    bucket_check?: {
      state?:
        | "verified_present"
        | "verified_absent"
        | "permission_denied"
        | "unreachable"
        | "not_applicable"
        | "unknown"
      method?: "openneuro_api" | "s3_list_objects" | "none"
      checked_at?: string
      message?: string
      latency_ms?: number
      cache_hit?: boolean
    }
    version_check?: {
      mode?: "verified" | "metadata_only"
      requested?: string
      resolved?: string
    }
    available_versions?: Array<{
      id: string
      label: string
      source: string
      state: "verified" | "metadata"
      created_at?: string
      recommended?: boolean
    }>
  }
  readiness?: {
    status?: string
    reason?: string
  }
  required_files?: {
    analysis_goal?: string
    required_total?: number
    required_passed?: number
    all_required_passed?: boolean
  }
  trace_summary?: Array<{
    stage: string
    kind: string
    hit: boolean
  }>
  unavailable?: boolean
  error?: string
}

export interface DatasetCardResponse {
  id: string
  name: string
  description?: string
  category?: string
  modalities: string[]
  acquisitions: string[]
  subjects_count?: number
  sessions_count?: number
  access_type: string
  license: string
  source_repo: string
  source_repo_id?: string
  primary_url: string
  center?: string
  consortium?: string
  tags: string[]
  tasks: string[]
  has_derivatives: boolean
  preview_media: DatasetPreview[]
  score?: number
  size_human?: string
  created_at?: string
  updated_at?: string
  onvoc?: {
    labels?: string[]
  }
}

export interface FacetValueResponse {
  value: string
  count: number
}

export interface DatasetSearchResponse {
  datasets: DatasetCardResponse[]
  total: number
  limit: number
  offset: number
  has_more: boolean
  search_time_ms: number
  facets: Record<string, FacetValueResponse[]>
  last_updated: string
  warnings?: string[]
  errors?: string[]
}

export interface DatasetDetailResponse extends DatasetCardResponse {
  species: string[]
  age_range?: { min: number; max: number; units: string }
  disease_flags: string[]
  subject_labels?: string[]
  phenotype_summary?: DatasetPhenotypeSummary[]
  annotation_sources?: string[]
  annotation_updated_at?: string
  approx_size_bytes?: number
  size_human?: string
  created_from?: string
  source_version?: string
  search_blob: string
  resource_addresses?: DatasetResourceAddresses
  onvoc?: {
    labels?: string[]
  }
}
