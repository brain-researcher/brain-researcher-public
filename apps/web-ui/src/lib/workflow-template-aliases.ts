export type CanonicalTemplateSelection = {
  analysisId: string
  pipelineId: string
  templateId: string
  requestedAnalysisId: string
  requestedPipelineId: string
  requestedTemplateId: string
  canonicalized: boolean
  canonicalizationReason?: string
}

const LEGACY_PIPELINE_WORKFLOW_ALIASES: Record<string, string> = {
  parcellation_analysis: 'workflow_rest_connectome_e2e',
  atlas_based_signal_extraction: 'workflow_rest_connectome_e2e',
  atlasbasedsignalextraction: 'workflow_rest_connectome_e2e',
  fmriprep: 'workflow_fmriprep_preprocessing',
  mriqc: 'workflow_mriqc',
  qsiprep: 'workflow_qsiprep',
}

function normalizeId(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function aliasKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[?#].*$/g, '')
    .split(/[\\/]/)
    .filter(Boolean)
    .pop()
    ?.replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || ''
}

export function legacyPipelineWorkflowAlias(value: unknown): string | null {
  const key = aliasKey(normalizeId(value))
  return key ? LEGACY_PIPELINE_WORKFLOW_ALIASES[key] ?? null : null
}

export function workflowIdFromReference(value: unknown): string | null {
  const raw = normalizeId(value)
  if (!raw) return null

  const withoutQuery = raw.replace(/[?#].*$/g, '')
  const fromAlias = legacyPipelineWorkflowAlias(withoutQuery)
  if (fromAlias) return fromAlias

  let pathValue = withoutQuery
  try {
    const parsed = new URL(withoutQuery)
    pathValue = parsed.pathname
  } catch {
    pathValue = withoutQuery
  }

  const markerMatch = pathValue.match(/(?:^|\/)(?:api\/)?workflows\/([^/]+)$/)
  if (markerMatch?.[1]) return markerMatch[1]

  const parts = pathValue.split(/[\\/]/).filter(Boolean)
  const last = parts.at(-1) || pathValue
  return last.startsWith('workflow_') ? last : null
}

export function canonicalizeTemplateSelection(input: {
  analysisId: string
  pipelineId: string
  templateId?: string
}): CanonicalTemplateSelection {
  const requestedAnalysisId = normalizeId(input.analysisId)
  const requestedPipelineId = normalizeId(input.pipelineId)
  const requestedTemplateId = normalizeId(input.templateId)
  let analysisId = requestedAnalysisId
  let pipelineId = requestedPipelineId
  let canonicalizationReason: string | undefined

  const aliasWorkflowId = legacyPipelineWorkflowAlias(pipelineId)
  const workflowId = workflowIdFromReference(pipelineId)
  if (analysisId === 'dynamic_workflow' && aliasWorkflowId) {
    pipelineId = aliasWorkflowId
    canonicalizationReason = 'legacy_pipeline_alias'
  } else if (analysisId === 'dynamic_workflow' && workflowId && workflowId !== pipelineId) {
    pipelineId = workflowId
    canonicalizationReason = 'workflow_id_reference'
  } else if (analysisId !== 'dynamic_workflow') {
    if (aliasWorkflowId) {
      analysisId = 'dynamic_workflow'
      pipelineId = aliasWorkflowId
      canonicalizationReason = 'legacy_pipeline_alias'
    } else if (workflowId && workflowId !== pipelineId) {
      analysisId = 'dynamic_workflow'
      pipelineId = workflowId
      canonicalizationReason = 'workflow_id_reference'
    } else if (pipelineId.startsWith('workflow_')) {
      analysisId = 'dynamic_workflow'
      canonicalizationReason = 'workflow_id_pipeline'
    }
  }

  const templateId = `${analysisId}/${pipelineId}`
  const canonicalized =
    analysisId !== requestedAnalysisId ||
    pipelineId !== requestedPipelineId ||
    Boolean(canonicalizationReason)

  return {
    analysisId,
    pipelineId,
    templateId,
    requestedAnalysisId,
    requestedPipelineId,
    requestedTemplateId,
    canonicalized,
    canonicalizationReason,
  }
}
