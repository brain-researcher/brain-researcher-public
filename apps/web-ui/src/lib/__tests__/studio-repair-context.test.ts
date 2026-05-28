import { buildRepairInputArtifacts, deriveRepairSignalSummary } from '../studio-repair-context'
import type { ChatRunCard } from '@/types/chat'
import type { EvidenceData } from '@/lib/evidence-rail-integration'

describe('studio-repair-context', () => {
  it('derives repair signals from failed run steps, violations, and diagnostics', () => {
    const runCard: ChatRunCard = {
      id: 'run-123',
      timestamp: '2026-03-10T12:00:00Z',
      title: 'Validation run',
      description: 'Validation run failed',
      execution: {
        durationSeconds: 42,
        steps: [
          {
            id: 'step-fit',
            name: 'Model fit',
            tool: 'fitlins',
            args: {},
            status: 'failed',
            error: 'FileNotFoundError: confounds.tsv missing for sub-01',
          },
        ],
        environment: {},
        resourceUsage: {},
      },
      inputs: {
        datasets: [],
        parameters: {
          smoothing_fwhm: 6,
        },
        attachments: [],
      },
      outputs: {
        artifacts: [],
        metrics: {},
        toolCalls: [
          {
            id: 'tool-fitlins',
            tool: 'fitlins',
            args: {},
            status: 'error',
            error: 'FileNotFoundError: confounds.tsv missing for sub-01',
          },
        ],
      },
      provenance: {
        tools: [],
        citations: [],
        dependencies: [],
      },
      reproducibility: {},
    }

    const evidenceData: EvidenceData = {
      jobId: 'job-123',
      mappedRunCard: runCard,
      steps: [
        {
          stepId: 'step-fit',
          name: 'Model fit',
          state: 'failed',
          error: 'confounds.tsv missing for sub-01',
        },
      ],
      diagnosticsSummary: {
        schema_version: 'diagnostics-v1',
        top_codes: [{ code: 'taxonomy:data:missing_input', count: 1 }],
        sample_errors: [
          {
            scope: 'step',
            code: 'missing_confounds',
            message: 'Missing confounds.tsv for sub-01',
          },
        ],
        recommended_next_actions: [{ action: 'Restrict validation to a subject with confounds.tsv.' }],
      },
      violations: [
        {
          code: 'missing_confounds',
          message: 'Missing confounds.tsv for sub-01',
          severity: 'error',
          blocking: true,
          where: {
            step_id: 'step-fit',
            stage: 'model_fit',
            component: 'fitlins',
          },
          suggested_fix: 'Restrict validation to a subject with confounds.tsv.',
        },
      ],
    } as EvidenceData

    const summary = deriveRepairSignalSummary({
      evidenceData,
      runCard,
      analysisStatus: 'failed',
      fallbackToolName: 'fitlins',
    })

    expect(summary.toolName).toBe('fitlins')
    expect(summary.errorType).toBe('missing_input')
    expect(summary.errorMessage).toContain('confounds.tsv')
    expect(summary.failingStep).toMatchObject({
      id: 'step-fit',
      name: 'Model fit',
      tool: 'fitlins',
      status: 'failed',
    })
    expect(summary.primaryViolation).toMatchObject({
      code: 'missing_confounds',
      blocking: true,
    })
    expect(summary.diagnosticsCodes).toContain('taxonomy:data:missing_input')
    expect(summary.sampleErrors[0]).toContain('missing_confounds')
  })

  it('builds repair input artifacts from datasets and attachments before artifact fallback', () => {
    const runCard: ChatRunCard = {
      id: 'run-456',
      timestamp: '2026-03-10T12:00:00Z',
      title: 'Validation run',
      description: '',
      execution: {
        durationSeconds: 5,
        steps: [],
        environment: {},
        resourceUsage: {},
      },
      inputs: {
        datasets: [
          {
            id: 'ds:openneuro:ds000001',
            name: 'OpenNeuro ds000001',
            source: 'openneuro',
            version: '1.0.0',
          },
        ],
        parameters: {},
        attachments: [
          {
            id: 'attachment-1',
            name: 'design.tsv',
            type: 'text/tab-separated-values',
            size: 123,
            url: '/uploads/design.tsv',
          },
        ],
      },
      outputs: {
        artifacts: [
          {
            id: 'artifact-1',
            name: 'preview-report.html',
            type: 'html',
            url: '/artifacts/preview-report.html',
          },
        ],
        metrics: {},
      },
      provenance: {
        tools: [],
        citations: [],
        dependencies: [],
      },
      reproducibility: {},
    }

    const preview = buildRepairInputArtifacts(runCard, runCard.outputs.artifacts)

    expect(preview[0]).toMatchObject({
      type: 'dataset',
      uri: 'ds:openneuro:ds000001',
    })
    expect(preview[1]).toMatchObject({
      name: 'design.tsv',
      uri: '/uploads/design.tsv',
    })
    expect(preview[2]).toMatchObject({
      name: 'preview-report.html',
      type: 'html',
    })
  })
})
