import type { AnalysisDetail, AnalysisSummary } from '@/types/analysis'
import { buildCodingAgentHandoffHref } from '@/lib/coding-agent-handoff'

type AnalysisLinkSource = Pick<
  AnalysisSummary,
  'analysis_id' | 'thread_id' | 'dataset' | 'template'
> &
  Pick<Partial<AnalysisDetail>, 'plan'>

function getString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function buildStudioResultsHref(
  analysis: Pick<AnalysisSummary, 'analysis_id' | 'thread_id'>,
): string {
  const params = new URLSearchParams()
  params.set('analysisId', analysis.analysis_id)
  params.set('tab', 'results')
  if (analysis.thread_id) {
    params.set('thread', analysis.thread_id)
  }
  return `/studio?${params.toString()}`
}

export function buildStudioPlanHrefFromAnalysis(
  analysis: AnalysisLinkSource,
  options?: { openMcp?: boolean; readOnly?: boolean },
): string | null {
  const plan = analysis.plan && typeof analysis.plan === 'object' ? analysis.plan : null
  const planContext = plan && typeof (plan as any).context === 'object' ? (plan as any).context : null
  const planInputs =
    planContext && typeof (planContext as any).inputs === 'object'
      ? (planContext as any).inputs
      : null

  const pipelineId =
    getString(analysis.template?.pipeline_id) ||
    getString((planContext as any)?.pipeline) ||
    getString((plan as any)?.pipeline) ||
    getString((analysis as any).pipeline_id)

  const datasetId =
    getString(analysis.dataset?.dataset_id) ||
    getString((planInputs as any)?.dataset_id) ||
    getString((planInputs as any)?.datasetId) ||
    getString((analysis as any).dataset_id)

  if (!datasetId && !pipelineId) return null

  const params = new URLSearchParams()
  params.set('tab', 'plan')
  if (pipelineId) params.set('pipeline', pipelineId)
  if (datasetId) params.set('datasetId', datasetId)
  if (!options?.readOnly && analysis.thread_id) {
    params.set('thread', analysis.thread_id)
  }
  if (options?.openMcp) {
    params.set('openMcp', '1')
  }

  return `/studio?${params.toString()}`
}

export function buildCodingAgentHandoffHrefFromAnalysis(
  analysis: AnalysisLinkSource,
): string | null {
  const plan = analysis.plan && typeof analysis.plan === 'object' ? analysis.plan : null
  const planContext = plan && typeof (plan as any).context === 'object' ? (plan as any).context : null
  const planInputs =
    planContext && typeof (planContext as any).inputs === 'object'
      ? (planContext as any).inputs
      : null

  const workflowId =
    getString(analysis.template?.pipeline_id) ||
    getString((planContext as any)?.pipeline) ||
    getString((plan as any)?.pipeline) ||
    getString((plan as any)?.workflow_id) ||
    getString((analysis as any).pipeline_id)

  const datasetId =
    getString(analysis.dataset?.dataset_id) ||
    getString((planInputs as any)?.dataset_id) ||
    getString((planInputs as any)?.datasetId) ||
    getString((analysis as any).dataset_id)

  const planId =
    getString((plan as any)?.plan_id) ||
    getString((plan as any)?.id) ||
    getString((planContext as any)?.plan_id)

  if (!datasetId && !workflowId && !planId && !analysis.thread_id) return null

  return buildCodingAgentHandoffHref({
    datasetId,
    workflowId,
    workflowLabel: getString(analysis.template?.template_id) || workflowId,
    planId,
    threadId: analysis.thread_id,
  })
}
