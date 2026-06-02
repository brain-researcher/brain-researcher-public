/* AUTO-GENERATED. DO NOT EDIT. */
/* Source: brain_researcher.core.contracts (Pydantic models) */

export interface IdsV1 {
  schema_version?: 'ids-v1'
  analysis_id?: string
  run_id?: string
  job_id?: string
  request_id?: string
  trace_id?: string
  workspace_id?: string
  user_id?: string
  session_id?: string
}

export interface PolicyRefV1 {
  schema_version?: 'policy-ref-v1'
  policy_id?: string
  policy_hash?: string
  policy_source?: string
  thresholds?: Record<string, any>
  notes?: string
}

export interface VersionRefV1 {
  schema_version?: 'version-ref-v1'
  contracts_version?: string
  brain_researcher_version?: string
  git_commit?: string
  tool_versions?: Record<string, string>
  image_digests?: Record<string, string>
}

export interface LoopSignalBaseV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type: 'condition_tag' | 'sensitivity_finding' | 'design_constraint' | 'hypothesis_delta' | 'user_feedback'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
}

export interface ConditionTagSignalV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type?: 'condition_tag'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
  condition_key: string
  condition_value: string
  conclusion?: string
  conflict_state?: string
}

export interface SensitivityFindingSignalV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type?: 'sensitivity_finding'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
  analysis_axis: string
  eta_squared: number
  stability_label?: string
  recommended_action?: string
}

export interface DesignConstraintSignalV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type?: 'design_constraint'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
  constraint_type: string
  target: string
  requirement: string
}

export interface HypothesisDeltaSignalV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type?: 'hypothesis_delta'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
  hypothesis_id: string
  delta_metric: string
  prior_value?: number
  posterior_value?: number
  delta_value?: number
}

export interface UserFeedbackSignalV1 {
  schema_version?: 'loop-signal-v1'
  signal_id?: string
  signal_type?: 'user_feedback'
  stage?: 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'unknown'
  run_id?: string
  plan_id?: string
  confidence?: number
  created_at?: string
  provenance?: Record<string, any>
  rating?: number
  helpful?: boolean
  feedback_text?: string
}

export interface ConditionConstraintV1 {
  condition_key: string
  condition_value: string
  expected_conclusion?: string
  source_signal_id?: string
}

export interface SensitivityConstraintV1 {
  analysis_axis: string
  min_eta_squared?: number
  recommendation?: string
  source_signal_id?: string
}

export interface DesignConstraintV1 {
  constraint_type: string
  target: string
  requirement: string
  source_signal_id?: string
}

export interface CrossStageContextV1 {
  schema_version?: 'cross-stage-context-v1'
  task_family?: string
  dataset_id?: string
  predicted_intents?: Array<string>
  condition_constraints?: Array<ConditionConstraintV1>
  sensitivity_constraints?: Array<SensitivityConstraintV1>
  design_constraints?: Array<DesignConstraintV1>
  notes?: Array<string>
}

export interface RunCardV1 {
  schema_version?: 'run-card-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  id?: string
  version?: string
  timestamp?: string
  title?: string
  description?: string
  execution?: Record<string, any>
  inputs?: Record<string, any>
  outputs?: Record<string, any> | Array<Record<string, any>>
  provenance?: Record<string, any>
  reproducibility?: Record<string, any>
  cross_stage_context?: CrossStageContextV1 | Record<string, any>
  loop_signals?: Array<ConditionTagSignalV1 | SensitivityFindingSignalV1 | DesignConstraintSignalV1 | HypothesisDeltaSignalV1 | UserFeedbackSignalV1>
  created_at?: string
  analysis?: Record<string, any>
  datasets?: Array<Record<string, any>>
  tools?: Array<Record<string, any>>
  parameters?: Record<string, any>
  citations?: Array<any>
  environment?: Record<string, any>
  reproducibility_score?: number
}

export interface TraceEventV1 {
  schema_version?: 'trace-event-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  run_id: string
  event_type: string
  timestamp: string
  event_id?: string
  payload?: Record<string, any>
}

export interface StreamEventV1 {
  schema_version?: 'stream-event-v1'
  ids?: IdsV1
  source_event_id: string
  event_type: string
  timestamp: string
  payload?: Record<string, any>
}

export interface ObservationSpecV1 {
  schema_version?: 'observation-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  job_id: string
  run_id?: string
  round_id?: string
  state: string
  created_at?: number
  started_at?: number
  finished_at?: number
  run_dir?: string
  files?: ObservationFiles
  inputs_manifest_ref?: string
  failure_summary?: string
  run_card?: RunCardV1 | Record<string, any>
  provenance?: Record<string, any>
  artifacts?: Array<Record<string, any>>
  steps?: Array<Record<string, any>>
  violations?: Array<Record<string, any>>
  diagnostics_summary?: Record<string, any>
  rm_pairwise?: RMLogMetadataV1 | Record<string, any>
  rm_process?: RMLogMetadataV1 | Record<string, any>
}

export interface ObservationFiles {
  observation_json?: string
  analysis_json?: string
  provenance_json?: string
  trace_jsonl?: string
  reward_breakdown_json?: string
  research_episode_json?: string
  option_set_json?: string
  evidence_gate_json?: string
  commitment_json?: string
  claim_report_json?: string
  claim_update_json?: string
  correction_summary_json?: string
  threshold_summary_json?: string
  thresholded_map?: string
  design_matrix?: string
  contrast_table?: string
  cluster_table?: string
  peak_table?: string
  rm_pairwise_redacted_json?: string
  rm_pairwise_raw_json?: string
  rm_process_redacted_json?: string
  rm_process_raw_json?: string
}

export interface RMLogMetadataV1 {
  schema_version?: 'rm-log-metadata-v1'
  policy?: string
  redacted_json?: string
  raw_json?: string
  redacted_checksum?: string
  raw_checksum?: string
  redacted_checksum_status?: string
  raw_checksum_status?: string
  redacted_checksum_reason?: string
  raw_checksum_reason?: string
  generated_at?: string
  metadata?: Record<string, any>
}

export interface AnalysisBundleV1 {
  schema_version?: 'analysis-bundle-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  job_id?: string
  run_id?: string
  state?: string
  created_at?: number
  started_at?: number
  finished_at?: number
  run_dir?: string
  generated_at: string
  evidence_index?: Array<string>
  qc_summary_ref?: string
  source_manifests?: Array<string>
  files?: AnalysisBundleFiles
  file_manifest?: Array<BundleFileEntry>
  observation?: Record<string, any>
  inputs_manifest?: Record<string, any>
  analysis_manifest?: Record<string, any>
  artifact_manifest?: Record<string, any>
  execution_manifest?: ExecutionManifestV1 | Record<string, any>
  reward_breakdown?: Record<string, any>
  trajectory?: Record<string, any>
  artifacts?: Array<Record<string, any>>
  run_card?: Record<string, any>
  review_context?: Record<string, any>
  provenance?: Record<string, any>
  cross_stage_context?: CrossStageContextV1 | Record<string, any>
  loop_signals?: Array<ConditionTagSignalV1 | SensitivityFindingSignalV1 | DesignConstraintSignalV1 | HypothesisDeltaSignalV1 | UserFeedbackSignalV1>
  evaluation?: EvaluationV1 | Record<string, any>
  policy_snapshot?: Record<string, any>
  rm_pairwise?: RMLogMetadataV1 | Record<string, any>
  rm_process?: RMLogMetadataV1 | Record<string, any>
}

export interface AnalysisBundleFiles {
  observation_json?: string
  inputs_manifest_json?: string
  analysis_json?: string
  artifact_manifest_json?: string
  trace_jsonl?: string
  trajectory_json?: string
  provenance_json?: string
  execution_manifest_json?: string
  analysis_script_py?: string
  run_script_sh?: string
  requirements_txt?: string
  environment_yml?: string
  docker_compose_yml?: string
  user_environment_yml?: string
  user_docker_compose_yml?: string
  user_env_example?: string
  user_quickstart_md?: string
  user_installation_md?: string
  reward_breakdown_json?: string
  research_episode_json?: string
  option_set_json?: string
  evidence_gate_json?: string
  commitment_json?: string
  claim_report_json?: string
  claim_update_json?: string
  correction_summary_json?: string
  threshold_summary_json?: string
  thresholded_map?: string
  design_matrix?: string
  contrast_table?: string
  cluster_table?: string
  peak_table?: string
  stdout_txt?: string
  stderr_txt?: string
  rm_pairwise_redacted_json?: string
  rm_pairwise_raw_json?: string
  rm_process_redacted_json?: string
  rm_process_raw_json?: string
}

export interface BundleFileEntry {
  role: string
  path: string
  size?: number
  checksum?: string
  checksum_status?: string
  checksum_reason?: string
  mime?: string
}

export interface TaskSpecV1 {
  schema_version?: 'task-spec-v1'
  task_id: string
  name?: string
  description?: string
  inputs?: Record<string, any>
  budget?: Record<string, any>
  expected_outputs?: Array<Record<string, any>>
  allowlist?: Record<string, any>
  scoring?: Record<string, any>
  tags?: Array<string>
  metadata?: Record<string, any>
}

export interface ScorecardV1 {
  schema_version?: 'scorecard-v1'
  task_id?: string
  run_id?: string
  job_id?: string
  overall_score?: number
  passed?: boolean
  metrics?: Record<string, number>
  breakdown?: Record<string, any>
  generated_at?: string
  evaluator?: Record<string, any>
  notes?: string
}

export interface EvaluationV1 {
  schema_version?: 'evaluation-v1'
  task?: TaskSpecV1 | Record<string, any>
  scorecard?: ScorecardV1 | Record<string, any>
  harbor?: Record<string, any>
  metadata?: Record<string, any>
}

export interface ExecutionEntrypointsV1 {
  python_script?: string
  shell_script?: string
  environment_file?: string
  docker_compose?: string
}

export interface ExecutionIORefV1 {
  name: string
  kind?: 'file' | 'directory' | 'uri' | 'value'
  required?: boolean
  description?: string
  path?: string
}

export interface ExecutionManifestV1 {
  schema_version?: 'execution-manifest-v1'
  execution_mode?: 'python_script' | 'shell_script' | 'docker_compose' | 'neurodesk' | 'mixed' | 'unknown'
  summary?: string
  entrypoints?: ExecutionEntrypointsV1
  runtime?: ExecutionRuntimeV1
  inputs?: Array<ExecutionIORefV1>
  outputs?: Array<ExecutionIORefV1>
  parameters?: Record<string, any>
  repro?: ExecutionReproV1
  neurodesk?: NeurodeskExecutionV1
}

export type ExecutionModeV1 = 'python_script' | 'shell_script' | 'docker_compose' | 'neurodesk' | 'mixed' | 'unknown'

export interface ExecutionReproV1 {
  working_directory?: string
  command?: string
  notes?: string
}

export interface ExecutionRuntimeV1 {
  python_version?: string
  docker_supported?: boolean
  neurodesk_supported?: boolean
}

export interface NeurodeskExecutionV1 {
  modules?: Array<string>
  container_paths?: Array<string>
  command_template?: string
}

export interface ArtifactV1 {
  schema_version?: 'artifact-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  artifact_id?: string
  job_id?: string
  kind: 'file' | 'json' | 'blob' | 'bundle' | 'log' | 'trace'
  media_type?: string
  uri: string
  sha256?: string
  bytes?: number
  created_at?: number
  tags?: Array<string>
  metadata?: Record<string, any>
}

export interface JobSpecV1 {
  schema_version?: 'job-spec-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  prompt?: string
  pipeline?: string
  parameters?: Record<string, any>
  metadata?: Record<string, any>
}

export interface JobRecordV1 {
  schema_version?: 'job-record-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  job_id: string
  status: 'pending' | 'queued' | 'claimed' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'cancelling' | 'timeout' | 'skipped' | 'paused' | 'retrying'
  kind?: string
  spec?: JobSpecV1 | Record<string, any>
  payload_json?: string
  priority?: number
  created_at?: number
  queued_at?: number
  claimed_at?: number
  started_at?: number
  finished_at?: number
  run_after?: number
  worker_id?: string
  lease_expires_at?: number
  last_heartbeat?: number
  attempt?: number
  max_attempts?: number
  run_id?: string
  run_dir?: string
  provenance_path?: string
  exit_code?: number
  error_message?: string
  cancellation_requested?: boolean
  cancel_reason?: string
  skip_reason?: string
  gpu_req?: number
  gpu_type?: string
  cpus?: number
  memory_gb?: number
  walltime_minutes?: number
  backend?: string
  job_name?: string
  user_id?: string
  session_id?: string
  project_id?: string
  artifacts?: Array<ArtifactV1>
}

export interface ProvenanceTimestampsV1 {
  started_at?: number
  finished_at?: number
  duration_sec?: number
}

export interface ProvenanceRuntimeV1 {
  container?: Record<string, any>
  sandbox?: Record<string, any>
  host?: Record<string, any>
  git?: Record<string, any>
}

export interface ProvenanceV1 {
  schema_version?: 'provenance-v1'
  ids?: IdsV1
  policy?: PolicyRefV1
  versions?: VersionRefV1
  run_id: string
  kind?: 'tool' | 'step' | 'workflow' | 'stage' | 'pipeline'
  status?: 'scheduled' | 'running' | 'succeeded' | 'failed' | 'partial' | 'timeout' | 'cancelled'
  timestamps?: ProvenanceTimestampsV1
  command?: Array<string>
  parameters?: Record<string, any>
  inputs?: Array<ArtifactV1>
  outputs?: Array<ArtifactV1>
  exit_code?: number
  error_message?: string
  runtime?: ProvenanceRuntimeV1
  resources?: Record<string, any>
  logs?: Record<string, any>
  metadata?: Record<string, any>
}

export interface AnalysisStreamBaseEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type: string
}

export interface JobStartedPayloadV1 {
  status?: 'pending' | 'queued' | 'claimed' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'cancelling' | 'timeout' | 'skipped' | 'paused' | 'retrying'
  message?: string
}

export interface JobStartedEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'job.started'
  payload?: JobStartedPayloadV1
}

export interface ToolCallStartedPayloadV1 {
  tool_call_id: string
  tool_id: string
  params?: Record<string, any>
}

export interface ToolCallStartedEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'tool.call.started'
  payload: ToolCallStartedPayloadV1
}

export interface ToolCallFinishedPayloadV1 {
  tool_call_id: string
  status: 'running' | 'succeeded' | 'failed' | 'timeout' | 'cancelled' | 'partial'
  artifacts?: Array<ArtifactV1>
  error_message?: string
}

export interface ToolCallFinishedEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'tool.call.finished'
  payload: ToolCallFinishedPayloadV1
}

export interface ArtifactWrittenPayloadV1 {
  artifact: ArtifactV1
}

export interface ArtifactWrittenEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'artifact.written'
  payload: ArtifactWrittenPayloadV1
}

export interface LogLinePayloadV1 {
  stream: 'stdout' | 'stderr'
  line: string
}

export interface LogLineEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'log.line'
  payload: LogLinePayloadV1
}

export interface ObservationAppendedPayloadV1 {
  observation: ArtifactV1
}

export interface ObservationAppendedEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'observation.appended'
  payload: ObservationAppendedPayloadV1
}

export interface StagePayloadV1 {
  stage: string
  status: 'scheduled' | 'started' | 'retrying' | 'completed' | 'warned' | 'blocked' | 'failed' | 'skipped'
  stage_id?: string
  tool_id?: string
  attempt?: number
  duration_ms?: number
  message?: string
  details?: Record<string, any>
}

export interface StageEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'stage'
  payload: StagePayloadV1
}

export interface WarningPayloadV1 {
  message: string
  code?: string
  details?: Record<string, any>
}

export interface WarningEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'warning'
  payload: WarningPayloadV1
}

export interface MetricPayloadV1 {
  name: string
  value: number
  unit?: string
  tags?: Record<string, string>
  details?: Record<string, any>
}

export interface MetricEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'metric'
  payload: MetricPayloadV1
}

export interface AnalysisCompletedPayloadV1 {
  status: 'pending' | 'queued' | 'claimed' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'cancelling' | 'timeout' | 'skipped' | 'paused' | 'retrying'
  message?: string
}

export interface AnalysisCompletedEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'analysis.completed'
  payload: AnalysisCompletedPayloadV1
}

export interface ErrorPayloadV1 {
  message: string
  error_class?: string
  details?: Record<string, any>
}

export interface ErrorEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'error'
  payload: ErrorPayloadV1
}

export interface UnknownEventPayloadV1 {
  raw_event_type: string
  raw_payload?: Record<string, any>
}

export interface UnknownEventV1 {
  schema_version?: 'analysis-stream-event-v1'
  ids?: IdsV1
  seq: number
  timestamp: string
  event_type?: 'unknown'
  payload: UnknownEventPayloadV1
}

export type AnalysisStreamEventV1 = JobStartedEventV1 | ToolCallStartedEventV1 | ToolCallFinishedEventV1 | ArtifactWrittenEventV1 | LogLineEventV1 | ObservationAppendedEventV1 | StageEventV1 | WarningEventV1 | MetricEventV1 | AnalysisCompletedEventV1 | ErrorEventV1 | UnknownEventV1
