'use client'

import { ANALYSIS_TYPES } from '@/config/analysis-presets'

type OfficialWorkflowTemplate = {
  analysisLabel: string
  pipelineId: string
  pipelineLabel: string
  pipelineDescription: string
}

type OfficialWorkflowTemplatesProps = {
  onPickPipeline: (pipelineId: string) => void
  testIdPrefix: string
  title?: string
  titleClassName?: string
  gridClassName?: string
}

const QUICK_TEMPLATE_PIPELINE_IDS = [
  'nilearn_connectivity',
  'nilearn_glm',
  'fmriprep',
  'fmri_glm_multiverse_openneuro',
] as const

const ALL_OFFICIAL_WORKFLOW_TEMPLATES: OfficialWorkflowTemplate[] = ANALYSIS_TYPES.flatMap((analysis) =>
  analysis.pipelines.map((pipeline) => ({
    analysisLabel: analysis.label,
    pipelineId: pipeline.id,
    pipelineLabel: pipeline.label,
    pipelineDescription: pipeline.description,
  })),
)

const OFFICIAL_WORKFLOW_TEMPLATES: OfficialWorkflowTemplate[] = (() => {
  const byPipelineId = new Map(
    ALL_OFFICIAL_WORKFLOW_TEMPLATES.map((template) => [template.pipelineId, template]),
  )
  const prioritized = QUICK_TEMPLATE_PIPELINE_IDS.map((id) => byPipelineId.get(id)).filter(
    (template): template is OfficialWorkflowTemplate => Boolean(template),
  )
  return prioritized.length > 0 ? prioritized : ALL_OFFICIAL_WORKFLOW_TEMPLATES.slice(0, 4)
})()

export function OfficialWorkflowTemplates({
  onPickPipeline,
  testIdPrefix,
  title = 'Official templates',
  titleClassName = 'text-sm font-medium text-center',
  gridClassName = 'grid grid-cols-1 gap-3 sm:grid-cols-2',
}: OfficialWorkflowTemplatesProps) {
  return (
    <div className="space-y-3">
      <div className={titleClassName}>{title}</div>
      <div className={gridClassName}>
        {OFFICIAL_WORKFLOW_TEMPLATES.map((template) => (
          <button
            key={template.pipelineId}
            type="button"
            data-testid={`${testIdPrefix}-${template.pipelineId}`}
            className="rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-muted/20"
            onClick={() => onPickPipeline(template.pipelineId)}
          >
            <div className="text-sm font-medium">{template.pipelineLabel}</div>
            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {template.pipelineDescription}
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              Category: {template.analysisLabel}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
