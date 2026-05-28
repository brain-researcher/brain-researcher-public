import { deriveRepairSignalSummary } from '../studio-repair-context'
import type { ChatRunCard } from '@/types/chat'
import type { EvidenceData } from '@/lib/evidence-rail-integration'

type FailureCase = {
  name: string
  analysisStatus?: string
  stepTool: string
  stepName: string
  stepError: string
  violationCode: string
  violationMessage: string
  diagnosticsCode: string
  sampleError: string
  expectedErrorType: string
}

function buildRunCard(testCase: FailureCase): ChatRunCard {
  return {
    id: `run-${testCase.name}`,
    timestamp: '2026-03-10T12:00:00Z',
    title: 'Validation run',
    description: testCase.name,
    execution: {
      durationSeconds: 12,
      steps: [
        {
          id: 'step-1',
          name: testCase.stepName,
          tool: testCase.stepTool,
          args: {},
          status: 'failed',
          error: testCase.stepError,
        },
      ],
      environment: {},
      resourceUsage: {},
    },
    inputs: {
      datasets: [],
      parameters: {},
      attachments: [],
    },
    outputs: {
      artifacts: [],
      metrics: {},
      toolCalls: [
        {
          id: `tool-${testCase.name}`,
          tool: testCase.stepTool,
          args: {},
          status: 'error',
          error: testCase.stepError,
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
}

function buildEvidenceData(testCase: FailureCase, runCard: ChatRunCard): EvidenceData {
  return {
    jobId: `job-${testCase.name}`,
    mappedRunCard: runCard,
    steps: [
      {
        stepId: 'step-1',
        name: testCase.stepName,
        state: testCase.analysisStatus === 'timeout' ? 'timeout' : 'failed',
        error: testCase.stepError,
      },
    ],
    diagnosticsSummary: {
      schema_version: 'diagnostics-v1',
      top_codes: [{ code: testCase.diagnosticsCode, count: 1 }],
      sample_errors: [
        {
          scope: 'step',
          code: testCase.violationCode,
          message: testCase.sampleError,
        },
      ],
      recommended_next_actions: [],
    },
    violations: [
      {
        code: testCase.violationCode,
        message: testCase.violationMessage,
        severity: 'error',
        blocking: true,
        where: {
          step_id: 'step-1',
          stage: 'validation',
          component: testCase.stepTool,
        },
      },
    ],
  } as EvidenceData
}

const FAILURE_CASES: FailureCase[] = [
  {
    name: 'missing-confounds',
    stepTool: 'fitlins',
    stepName: 'Model fit',
    stepError: 'FileNotFoundError: confounds.tsv missing for sub-01',
    violationCode: 'missing_confounds',
    violationMessage: 'Missing confounds.tsv for subject 01',
    diagnosticsCode: 'taxonomy:data:missing_input',
    sampleError: 'Missing confounds.tsv for subject 01',
    expectedErrorType: 'missing_input',
  },
  {
    name: 'dataset-version-mismatch',
    stepTool: 'bids-validator',
    stepName: 'BIDS validation',
    stepError: 'Dataset version mismatch between selected OpenNeuro manifest and mounted files',
    violationCode: 'dataset_version_mismatch',
    violationMessage: 'Dataset version mismatch between selected OpenNeuro manifest and mounted files',
    diagnosticsCode: 'violation:dataset_version_mismatch',
    sampleError: 'Dataset version mismatch between selected OpenNeuro manifest and mounted files',
    expectedErrorType: 'validation_error',
  },
  {
    name: 'atlas-parameter-mismatch',
    stepTool: 'nilearn_glm',
    stepName: 'Design matrix build',
    stepError: 'Atlas mismatch: Schaefer-200 parcels do not match the configured AAL design matrix labels',
    violationCode: 'atlas_parameter_mismatch',
    violationMessage: 'Atlas mismatch between selected parcellation and design matrix labels',
    diagnosticsCode: 'violation:atlas_parameter_mismatch',
    sampleError: 'Atlas mismatch between selected parcellation and design matrix labels',
    expectedErrorType: 'configuration_error',
  },
  {
    name: 'missing-task-label',
    stepTool: 'bids-validator',
    stepName: 'BIDS validation',
    stepError: 'BIDS validation failed: task label mismatch between events.tsv and the requested task-nback design',
    violationCode: 'task_label_mismatch',
    violationMessage: 'Task label mismatch between events.tsv and the requested design',
    diagnosticsCode: 'violation:task_label_mismatch',
    sampleError: 'Task label mismatch between events.tsv and the requested design',
    expectedErrorType: 'validation_error',
  },
  {
    name: 'dependency-env-issue',
    stepTool: 'fmriprep',
    stepName: 'Preprocessing',
    stepError: 'ImportError: niworkflows is not installed in the execution environment',
    violationCode: 'environment_dependency_missing',
    violationMessage: 'Execution environment is missing the niworkflows package',
    diagnosticsCode: 'taxonomy:environment:dependency_missing',
    sampleError: 'Execution environment is missing the niworkflows package',
    expectedErrorType: 'dependency_error',
  },
]

describe('studio-repair-context real failure case eval', () => {
  it.each(FAILURE_CASES)(
    'classifies $name as $expectedErrorType with local tool/error context preserved',
    (testCase) => {
      const runCard = buildRunCard(testCase)
      const evidenceData = buildEvidenceData(testCase, runCard)

      const summary = deriveRepairSignalSummary({
        evidenceData,
        runCard,
        analysisStatus: testCase.analysisStatus ?? 'failed',
        fallbackToolName: testCase.stepTool,
      })

      expect(summary.toolName).toBe(testCase.stepTool)
      expect(summary.errorType).toBe(testCase.expectedErrorType)
      expect(summary.errorMessage).toContain(testCase.stepError.split(':')[0])
      expect(summary.failingStep).toMatchObject({
        id: 'step-1',
        name: testCase.stepName,
        tool: testCase.stepTool,
      })
      expect(summary.primaryViolation?.code).toBe(testCase.violationCode)
      expect(summary.diagnosticsCodes[0]).toBe(testCase.diagnosticsCode)
    },
  )
})
