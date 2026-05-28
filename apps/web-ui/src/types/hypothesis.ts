export type HypothesisStatus =
  | 'open'
  | 'provisional'
  | 'selected'
  | 'rejected'
  | 'verified'

export type AgentName = 'explorer' | 'critic' | 'verifier' | 'ranker'

export type AgentTraceStatus = 'ok' | 'warning' | 'error' | 'pending'

export type OpenQuestionStatus = 'open' | 'in_progress' | 'resolved'

export type BatchRunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'review_blocked'

export type ProgressStage = 'clarifying' | 'running' | 'completed' | 'failed'
export type HypothesisRunState = 'clarifying' | 'running' | 'completed' | 'failed'
export type HypothesisArtifactKind =
  | 'hypothesis_canvas'
  | 'evidence_pack'
  | 'deep_research_report'
  | 'kg_compare'
  | 'candidate_cards'
  | 'hot_load_trajectory'
  | 'workflow_plan'
  | 'validation_report'

export type WorkflowStage =
  | 'clarify'
  | 'canvas'
  | 'candidates'
  | 'research_preview'
  | 'research_ready'
  | 'plan'
  | 'triage'
  | 'blocked'
  | 'ready_to_run'

export type ResearchGoal =
  | 'mechanism_explanation'
  | 'predictive_modeling'
  | 'intervention_effect'
  | 'replication_dispute'

export type ResearchModality =
  | 'fmri_task'
  | 'fmri_rest'
  | 'eeg'
  | 'behavioral'
  | 'multimodal'

export type ValidationTriageStatus = 'fixable' | 'non_fixable' | 'unknown'

export type ValidationOutcomeStatus = 'pass' | 'warn' | 'fail'

export type ValidationFailureCode =
  | 'DATA_UNAVAILABLE'
  | 'HYPOTHESIS_UNDERSPECIFIED'
  | 'MODALITY_MISMATCH'
  | 'METHOD_INCOMPATIBLE'
  | 'CONFOUND_UNCONTROLLED'
  | 'UNKNOWN'

export type HypothesisEvidenceKind = 'paper' | 'dataset' | 'experiment' | 'note' | 'other'
export type EvidenceQualityTier = 'primary' | 'secondary' | 'tertiary'
export type CandidateGroundingStatus = 'grounded' | 'weak_grounded' | 'draft_unverified'

export interface EvidenceAnchor {
  evidence_id: string
  label: string
  kind: HypothesisEvidenceKind
  reason?: string | null
  source_channel?:
    | 'graph'
    | 'deep_research_live'
    | 'deep_research_pending'
    | 'file_search_live'
    | 'workflow_fallback'
    | 'other'
  confidence?: number | null
  overlap_score?: number | null
  quality_tier?: EvidenceQualityTier | null
  traceability_score?: number | null
}

export interface HypothesisScore {
  total_score: number | null
  novelty: number | null
  coherence: number | null
  leverage: number | null
  feasibility: number | null
  risk: number | null
}

export interface AgentTrace {
  agent: AgentName
  status: AgentTraceStatus
  summary: string
  details: string[]
  updated_at?: string | null
}

export interface HypothesisEvidenceItem {
  id: string
  label: string
  kind: HypothesisEvidenceKind
  summary?: string | null
  synthetic_summary?: boolean | null
  url?: string | null
  raw_url?: string | null
  display_url?: string | null
  source_host?: string | null
  source_channel?:
    | 'graph'
    | 'deep_research_live'
    | 'deep_research_pending'
    | 'file_search_live'
    | 'workflow_fallback'
    | 'other'
  path_type?: string | null
  support_count?: number | null
  freshness_ts?: string | null
  confidence?: number | null
  source_type?: 'paper' | 'dataset' | 'other' | null
  quality_tier?: EvidenceQualityTier | null
  traceability_score?: number | null
  /** Normalized ID for cross-database dedupe (e.g. PMID when available; PMC→PMID resolved). */
  canonical_id?: string | null
}

export interface MDEPlan {
  id: string
  objective: string
  minimal_test: string
  falsifier: string
  expected_signals: string[]
  confounds: string[]
  cost_estimate?: string | null
  status?: BatchRunStatus | 'draft' | 'ready'
}

export interface HypothesisCandidate {
  id: string
  title: string
  statement: string
  status: HypothesisStatus
  tags: string[]
  open_question_id?: string | null
  rationale?: string | null
  score: HypothesisScore
  traces: AgentTrace[]
  mde: MDEPlan | null
  evidence: HypothesisEvidenceItem[]
  created_at?: string | null
  updated_at?: string | null
}

export interface OpenQuestion {
  id: string
  title: string
  description: string
  status: OpenQuestionStatus
  priority?: 'high' | 'medium' | 'low'
  leverage_hint?: string | null
}

export interface HypothesisContext {
  session_id?: string | null
  dataset_id?: string | null
  concept_id?: string | null
  task_id?: string | null
  thread_id?: string | null
}

export interface HypothesisSession {
  session_id: string
  context: HypothesisContext
  open_questions: OpenQuestion[]
  candidates: HypothesisCandidate[]
  messages?: HypothesisChatMessage[]
  selected_hypothesis_id?: string | null
  leaderboard_url?: string | null
  updated_at?: string | null
}

export interface BatchRunSummary {
  run_id: string
  status: BatchRunStatus
  queued_count?: number
  started_at?: string | null
  updated_at?: string | null
  leaderboard_url?: string | null
}

export interface HypothesisChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
}

export interface ProgressEvent {
  stage: ProgressStage
  message: string
  metrics?: Record<string, number>
  ts: string
}

export interface HypothesisIntentSummary {
  term: string | null
  goal?: ResearchGoal | null
  modality?: ResearchModality | null
  population?: string | null
  output_mode?: 'three_options' | 'single_best' | 'direct_plan' | null
  intent_ready: boolean
  missing_fields: string[]
}

export interface HypothesisArtifactEnvelope {
  id: string
  kind: HypothesisArtifactKind
  payload: Record<string, unknown>
  updated_at: string
}

export interface HypothesisRunSnapshot {
  run_id: string
  session_id: string
  state: HypothesisRunState
  intent_summary: HypothesisIntentSummary
  started_at: string
  updated_at: string
  done: boolean
  error_message?: string | null
  artifacts: HypothesisArtifactEnvelope[]
}

export interface HypothesisRunStartResponse {
  run_id: string
  session_id: string
  state: HypothesisRunState
  intent_ready: boolean
  intent_summary: HypothesisIntentSummary
  assistant_message?: string | null
}

export interface HypothesisRunEventBase {
  type:
    | 'run_state'
    | 'assistant_message'
    | 'stage'
    | 'artifact_upsert'
    | 'metric'
    | 'error'
    | 'done'
  run_id: string
  seq: number
  ts: string
}

export interface HypothesisRunStateEvent extends HypothesisRunEventBase {
  type: 'run_state'
  payload: {
    state: HypothesisRunState
    message?: string
  }
}

export interface HypothesisAssistantMessageEvent extends HypothesisRunEventBase {
  type: 'assistant_message'
  payload: {
    content: string
  }
}

export interface HypothesisStageEvent extends HypothesisRunEventBase {
  type: 'stage'
  payload: {
    stage_name: string
    message: string
    progress?: number
  }
}

export interface HypothesisArtifactUpsertEvent extends HypothesisRunEventBase {
  type: 'artifact_upsert'
  payload: {
    artifact: HypothesisArtifactEnvelope
  }
}

export interface HypothesisMetricEvent extends HypothesisRunEventBase {
  type: 'metric'
  payload: {
    name: string
    value: number
    unit?: string
  }
}

export interface HypothesisErrorEvent extends HypothesisRunEventBase {
  type: 'error'
  payload: {
    message: string
  }
}

export interface HypothesisDoneEvent extends HypothesisRunEventBase {
  type: 'done'
  payload: {
    summary: string
    final_state: HypothesisRunState
  }
}

export type HypothesisRunEvent =
  | HypothesisRunStateEvent
  | HypothesisAssistantMessageEvent
  | HypothesisStageEvent
  | HypothesisArtifactUpsertEvent
  | HypothesisMetricEvent
  | HypothesisErrorEvent
  | HypothesisDoneEvent

export interface ClarifyQuestionOption {
  id: string
  label: string
}

export interface ClarifyQuestion {
  id: string
  prompt: string
  options: ClarifyQuestionOption[]
}

export interface HypothesisCanvas {
  term: string
  goal: ResearchGoal
  modality: ResearchModality
  population: string
  primary_outcome: string
  constraints: string
  research_question: string
}

export interface DirectionCandidate {
  id: string
  title: string
  hypothesis: string
  independent_variable: string
  dependent_variable: string
  expected_signal: string
  likely_data_source: string
  novelty_gap: string
  risk_note: string
  minimal_discriminating_test?: string | null
  falsifier_hint?: string | null
  taste_axis?: string | null
  pattern_id?: string
  pattern_label?: string
  claim?: string
  evidence_anchors?: EvidenceAnchor[]
  grounding_status?: CandidateGroundingStatus
  confidence?: number | null
  semantic_alignment?: number | null
  anchor_quality?: {
    primary: number
    secondary: number
    tertiary: number
  } | null
  anchor_dim?: string | null
  anchor_source?: 'kg' | 'evidence' | 'kg_compare' | 'hybrid' | null
  anchor_evidence_ids?: string[]
  diversity_retry_count?: number | null
  fallback_reasons?: string[]
  share_allowed?: boolean
}

export interface ResearchPreview {
  coverage_scope: string[]
  estimated_minutes: number
  estimated_credits: number
  risk_level: 'low' | 'medium' | 'high'
  known_gaps: string[]
}

export interface WorkflowPlan {
  id: string
  mvp_steps: string[]
  full_steps: string[]
  falsifier: string
  success_criteria: string[]
  assumptions: string[]
}

export interface ValidationCheck {
  id: string
  label: string
  status: 'pass' | 'warn' | 'fail'
  detail: string
}

export interface BlockedReport {
  why_not: string
  alternatives: string[]
  required_inputs: string[]
}

export interface ValidationTriage {
  status: ValidationTriageStatus
  reason_codes: ValidationFailureCode[]
  user_actions: string[]
}

export interface ValidationReport {
  status: ValidationOutcomeStatus
  triage: ValidationTriage
  checks: ValidationCheck[]
  blocked_report?: BlockedReport | null
}

export interface PlanPatchResult {
  summary: string
  changed_steps: string[]
  patched_plan: WorkflowPlan
}
