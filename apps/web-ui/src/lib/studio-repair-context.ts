import type {
  ChatRunCard,
  DatasetInfo,
  ExecutionStep,
  FileAttachment,
  ToolCall,
} from '@/types/chat'
import type { EvidenceData } from '@/lib/evidence-rail-integration'

export type RepairFailingStep = {
  id: string | null
  name: string | null
  tool: string | null
  status: string | null
  error: string | null
}

export type RepairViolationSummary = {
  code: string | null
  message: string | null
  severity: string | null
  blocking: boolean
  suggested_fix: string | null
  where: {
    step_id: string | null
    stage: string | null
    component: string | null
    path: string | null
  } | null
}

export type RepairSignalSummary = {
  failingStep: RepairFailingStep | null
  toolName: string | null
  errorType: string | null
  errorMessage: string | null
  primaryViolation: RepairViolationSummary | null
  diagnosticsCodes: string[]
  sampleErrors: string[]
}

type DeriveRepairSignalSummaryArgs = {
  evidenceData: EvidenceData | null
  runCard: ChatRunCard | null
  analysisStatus?: string | null
  summaryMessage?: string | null
  diagnosisMessage?: string | null
  fallbackToolName?: string | null
}

const FAILURE_STATUSES = new Set(['failed', 'error', 'timeout', 'cancelled'])

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized.length > 0 ? normalized : null
}

function isFailureStatus(value: unknown): boolean {
  const normalized = asNonEmptyString(value)?.toLowerCase()
  return normalized ? FAILURE_STATUSES.has(normalized) : false
}

function pickFailedRunStep(runCard: ChatRunCard | null): ExecutionStep | null {
  const steps = Array.isArray(runCard?.execution?.steps) ? runCard.execution.steps : []
  return (
    steps.find((step) => Boolean(asNonEmptyString(step.error)) || isFailureStatus(step.status)) ?? null
  )
}

function pickFailedEvidenceStep(
  evidenceData: EvidenceData | null,
  preferredStepId?: string | null,
) {
  const steps = Array.isArray(evidenceData?.steps) ? evidenceData.steps : []
  if (preferredStepId) {
    const exact = steps.find((step) => asNonEmptyString(step.stepId) === preferredStepId)
    if (exact) return exact
  }
  return (
    steps.find((step) => Boolean(asNonEmptyString(step.error)) || isFailureStatus(step.state)) ?? null
  )
}

function summarizeViolation(value: unknown): RepairViolationSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const whereRecord =
    record.where && typeof record.where === 'object' && !Array.isArray(record.where)
      ? (record.where as Record<string, unknown>)
      : null
  return {
    code: asNonEmptyString(record.code),
    message: asNonEmptyString(record.message),
    severity: asNonEmptyString(record.severity),
    blocking: Boolean(record.blocking),
    suggested_fix: asNonEmptyString(record.suggested_fix),
    where: whereRecord
      ? {
          step_id: asNonEmptyString(whereRecord.step_id),
          stage: asNonEmptyString(whereRecord.stage),
          component: asNonEmptyString(whereRecord.component),
          path: asNonEmptyString(whereRecord.path),
        }
      : null,
  }
}

function pickPrimaryViolation(
  evidenceData: EvidenceData | null,
  preferredStepId?: string | null,
): RepairViolationSummary | null {
  const violations = Array.isArray(evidenceData?.violations)
    ? evidenceData.violations
        .map((violation) => summarizeViolation(violation))
        .filter((violation): violation is RepairViolationSummary => violation !== null)
    : []
  if (violations.length === 0) return null

  if (preferredStepId) {
    const exact = violations.find(
      (violation) =>
        violation.where?.step_id === preferredStepId &&
        (violation.blocking ||
          violation.severity === 'error' ||
          violation.severity === 'critical'),
    )
    if (exact) return exact
  }

  return (
    violations.find(
      (violation) =>
        violation.blocking ||
        violation.severity === 'error' ||
        violation.severity === 'critical',
    ) ?? violations[0]
  )
}

function pickFailedToolCall(
  runCard: ChatRunCard | null,
  preferredTool?: string | null,
): ToolCall | null {
  const toolCalls = Array.isArray(runCard?.outputs?.toolCalls) ? runCard.outputs.toolCalls : []
  if (preferredTool) {
    const exact = toolCalls.find((toolCall) => {
      const tool = asNonEmptyString(toolCall.tool)
      return tool === preferredTool && (toolCall.status === 'error' || Boolean(toolCall.error))
    })
    if (exact) return exact
  }
  return toolCalls.find((toolCall) => toolCall.status === 'error' || Boolean(toolCall.error)) ?? null
}

function summarizeDiagnosticsCodes(evidenceData: EvidenceData | null): string[] {
  const items = Array.isArray(evidenceData?.diagnosticsSummary?.top_codes)
    ? evidenceData?.diagnosticsSummary?.top_codes
    : []
  return items
    .map((item) => asNonEmptyString(item?.code))
    .filter((value): value is string => value !== null)
    .slice(0, 8)
}

function summarizeSampleErrors(evidenceData: EvidenceData | null): string[] {
  const items = Array.isArray(evidenceData?.diagnosticsSummary?.sample_errors)
    ? evidenceData.diagnosticsSummary.sample_errors
    : []
  const results: string[] = []
  for (const item of items) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const record = item as Record<string, unknown>
    const message = asNonEmptyString(record.message)
    if (!message) continue
    const code = asNonEmptyString(record.code)
    const scope = asNonEmptyString(record.scope)
    const prefix = [scope, code].filter(Boolean).join(': ')
    results.push(prefix ? `${prefix}: ${message}` : message)
    if (results.length >= 5) break
  }
  return results
}

function inferRepairErrorType(args: {
  analysisStatus?: string | null
  errorMessage: string | null
  failingStep: RepairFailingStep | null
  primaryViolation: RepairViolationSummary | null
  diagnosticsCodes: string[]
  sampleErrors: string[]
  failedToolCall: ToolCall | null
}): string | null {
  const status = asNonEmptyString(args.analysisStatus)?.toLowerCase()
  if (status === 'timeout') return 'timeout'

  const corpus = [
    status,
    args.errorMessage,
    args.failingStep?.error,
    args.failingStep?.name,
    args.failingStep?.tool,
    args.primaryViolation?.code,
    args.primaryViolation?.message,
    args.primaryViolation?.suggested_fix,
    args.primaryViolation?.where?.stage,
    args.primaryViolation?.where?.component,
    args.failedToolCall?.tool,
    args.failedToolCall?.error,
    ...args.diagnosticsCodes,
    ...args.sampleErrors,
  ]
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .join(' ')
    .toLowerCase()

  if (!corpus) return null
  if (
    /timeout|timed out|deadline exceeded|job_state:timeout/.test(corpus)
  ) {
    return 'timeout'
  }
  if (
    /permission denied|forbidden|unauthorized|access denied/.test(corpus)
  ) {
    return 'permission_error'
  }
  if (
    /out of memory|oom|resource exhausted|disk full|no space left|memoryerror|killed process|cuda out of memory/.test(
      corpus,
    )
  ) {
    return 'resource_error'
  }
  if (
    /module not found|importerror|dependency|package .* not found|command not found|environment missing|missing executable/.test(
      corpus,
    )
  ) {
    return 'dependency_error'
  }
  if (
    /file ?not ?found|no such file|missing[_ :]|missing input|missing confounds|not found|missing artifact|missing dataset/.test(
      corpus,
    )
  ) {
    return 'missing_input'
  }
  if (
    /atlas|parcellation|smoothing|tr\b|high.?pass|config|configuration|parameter|argument|setting/.test(
      corpus,
    )
  ) {
    return 'configuration_error'
  }
  if (
    /bids|schema|validation|invalid|mismatch|not compliant|violation:|taxonomy:/.test(
      corpus,
    )
  ) {
    return 'validation_error'
  }
  return 'workflow_error'
}

function buildMergedFailingStep(args: {
  runStep: ExecutionStep | null
  evidenceStep: EvidenceData['steps'][number] | null
  primaryViolation: RepairViolationSummary | null
}): RepairFailingStep | null {
  const { runStep, evidenceStep, primaryViolation } = args
  const stepId =
    asNonEmptyString(runStep?.id) ||
    asNonEmptyString(evidenceStep?.stepId) ||
    primaryViolation?.where?.step_id ||
    null
  const name =
    asNonEmptyString(runStep?.name) ||
    asNonEmptyString(evidenceStep?.name) ||
    stepId
  const tool =
    asNonEmptyString(runStep?.tool) ||
    primaryViolation?.where?.component ||
    null
  const status =
    asNonEmptyString(runStep?.status) ||
    asNonEmptyString(evidenceStep?.state) ||
    null
  const error =
    asNonEmptyString(runStep?.error) ||
    asNonEmptyString(evidenceStep?.error) ||
    primaryViolation?.message ||
    null

  if (!stepId && !name && !tool && !status && !error) return null
  return {
    id: stepId,
    name,
    tool,
    status,
    error,
  }
}

function pushUniquePreview(
  items: Array<Record<string, unknown>>,
  seen: Set<string>,
  value: Record<string, unknown>,
) {
  const name = asNonEmptyString(value.name)
  const uri = asNonEmptyString(value.uri)
  const type = asNonEmptyString(value.type) || 'artifact'
  const key = `${type}:${name || uri || 'unknown'}`
  if (seen.has(key)) return
  seen.add(key)
  items.push(value)
}

function datasetPreview(dataset: DatasetInfo): Record<string, unknown> {
  return {
    name: dataset.name || dataset.id || 'dataset',
    type: 'dataset',
    uri: dataset.id || null,
    source: dataset.source || null,
    version: dataset.version || null,
    n_subjects: dataset.nSubjects ?? null,
  }
}

function attachmentPreview(attachment: FileAttachment): Record<string, unknown> {
  return {
    name: attachment.name || attachment.id || 'attachment',
    type: attachment.type || 'attachment',
    uri: attachment.url || attachment.path || null,
    size: attachment.size ?? null,
    storage: attachment.storage ?? null,
  }
}

export function buildRepairInputArtifacts(
  runCard: ChatRunCard | null,
  fallbackArtifacts: unknown,
): Array<Record<string, unknown>> {
  const items: Array<Record<string, unknown>> = []
  const seen = new Set<string>()

  const datasets = Array.isArray(runCard?.inputs?.datasets) ? runCard.inputs.datasets : []
  for (const dataset of datasets.slice(0, 3)) {
    pushUniquePreview(items, seen, datasetPreview(dataset))
  }

  const attachments = Array.isArray(runCard?.inputs?.attachments)
    ? runCard.inputs.attachments
    : []
  for (const attachment of attachments.slice(0, 3)) {
    pushUniquePreview(items, seen, attachmentPreview(attachment))
  }

  const artifacts = Array.isArray(fallbackArtifacts) ? fallbackArtifacts : []
  for (const artifact of artifacts.slice(0, 6)) {
    if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) continue
    const record = artifact as Record<string, unknown>
    pushUniquePreview(items, seen, {
      name: asNonEmptyString(record.name) || asNonEmptyString(record.id) || 'artifact',
      type: asNonEmptyString(record.type) || 'artifact',
      uri:
        asNonEmptyString(record.url) ||
        asNonEmptyString(record.path) ||
        asNonEmptyString(record.uri),
    })
    if (items.length >= 6) break
  }

  return items.slice(0, 6)
}

export function deriveRepairSignalSummary({
  evidenceData,
  runCard,
  analysisStatus,
  summaryMessage,
  diagnosisMessage,
  fallbackToolName,
}: DeriveRepairSignalSummaryArgs): RepairSignalSummary {
  const runStep = pickFailedRunStep(runCard)
  const evidenceStep = pickFailedEvidenceStep(evidenceData, asNonEmptyString(runStep?.id))
  const primaryViolation = pickPrimaryViolation(
    evidenceData,
    asNonEmptyString(runStep?.id) || asNonEmptyString(evidenceStep?.stepId),
  )
  const failingStep = buildMergedFailingStep({
    runStep,
    evidenceStep,
    primaryViolation,
  })
  const failedToolCall = pickFailedToolCall(runCard, failingStep?.tool)
  const diagnosticsCodes = summarizeDiagnosticsCodes(evidenceData)
  const sampleErrors = summarizeSampleErrors(evidenceData)

  const toolName =
    failingStep?.tool ||
    asNonEmptyString(failedToolCall?.tool) ||
    primaryViolation?.where?.component ||
    fallbackToolName ||
    failingStep?.name ||
    null

  const errorMessage =
    asNonEmptyString(summaryMessage) ||
    failingStep?.error ||
    asNonEmptyString(failedToolCall?.error) ||
    primaryViolation?.message ||
    sampleErrors[0] ||
    asNonEmptyString(diagnosisMessage) ||
    null

  const errorType = inferRepairErrorType({
    analysisStatus,
    errorMessage,
    failingStep,
    primaryViolation,
    diagnosticsCodes,
    sampleErrors,
    failedToolCall,
  })

  return {
    failingStep,
    toolName,
    errorType,
    errorMessage,
    primaryViolation,
    diagnosticsCodes,
    sampleErrors,
  }
}
