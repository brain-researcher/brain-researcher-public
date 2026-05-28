export type CodingAgentHandoffContext = {
  datasetId?: string | null
  datasetVersion?: string | null
  workflowId?: string | null
  workflowLabel?: string | null
  planId?: string | null
  threadId?: string | null
}

function setIfPresent(params: URLSearchParams, key: string, value: string | null | undefined) {
  const trimmed = typeof value === 'string' ? value.trim() : ''
  if (trimmed) params.set(key, trimmed)
}

export function buildCodingAgentHandoffHref(context: CodingAgentHandoffContext = {}): string {
  const params = new URLSearchParams()
  params.set('tab', 'integrations')
  params.set('handoff', 'coding-agent')
  setIfPresent(params, 'datasetId', context.datasetId)
  setIfPresent(params, 'datasetVersion', context.datasetVersion)
  setIfPresent(params, 'workflowId', context.workflowId)
  setIfPresent(params, 'workflowLabel', context.workflowLabel)
  setIfPresent(params, 'planId', context.planId)
  setIfPresent(params, 'threadId', context.threadId)
  return `/settings?${params.toString()}`
}
