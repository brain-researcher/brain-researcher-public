import { describe, expect, it } from 'vitest'

import {
  buildCodingAgentHandoffHrefFromAnalysis,
  buildStudioPlanHrefFromAnalysis,
} from '@/lib/analysis-links'

describe('analysis link helpers', () => {
  it('keeps Studio plan links separate from coding-agent handoff links', () => {
    const analysis = {
      analysis_id: 'run_123',
      thread_id: 'thread_abc',
      dataset: { dataset_id: 'ds000114', name: 'ds000114' },
      template: {
        pipeline_id: 'workflow_rest_connectome_e2e',
        template_id: 'dynamic_workflow/workflow_rest_connectome_e2e',
      },
      plan: { plan_id: 'plan_123' },
    } as any

    expect(buildStudioPlanHrefFromAnalysis(analysis)).toBe(
      '/studio?tab=plan&pipeline=workflow_rest_connectome_e2e&datasetId=ds000114&thread=thread_abc',
    )
    expect(buildCodingAgentHandoffHrefFromAnalysis(analysis)).toBe(
      '/settings?tab=integrations&handoff=coding-agent&datasetId=ds000114&workflowId=workflow_rest_connectome_e2e&workflowLabel=dynamic_workflow%2Fworkflow_rest_connectome_e2e&planId=plan_123&threadId=thread_abc',
    )
  })
})
