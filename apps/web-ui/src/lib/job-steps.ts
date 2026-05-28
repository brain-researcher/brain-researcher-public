export interface StepSummary {
  step_id: string
  name?: string
  state: string
  execution_time_ms?: number
  run_dir?: string
  error?: string
}

export interface JobStepsResponse {
  job_id: string
  state: string
  steps: StepSummary[]
  cache_key?: string
  cache_hit?: boolean
}

export type StepState =
  | 'pending'
  | 'running'
  | 'queued'
  | 'claimed'
  | 'succeeded'
  | 'completed'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'skipped'
  | 'retrying'

export interface StepsUpdateEvent {
  event: 'steps_update'
  data: JobStepsResponse
  id: string
}

export interface StepsCompleteEvent {
  event: 'complete'
  data: {
    final_state: string
    job_id: string
    total_steps: number
  }
}

export interface StepsPingEvent {
  event: 'ping'
  data: {
    timestamp: number
    job_id: string
  }
}

export interface StepsErrorEvent {
  event: 'error'
  data: {
    error: string
    status_code?: number
  }
}

export type StepsSSEEvent =
  | StepsUpdateEvent
  | StepsCompleteEvent
  | StepsPingEvent
  | StepsErrorEvent
