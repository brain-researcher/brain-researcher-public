import type { RunCardV1 } from './contracts.generated'

export interface FileAttachment {
  id: string
  name: string
  type: string
  size: number
  url: string
  upload_progress?: number
  // New optional fields for storage metadata (backward compatible)
  storage?: 'local' | 's3' | 'remote'
  path?: string
  checksum?: string
  uploadedBy?: string
  expiresAt?: string
}

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  executionBlock?: ExecutionBlock
  attachments?: FileAttachment[]
  resumeCheckpointId?: string | null
  lastCheckpointId?: string | null
  metadata?: Record<string, any>
  runCard?: ChatRunCard
  error?: string
}

export interface ExecutionBlock {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  steps?: ExecutionStep[]
  artifacts?: Artifact[]
  startTime?: Date
  endTime?: Date
  error?: string
  metadata?: Record<string, any>
  progress?: number
}

export interface ExecutionStep {
  id: string
  name: string
  tool: string
  args: Record<string, any>
  status: 'pending' | 'running' | 'completed' | 'failed' | 'success' | 'succeeded' | 'error' | 'skipped'
  preview?: string
  timing?: {
    startTime: Date
    endTime?: Date
    duration?: number
  }
  logs?: LogEntry[]
  retryCount?: number
  error?: string
  produces?: Record<string, any>
  branchGroupId?: string
  branchRank?: number
  branchStepId?: string
  behaviorPolicyId?: string
}

export interface BranchEvent {
  eventType?: string
  branchGroupId?: string
  branchRank?: number
  branchTool?: string
  branchStepId?: string
  branchId?: string
  timestamp?: string | number
  error?: string
}

export interface PlannerEvent {
  eventType?: string
  timestamp?: string | number
  payload?: Record<string, any>
  diff?: Record<string, any>
  eventId?: string
}

export interface Artifact {
  id: string
  type: 'image' | 'table' | 'json' | 'html' | 'nifti' | 'brain_map' | 'text'
  name: string
  url: string
  meta?: Record<string, any>
  size?: number
  checksum?: string
  description?: string
}

export interface LogEntry {
  timestamp: Date
  level: 'INFO' | 'WARN' | 'ERROR'
  message: string
  step?: string
}

// Dataset info for RunCard inputs
export interface DatasetInfo {
  id: string
  name: string
  source: string
  version?: string
  nSubjects?: number
  nSessions?: number
  tasks?: string[]
  checksum?: string
  bidsVersion?: string
}

// Tool info for RunCard provenance
export interface ToolInfo {
  name: string
  version: string
  citation?: string
  doi?: string
  url?: string
  checksum?: string
}

// Citation info for RunCard provenance
export interface Citation {
  id?: string
  type: 'dataset' | 'paper' | 'tool' | 'method' | 'reference'
  title: string
  authors?: string[]
  doi?: string
  url?: string
  year?: number
  description?: string
  journal?: string
  bibtex?: string
}

// Resource usage info
export interface ResourceUsage {
  peakMemoryMb?: number
  cpuTimeSeconds?: number
  gpuTimeSeconds?: number
  diskIoMb?: number
  networkIoMb?: number
}

// RunCard view-model used by the web UI (not the canonical contract)
export interface ChatRunCard {
  version?: string
  id: string
  timestamp: string | Date
  title: string
  description: string

  // Execution details
  execution: {
    durationSeconds: number
    steps: ExecutionStep[]
    environment: Record<string, string>
    resourceUsage: ResourceUsage
    branchEvents?: BranchEvent[]
    plannerEvents?: PlannerEvent[]
    plannerState?: Record<string, any>
  }

  // Inputs and parameters
  inputs: {
    datasets: DatasetInfo[]
    parameters: Record<string, any>
    attachments: FileAttachment[]
  }

  // Outputs and results
  outputs: {
    artifacts: Artifact[]
    metrics: Record<string, number>
    plots?: string[]
    text?: string
    toolCalls?: ToolCall[]
    citations?: Citation[]
  }

  // Provenance and reproducibility
  provenance: {
    tools: ToolInfo[]
    citations: Citation[]
    dependencies: string[]
  }

  reproducibility: {
    score?: number
    randomSeed?: number
    isReproducible?: boolean
    versions?: Record<string, string>
    checksums?: Record<string, string>
    containerInfo?: Record<string, string>
  }

  // Legacy fields for backward compatibility
  prompt?: string
  dataset?: DatasetInfo
  tools?: ToolInfo[]
  parameters?: Record<string, any>
  citations?: Citation[]
  artifacts?: Artifact[]
  reproducibilityScore?: number
}

// Tool call record for outputs
export interface ToolCall {
  id: string
  tool: string
  args: Record<string, any>
  result?: any
  status: 'success' | 'error'
  durationMs?: number
  error?: string
}

// Raw backend RunCard (snake_case) for mapping
export type BackendRunCard = RunCardV1 & {
  // Back-compat: older producers include a top-level run_id.
  run_id?: string
}
