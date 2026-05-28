export interface PipelineNodeDefinition {
  id: string
  label: string
  tool?: string | null
  type?: string | null
  category?: string | null
  parameters?: Record<string, any>
  metadata?: Record<string, any>
  config?: Record<string, any>
  position?: Record<string, any> | null
}

export interface PipelineEdgeDefinition {
  id?: string | null
  source: string
  target: string
  label?: string | null
  metadata?: Record<string, any>
}

export interface ExecutePipelinePayload {
  name?: string | null
  description?: string | null
  pipeline_id?: string | null
  dataset_id?: string | null
  metadata?: Record<string, any>
  nodes: PipelineNodeDefinition[]
  edges: PipelineEdgeDefinition[]
}

export type PipelineStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface PipelineExecutionStep {
  node_id: string
  order: number
  name: string
  tool: string
  status: PipelineStepStatus
  estimated_duration_ms: number
  summary?: string | null
  metadata?: Record<string, any>
}

export interface PipelineResourceSnapshot {
  label: string
  status: PipelineStepStatus
  progress: number
  node_type?: string | null
  resources: Record<string, any>
}

export interface PipelineExecutionResponse {
  job_id: string
  pipeline_id: string
  status: string
  estimated_duration_seconds: number
  steps: PipelineExecutionStep[]
  resource_snapshot: Record<string, PipelineResourceSnapshot>
  stream_url: string
}
