import { describe, expect, it } from 'vitest'

import {
  canonicalizeTemplateSelection,
  workflowIdFromReference,
} from '@/lib/workflow-template-aliases'

describe('workflow template aliases', () => {
  it('maps the legacy Atlas-Based Signal Extraction pipeline to the canonical workflow id', () => {
    const selection = canonicalizeTemplateSelection({
      analysisId: 'connectivity',
      pipelineId: 'parcellation_analysis',
    })

    expect(selection).toEqual(
      expect.objectContaining({
        analysisId: 'dynamic_workflow',
        pipelineId: 'workflow_rest_connectome_e2e',
        requestedAnalysisId: 'connectivity',
        requestedPipelineId: 'parcellation_analysis',
        canonicalized: true,
        canonicalizationReason: 'legacy_pipeline_alias',
      }),
    )
  })

  it('maps long-running BIDS app presets to recipe-backed workflow ids', () => {
    expect(
      canonicalizeTemplateSelection({
        analysisId: 'preprocess',
        pipelineId: 'fmriprep',
      }),
    ).toEqual(
      expect.objectContaining({
        analysisId: 'dynamic_workflow',
        pipelineId: 'workflow_fmriprep_preprocessing',
        canonicalized: true,
        canonicalizationReason: 'legacy_pipeline_alias',
      }),
    )

    expect(
      canonicalizeTemplateSelection({
        analysisId: 'preprocess',
        pipelineId: 'mriqc',
      }),
    ).toEqual(
      expect.objectContaining({
        analysisId: 'dynamic_workflow',
        pipelineId: 'workflow_mriqc',
        canonicalized: true,
        canonicalizationReason: 'legacy_pipeline_alias',
      }),
    )

    expect(
      canonicalizeTemplateSelection({
        analysisId: 'preprocess',
        pipelineId: 'qsiprep',
      }),
    ).toEqual(
      expect.objectContaining({
        analysisId: 'dynamic_workflow',
        pipelineId: 'workflow_qsiprep',
        canonicalized: true,
        canonicalizationReason: 'legacy_pipeline_alias',
      }),
    )
  })

  it('extracts workflow ids from API workflow URLs', () => {
    expect(workflowIdFromReference('/api/workflows/workflow_preprocessing_qc')).toBe(
      'workflow_preprocessing_qc',
    )
    expect(
      workflowIdFromReference('https://${PUBLIC_HOSTNAME}/api/workflows/workflow_mriqc'),
    ).toBe('workflow_mriqc')
  })
})
