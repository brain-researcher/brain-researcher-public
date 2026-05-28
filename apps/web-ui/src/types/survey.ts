/**
 * TypeScript type definitions for the Survey System
 * Comprehensive types for surveys, questions, responses, and analytics
 */

export type SurveyStatus = 'draft' | 'active' | 'paused' | 'completed' | 'archived';

export type QuestionType = 
  | 'multiple_choice'
  | 'single_choice'
  | 'text'
  | 'textarea'
  | 'scale'
  | 'matrix'
  | 'neuroimaging_protocol'
  | 'brain_region'
  | 'cognitive_battery'
  | 'medication_history'
  | 'scanner_parameters';

export type TriggerType = 
  | 'analysis_complete'
  | 'data_upload'
  | 'study_milestone'
  | 'time_based'
  | 'user_action'
  | 'system_event'
  | 'quality_threshold'
  | 'completion_rate'
  | 'neuroimaging_pipeline';

export type InsightType = 
  | 'sentiment_analysis'
  | 'response_patterns'
  | 'completion_trends'
  | 'demographic_analysis'
  | 'neuroimaging_correlations'
  | 'quality_assessment'
  | 'comparative_analysis'
  | 'predictive_insights'
  | 'anomaly_detection';

export type DistributionType = 'manual' | 'scheduled' | 'triggered';
export type NotificationMethod = 'email' | 'in_app' | 'push';
export type CompletionStatus = 'in_progress' | 'completed' | 'abandoned';

// Core Survey Types

export interface Survey {
  id: string;
  title: string;
  description?: string;
  category: string;
  creator_id: string;
  target_audience?: string;
  settings: SurveySettings;
  neuroimaging_context?: NeuroimagingContext;
  status: SurveyStatus;
  created_at: string;
  updated_at?: string;
  published_at?: string;
  expires_at?: string;
  expected_responses: number;
  max_responses?: number;
  questions?: SurveyQuestion[];
  analytics?: SurveyAnalytics;
}

export interface SurveySettings {
  theme?: SurveyTheme;
  logic?: SurveyLogic;
  validation?: ValidationSettings;
  reminders?: ReminderSettings;
  privacy?: PrivacySettings;
  customization?: CustomizationSettings;
}

export interface SurveyTheme {
  primary_color: string;
  secondary_color: string;
  font_family: string;
  background_color?: string;
  logo_url?: string;
  custom_css?: string;
}

export interface SurveyLogic {
  conditional_questions?: ConditionalLogic[];
  skip_logic?: SkipLogic[];
  randomization?: RandomizationSettings;
  branching?: BranchingRule[];
}

export interface ValidationSettings {
  require_all_questions: boolean;
  email_validation: boolean;
  phone_validation: boolean;
  custom_validators?: CustomValidator[];
}

export interface ReminderSettings {
  enabled: boolean;
  frequency: 'daily' | 'weekly' | 'custom';
  max_reminders: number;
  custom_message?: string;
}

export interface PrivacySettings {
  anonymous_responses: boolean;
  collect_ip: boolean;
  data_retention_days?: number;
  gdpr_compliant: boolean;
}

export interface CustomizationSettings {
  progress_bar: boolean;
  question_numbering: boolean;
  save_and_continue: boolean;
  mobile_optimized: boolean;
}

// Neuroimaging-Specific Types

export interface NeuroimagingContext {
  study_type?: string[];
  imaging_modalities?: string[];
  analysis_software?: string[];
  data_sharing?: boolean;
  ethics_approval?: boolean;
}

export interface BrainRegion {
  name: string;
  atlas?: string;
  coordinates?: {
    x: number;
    y: number;
    z: number;
  };
  hemisphere?: 'left' | 'right' | 'bilateral';
}

export interface CognitiveDomain {
  name: string;
  subcategories?: string[];
  assessments?: string[];
}

export interface ScannerParameters {
  field_strength: string;
  manufacturer: string;
  pulse_sequence: string;
  voxel_size?: number[];
  repetition_time?: number;
  echo_time?: number;
  flip_angle?: number;
}

// Question Types

export interface SurveyQuestion {
  id: string;
  survey_id: string;
  question_text: string;
  question_type: QuestionType;
  description?: string;
  options: QuestionOptions;
  validation_rules: ValidationRules;
  conditional_logic?: ConditionalLogic;
  neuroimaging_context?: QuestionNeuroimagingContext;
  cognitive_domain?: string;
  order_index: number;
  required: boolean;
  randomize_options: boolean;
}

export interface QuestionOptions {
  // Multiple choice / single choice
  choices?: ChoiceOption[];
  other_option?: boolean;
  
  // Scale questions
  scale_type?: 'numeric' | 'likert' | 'visual_analog';
  scale_min?: number;
  scale_max?: number;
  scale_labels?: string[];
  
  // Matrix questions
  rows?: string[];
  columns?: string[];
  
  // Text questions
  max_length?: number;
  min_length?: number;
  input_type?: 'text' | 'email' | 'number' | 'url';
  
  // Neuroimaging-specific options
  brain_regions?: BrainRegion[];
  cognitive_assessments?: CognitiveDomain[];
  scanner_parameters?: ScannerParameters;
  medication_categories?: string[];
  custom_allowed?: boolean;
}

export interface ChoiceOption {
  id: string;
  text: string;
  value: string | number;
  description?: string;
  image_url?: string;
  neuroimaging_metadata?: Record<string, any>;
}

export interface ValidationRules {
  required?: boolean;
  min_value?: number;
  max_value?: number;
  regex_pattern?: string;
  custom_message?: string;
  neuroimaging_validation?: NeuroimagingValidation;
}

export interface NeuroimagingValidation {
  valid_modalities?: string[];
  required_parameters?: string[];
  coordinate_validation?: boolean;
  atlas_validation?: string;
}

export interface QuestionNeuroimagingContext {
  category: string;
  required_for?: string[];
  atlas_support?: boolean;
  synchronized_with_imaging?: boolean;
  statistical_covariates?: boolean;
}

// Logic and Conditional Types

export interface ConditionalLogic {
  condition_id: string;
  target_question_id: string;
  operator: 'equals' | 'not_equals' | 'contains' | 'greater_than' | 'less_than';
  value: any;
  action: 'show' | 'hide' | 'require' | 'skip';
}

export interface SkipLogic {
  question_id: string;
  conditions: ConditionalLogic[];
  skip_to_question?: string;
  skip_to_section?: string;
  end_survey?: boolean;
}

export interface RandomizationSettings {
  randomize_questions: boolean;
  randomize_options: boolean;
  randomization_groups?: RandomizationGroup[];
}

export interface RandomizationGroup {
  group_id: string;
  question_ids: string[];
  randomize_order: boolean;
}

export interface BranchingRule {
  rule_id: string;
  condition: ConditionalLogic;
  branch_to: string;
  description?: string;
}

export interface CustomValidator {
  validator_id: string;
  function_name: string;
  parameters: Record<string, any>;
  error_message: string;
}

// Response Types

export interface SurveyResponse {
  id: string;
  survey_id: string;
  participant_id: string;
  responses: Record<string, any>;
  metadata: ResponseMetadata;
  session_data: SessionData;
  completion_status: CompletionStatus;
  started_at: string;
  submitted_at?: string;
  completion_time_seconds?: number;
  quality_score?: number;
  flagged_for_review: boolean;
  review_notes?: string;
}

export interface ResponseMetadata {
  device_type?: string;
  browser?: string;
  screen_resolution?: string;
  completion_time_seconds?: number;
  quality_score?: number;
  partial_responses?: Record<string, any>;
}

export interface SessionData {
  session_id: string;
  user_agent?: string;
  ip_address?: string;
  referrer?: string;
  utm_parameters?: Record<string, string>;
}

// Distribution and Trigger Types

export interface SurveyDistribution {
  id: string;
  survey_id: string;
  distribution_type: DistributionType;
  schedule_config?: ScheduleConfig;
  target_criteria: TargetCriteria;
  status: string;
  created_at: string;
  activated_at?: string;
  completed_at?: string;
  sent_count: number;
  opened_count: number;
  response_count: number;
}

export interface ScheduleConfig {
  start_date?: string;
  end_date?: string;
  cron_expression?: string;
  timezone?: string;
  recurring?: boolean;
  frequency?: 'daily' | 'weekly' | 'monthly';
}

export interface TargetCriteria {
  audience?: string;
  user_ids?: string[];
  roles?: string[];
  study_participants?: string;
  custom_filters?: Record<string, any>;
}

export interface SurveyTrigger {
  id: string;
  survey_id: string;
  trigger_type: TriggerType;
  trigger_conditions: TriggerConditions;
  trigger_data: Record<string, any>;
  status: string;
  created_at: string;
  last_triggered_at?: string;
  trigger_count: number;
}

export interface TriggerConditions {
  user_id?: string;
  event_data?: Record<string, any>;
  time?: TimeConditions;
  neuroimaging_events?: NeuroimagingTriggerEvents;
}

export interface TimeConditions {
  day_of_week?: string[];
  time_range?: {
    start: string;
    end: string;
  };
  delay_minutes?: number;
}

export interface NeuroimagingTriggerEvents {
  pipeline_stages?: string[];
  quality_thresholds?: Record<string, number>;
  analysis_types?: string[];
  data_types?: string[];
}

// Analytics and Insights Types

export interface SurveyAnalytics {
  total_responses: number;
  completion_rate: number;
  average_completion_time?: number;
  response_rate?: number;
  quality_metrics?: QualityMetrics;
  demographic_breakdown?: DemographicBreakdown;
  insights?: SurveyInsight[];
}

export interface QualityMetrics {
  average_quality_score: number;
  high_quality_responses: number;
  flagged_responses: number;
  completion_time_analysis: CompletionTimeAnalysis;
}

export interface CompletionTimeAnalysis {
  average_seconds: number;
  median_seconds: number;
  fast_completions: number;
  slow_completions: number;
}

export interface DemographicBreakdown {
  age_distribution?: AgeDistribution;
  gender_distribution?: Record<string, number>;
  education_distribution?: Record<string, number>;
  geographic_distribution?: Record<string, number>;
}

export interface AgeDistribution {
  mean: number;
  median: number;
  ranges: Record<string, number>;
}

export interface SurveyInsight {
  id: string;
  survey_id: string;
  insight_type: InsightType;
  title: string;
  description: string;
  confidence_score: number;
  supporting_data: Record<string, any>;
  methodology: MethodologyInfo;
  generated_at: string;
  generated_by: string;
  review_status: string;
}

export interface MethodologyInfo {
  algorithm: string;
  parameters?: Record<string, any>;
  data_sources?: string[];
  limitations?: string[];
}

// Template Types

export interface SurveyTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  neuroimaging_focus: string[];
  study_types: string[];
  cognitive_domains: string[];
  template_questions: TemplateQuestion[];
  default_settings: SurveySettings;
  usage_count: number;
  created_at: string;
  created_by: string;
  tags: string[];
  is_public: boolean;
}

export interface TemplateQuestion {
  question_text: string;
  question_type: QuestionType;
  options: QuestionOptions;
  validation_rules: ValidationRules;
  neuroimaging_context?: QuestionNeuroimagingContext;
  required: boolean;
  description?: string;
}

// Notification Types

export interface SurveyNotification {
  id: string;
  survey_id: string;
  participant_id: string;
  notification_type: string;
  title: string;
  message: string;
  delivery_method: NotificationMethod;
  delivery_config: DeliveryConfig;
  status: string;
  scheduled_for?: string;
  sent_at?: string;
  delivered_at?: string;
  opened_at?: string;
  clicked_at?: string;
  error_message?: string;
  retry_count: number;
  max_retries: number;
}

export interface DeliveryConfig {
  email_template?: string;
  subject_line?: string;
  sender_info?: {
    name: string;
    email: string;
  };
  push_config?: {
    title: string;
    body: string;
    icon?: string;
  };
}

// API Request/Response Types

export interface CreateSurveyRequest {
  title: string;
  description?: string;
  category: string;
  questions: Partial<SurveyQuestion>[];
  settings?: Partial<SurveySettings>;
  target_audience?: string;
  distribution_type?: DistributionType;
  schedule_config?: ScheduleConfig;
  trigger_config?: Partial<SurveyTrigger>;
}

export interface UpdateSurveyRequest {
  title?: string;
  description?: string;
  questions?: Partial<SurveyQuestion>[];
  settings?: Partial<SurveySettings>;
  status?: SurveyStatus;
}

export interface SubmitResponseRequest {
  survey_id: string;
  participant_id?: string;
  responses: Record<string, any>;
  metadata?: Partial<ResponseMetadata>;
  session_data?: Partial<SessionData>;
}

export interface AnalyticsRequest {
  survey_ids?: string[];
  date_range?: {
    start: string;
    end: string;
  };
  metrics: string[];
  filters?: Record<string, any>;
}

export interface AnalyticsResponse {
  analytics: Record<string, any>;
  generated_at: string;
  survey_count: number;
}

// UI Component Types

export interface SurveyBuilderState {
  survey: Partial<Survey>;
  questions: SurveyQuestion[];
  current_question_index: number;
  preview_mode: boolean;
  unsaved_changes: boolean;
  validation_errors: Record<string, string>;
}

export interface QuestionEditorProps {
  question: Partial<SurveyQuestion>;
  onChange: (question: Partial<SurveyQuestion>) => void;
  onSave: () => void;
  onCancel: () => void;
  neuroimaging_templates?: TemplateQuestion[];
}

export interface SurveyDisplayProps {
  survey: Survey;
  responses?: Record<string, any>;
  onResponseChange: (questionId: string, value: any) => void;
  onSubmit: (responses: Record<string, any>) => void;
  readonly?: boolean;
}

export interface AnalyticsDashboardProps {
  survey_ids: string[];
  date_range?: {
    start: string;
    end: string;
  };
  refresh_interval?: number;
}

// Error Types

export interface SurveyError {
  code: string;
  message: string;
  field?: string;
  details?: Record<string, any>;
}

// Utility Types

export type SurveyOperationResult<T = any> = {
  success: boolean;
  data?: T;
  error?: SurveyError;
  message?: string;
};

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
};

// Constants for type validation and UI

export const QUESTION_TYPES: { value: QuestionType; label: string; neuroimaging?: boolean }[] = [
  { value: 'multiple_choice', label: 'Multiple Choice' },
  { value: 'single_choice', label: 'Single Choice' },
  { value: 'text', label: 'Text Input' },
  { value: 'textarea', label: 'Text Area' },
  { value: 'scale', label: 'Scale/Rating' },
  { value: 'matrix', label: 'Matrix' },
  { value: 'neuroimaging_protocol', label: 'Neuroimaging Protocol', neuroimaging: true },
  { value: 'brain_region', label: 'Brain Region Selection', neuroimaging: true },
  { value: 'cognitive_battery', label: 'Cognitive Assessment', neuroimaging: true },
  { value: 'medication_history', label: 'Medication History', neuroimaging: true },
  { value: 'scanner_parameters', label: 'Scanner Parameters', neuroimaging: true },
];

export const SURVEY_CATEGORIES = [
  'demographic_survey',
  'cognitive_assessment',
  'user_feedback',
  'quality_assessment',
  'post_analysis_feedback',
  'data_quality',
  'dataset_description',
  'baseline_assessment',
  'followup_assessment',
  'neuroimaging_protocol'
];

export const NEUROIMAGING_MODALITIES = [
  'fMRI',
  'sMRI',
  'DTI',
  'EEG',
  'MEG',
  'PET',
  'SPECT',
  'fNIRS'
];

export const COGNITIVE_DOMAINS = [
  'attention',
  'memory',
  'executive_function',
  'language',
  'visuospatial',
  'motor',
  'social_cognition',
  'emotion'
];

export const BRAIN_REGIONS = [
  'prefrontal_cortex',
  'temporal_lobe',
  'parietal_lobe',
  'occipital_lobe',
  'hippocampus',
  'amygdala',
  'thalamus',
  'basal_ganglia',
  'cerebellum',
  'brainstem',
  'insula',
  'cingulate_cortex',
  'motor_cortex',
  'somatosensory_cortex',
  'visual_cortex',
  'auditory_cortex'
];

export const SCANNER_PARAMETERS = [
  'field_strength',
  'manufacturer',
  'pulse_sequence',
  'voxel_size',
  'repetition_time',
  'echo_time',
  'flip_angle',
  'acquisition_matrix',
  'slice_thickness',
  'slice_gap'
];
