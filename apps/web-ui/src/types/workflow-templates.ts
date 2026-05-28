export type WorkflowTemplateStatus =
  | 'active'
  | 'deprecated'
  | 'experimental'
  | 'draft'

export interface WorkflowTemplateListItem {
  id: string
  name: string
  description: string
  version: string
  category: string
  author: string
  status: WorkflowTemplateStatus
  tags: string[]
  parameter_count: number
  step_count: number
  created_at: string
}

export interface WorkflowTemplateParameter {
  name: string
  type: string
  description: string
  required: boolean
  default?: unknown
  choices?: unknown[]
  min_value?: number
  max_value?: number
  pattern?: string
  validation_rules?: string[]
}

export interface WorkflowTemplateStep {
  name: string
  tool: string
  description: string
  parameters: Record<string, unknown>
  depends_on?: string[]
  optional?: boolean
  timeout_seconds?: number | null
  retry_count?: number
  conditions?: string[]
}

export interface WorkflowTemplateDetail {
  id: string
  name: string
  description: string
  version: string
  category: string
  author: string
  status: WorkflowTemplateStatus
  tags: string[]
  parameters: WorkflowTemplateParameter[]
  steps: WorkflowTemplateStep[]
  outputs: Record<string, unknown>
  metadata: Record<string, unknown>
  inherits_from?: string | null
  created_at: string
}

export interface WorkflowTemplateCreateResponse {
  template_id: string
  template_name: string
  version: string
  created_at: string
}
