import { getDataset } from '@/lib/server/dataset-catalog'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import type {
  AnalysisDetail,
  AnalysisLogSummary,
  AnalysisPreflightSnapshot,
  AnalysisStatus,
  AnalysisStepSummary,
} from '@/types/analysis'

type BuildResult =
  | { ok: true; detail: AnalysisDetail }
  | { ok: false; status: number; body: Record<string, unknown> }

const toEpochSeconds = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e11 ? Math.floor(value / 1000) : value
  }
  if (typeof value !== 'string' || !value.trim()) return null
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return null
  return Math.floor(ms / 1000)
}

function normalizeStatus(value: unknown): AnalysisStatus {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'claimed') return 'running'
  if (normalized === 'skipped') return 'cancelled'
  if (normalized === 'succeeded') return 'completed'
  const allowed = new Set<AnalysisStatus>([
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled',
    'cancelling',
    'retrying',
    'paused',
    'timeout',
    'unknown',
  ])
  return allowed.has(normalized as AnalysisStatus) ? (normalized as AnalysisStatus) : 'unknown'
}

async function fetchJson(
  url: string,
  init: RequestInit,
): Promise<{ ok: boolean; status: number; json: unknown | null; text: string }> {
  try {
    const res = await fetch(url, { ...init, cache: 'no-store' })
    const text = await res.text()
    let json: unknown | null = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      json = null
    }
    return { ok: res.ok, status: res.status, json, text }
  } catch (error) {
    return { ok: false, status: 502, json: null, text: String(error) }
  }
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function parsePayloadJson(raw: unknown): Record<string, unknown> | null {
  if (typeof raw !== 'string' || !raw.trim()) return null
  try {
    return safeRecord(JSON.parse(raw))
  } catch {
    return null
  }
}

function extractPlanOfRecordSteps(plan: Record<string, unknown> | null): Record<string, unknown>[] {
  if (!plan) return []
  const dag = safeRecord(plan.dag)
  const steps = dag?.steps
  if (!Array.isArray(steps)) return []
  return steps
    .map((step) => safeRecord(step))
    .filter((step): step is Record<string, unknown> => step != null)
}

function extractClientPlanEnvelope(
  payload: Record<string, unknown>,
): Record<string, unknown> | null {
  const metadata = safeRecord(payload.metadata)
  const metadataParameters = safeRecord(metadata?.parameters)
  const clientMetadata = safeRecord(metadataParameters?._client_metadata)

  return (
    safeRecord(metadata?.client_plan_envelope) ??
    safeRecord(clientMetadata?.plan_envelope) ??
    safeRecord(clientMetadata?.canonical_plan)
  )
}

function pickDatasetRef(plan: Record<string, unknown> | null): string {
  if (!plan) return ''
  return (
    normalizeId(plan.dataset_ref) ||
    normalizeId(plan.dataset_id) ||
    normalizeId(safeRecord(plan.context)?.dataset_ref) ||
    normalizeId(safeRecord(safeRecord(plan.context)?.inputs)?.dataset_ref) ||
    normalizeId(safeRecord(safeRecord(plan.context)?.inputs)?.dataset_id) ||
    normalizeId(safeRecord(plan.handoff_pack)?.dataset_ref) ||
    normalizeId(safeRecord(plan.handoff)?.dataset_ref)
  )
}

function buildPlanFromJobPayload(payload: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!payload) return null

  const clientPlan = extractClientPlanEnvelope(payload)
  const planOfRecord =
    safeRecord(payload.plan_of_record) ?? safeRecord(payload.plan) ?? clientPlan
  const handoff =
    safeRecord(planOfRecord?.handoff_pack) ??
    safeRecord(clientPlan?.handoff_pack) ??
    safeRecord(planOfRecord?.handoff) ??
    safeRecord(clientPlan?.handoff)
  const prompt =
    typeof payload.prompt === 'string' && payload.prompt.trim() ? payload.prompt.trim() : ''
  const planSteps = extractPlanOfRecordSteps(planOfRecord)
  const planId =
    normalizeId(clientPlan?.plan_id) ||
    normalizeId(planOfRecord?.plan_id) ||
    normalizeId(handoff?.plan_id) ||
    normalizeId(safeRecord(payload.plan_summary)?.plan_id)
  const version =
    typeof clientPlan?.version === 'number'
      ? clientPlan.version
      : typeof planOfRecord?.version === 'number'
        ? planOfRecord.version
        : typeof handoff?.version === 'number'
          ? handoff.version
          : null
  const workflowId =
    normalizeId(clientPlan?.workflow_id) ||
    normalizeId(planOfRecord?.workflow_id) ||
    normalizeId(handoff?.workflow_id)
  const datasetRef = pickDatasetRef(clientPlan) || pickDatasetRef(planOfRecord)

  if (clientPlan) {
    const merged: Record<string, unknown> = { ...clientPlan }
    if (!merged.prompt && prompt) merged.prompt = prompt
    if (!merged.intent && prompt) merged.intent = prompt
    if (!Array.isArray(merged.steps) && planSteps.length) merged.steps = planSteps
    if (!normalizeId(merged.plan_id) && planId) merged.plan_id = planId
    if (merged.version == null && version != null) merged.version = version
    if (!normalizeId(merged.workflow_id) && workflowId) merged.workflow_id = workflowId
    if (!normalizeId(merged.dataset_ref) && datasetRef) merged.dataset_ref = datasetRef
    if (!normalizeId(merged.dataset_id) && datasetRef) merged.dataset_id = datasetRef
    if (!safeRecord(merged.handoff_pack) && handoff) merged.handoff_pack = handoff
    if (!safeRecord(merged.handoff) && handoff) merged.handoff = handoff
    if (!safeRecord(merged.parameters)) {
      const payloadParams = safeRecord(payload.parameters)
      if (payloadParams) merged.parameters = payloadParams
    }
    return merged
  }

  const runSummary = safeRecord(planOfRecord?.run_summary)
  const analysisId = normalizeId(runSummary?.analysis_id)
  const pipelineId = normalizeId(runSummary?.pipeline_id)
  const templateId =
    analysisId && pipelineId ? `${analysisId}/${pipelineId}` : normalizeId(runSummary?.template_id)
  const payloadParams = safeRecord(payload.parameters)

  if (!planOfRecord && !payloadParams && !prompt) return null

  return {
    ...(planId ? { plan_id: planId } : {}),
    ...(version != null ? { version } : {}),
    ...(prompt ? { prompt, intent: prompt } : {}),
    ...(payloadParams ? { parameters: payloadParams } : {}),
    ...(datasetRef ? { dataset_ref: datasetRef, dataset_id: datasetRef } : {}),
    ...(workflowId ? { workflow_id: workflowId } : {}),
    ...(analysisId ? { analysis_id: analysisId } : {}),
    ...(pipelineId ? { pipeline_id: pipelineId } : {}),
    ...(templateId ? { template_id: templateId } : {}),
    ...(handoff ? { handoff } : {}),
    ...(planSteps.length ? { steps: planSteps } : {}),
  }
}

function extractMethodsText(raw: unknown): string | null {
  const runcard = safeRecord(raw)
  if (!runcard) return null

  const direct = runcard.methods
  if (typeof direct === 'string' && direct.trim()) return direct.trim()

  const methodsObj = safeRecord(direct)
  const nestedText = methodsObj?.text
  if (typeof nestedText === 'string' && nestedText.trim()) return nestedText.trim()

  return null
}

function extractParameters(raw: unknown): Record<string, unknown> | null {
  const runcard = safeRecord(raw)
  if (!runcard) return null

  const inputs = safeRecord(runcard.inputs)
  if (!inputs) return null

  return safeRecord(inputs.parameters)
}

function formatValue(value: unknown, maxLen = 180): string {
  if (value == null) return 'null'
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed.length > maxLen) return `${trimmed.slice(0, maxLen)}…`
    return trimmed
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const preview = value.slice(0, 6).map((v) => formatValue(v, 40)).join(', ')
    return value.length > 6 ? `[${preview}, …]` : `[${preview}]`
  }
  if (typeof value === 'object') {
    try {
      const json = JSON.stringify(value)
      return json.length > maxLen ? `${json.slice(0, maxLen)}…` : json
    } catch {
      return '[object]'
    }
  }
  return String(value)
}

function extractToolVersions(raw: unknown): Array<{ name: string; version?: string }> {
  const runcard = safeRecord(raw)
  if (!runcard) return []

  const byName = new Map<string, { name: string; version?: string }>()

  const reproducibility = safeRecord(runcard.reproducibility)
  const versions = safeRecord(reproducibility?.versions)
  if (versions) {
    for (const [name, version] of Object.entries(versions)) {
      const key = name.toLowerCase()
      const versionStr = typeof version === 'string' && version.trim() ? version.trim() : undefined
      byName.set(key, { name, version: versionStr })
    }
  }

  const provenance = safeRecord(runcard.provenance)
  const tools = provenance?.tools
  if (Array.isArray(tools)) {
    for (const entry of tools) {
      if (typeof entry === 'string' && entry.trim()) {
        const key = entry.trim().toLowerCase()
        const existing = byName.get(key)
        byName.set(key, existing ?? { name: entry.trim() })
        continue
      }
      const toolObj = safeRecord(entry)
      if (!toolObj) continue
      const name = typeof toolObj.name === 'string' ? toolObj.name.trim() : ''
      if (!name) continue
      const version = typeof toolObj.version === 'string' ? toolObj.version.trim() : undefined
      const key = name.toLowerCase()
      const existing = byName.get(key)
      if (!existing || (!existing.version && version)) {
        byName.set(key, { name, version })
      }
    }
  }

  const legacyEnv = safeRecord(runcard.environment)
  if (legacyEnv) {
    for (const [key, value] of Object.entries(legacyEnv)) {
      if (!key.toLowerCase().endsWith('_version')) continue
      const name = key.replace(/_version$/i, '').replace(/_/g, ' ').trim()
      if (!name) continue
      const version = typeof value === 'string' && value.trim() ? value.trim() : undefined
      const mapKey = name.toLowerCase()
      const existing = byName.get(mapKey)
      if (!existing || (!existing.version && version)) {
        byName.set(mapKey, { name, version })
      }
    }
  }

  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
}

function extractExecutionSteps(raw: unknown): Array<{ name: string; tool?: string }> {
  const runcard = safeRecord(raw)
  if (!runcard) return []

  const execution = safeRecord(runcard.execution)
  const steps = execution?.steps
  if (!Array.isArray(steps)) return []

  const items: Array<{ name: string; tool?: string }> = []
  for (const step of steps.slice(0, 12)) {
    const obj = safeRecord(step)
    if (!obj) continue
    const name =
      (typeof obj.name === 'string' && obj.name.trim()) ||
      (typeof obj.tool === 'string' && obj.tool.trim()) ||
      ''
    if (!name) continue
    const tool = typeof obj.tool === 'string' && obj.tool.trim() ? obj.tool.trim() : undefined
    items.push({ name: name.trim(), tool })
  }
  return items
}

function extractDetailSteps(args: {
  runcard: unknown | null
  plan: Record<string, unknown> | null
  payload: Record<string, unknown> | null
  job: Record<string, unknown> | null
  status: AnalysisStatus
}): AnalysisStepSummary[] {
  const items: AnalysisStepSummary[] = []
  const seen = new Map<string, number>()
  const addStep = (step: Record<string, unknown>) => {
    const id = normalizeId(step.id) || normalizeId(step.step_id)
    const name =
      normalizeId(step.name) ||
      normalizeId(step.label) ||
      normalizeId(step.tool) ||
      normalizeId(step.stage) ||
      ''
    if (!name) return
    const status = normalizeId(step.status) || normalizeId(step.state)
    const tool = normalizeId(step.tool)
    const detail =
      normalizeId(step.detail) ||
      normalizeId(step.message) ||
      normalizeId(step.preview) ||
      normalizeId(step.error) ||
      normalizeId(step.error_message)
    const key = id || `${name}:${tool}:${status}`
    const next = {
      ...(id ? { id } : {}),
      name,
      ...(status ? { status } : {}),
      ...(tool ? { tool } : {}),
      ...(detail ? { detail } : {}),
    }
    const existingIndex = seen.get(key)
    if (existingIndex != null) {
      const existing = items[existingIndex]
      if (!existing.status && next.status) existing.status = next.status
      if (!existing.tool && next.tool) existing.tool = next.tool
      if (!existing.detail && next.detail) existing.detail = next.detail
      return
    }
    seen.set(key, items.length)
    items.push(next)
  }

  const jobProgress = args.job?.step_progress
  if (Array.isArray(jobProgress)) {
    jobProgress.map(safeRecord).forEach((step) => {
      if (step) addStep(step)
    })
  }

  const payloadSteps = args.payload?.steps
  if (Array.isArray(payloadSteps)) {
    payloadSteps.map(safeRecord).forEach((step) => {
      if (step) addStep(step)
    })
  }

  const execution = safeRecord(safeRecord(args.runcard)?.execution)
  const executionSteps = execution?.steps
  if (Array.isArray(executionSteps)) {
    executionSteps.map(safeRecord).forEach((step) => {
      if (step) addStep(step)
    })
  }

  const planSteps = args.plan?.steps
  if (Array.isArray(planSteps)) {
    planSteps.map(safeRecord).forEach((step) => {
      if (step) addStep(step)
    })
  }

  return coerceFailedPlaceholderSteps({
    items: items.slice(0, 12),
    status: args.status,
    job: args.job,
    payload: args.payload,
  })
}

function failureDetail(args: {
  job: Record<string, unknown> | null
  payload: Record<string, unknown> | null
}): string {
  const metadata = safeRecord(args.payload?.metadata)
  return (
    normalizeId(args.job?.error_message) ||
    normalizeId(args.job?.error) ||
    normalizeId(args.payload?.error_message) ||
    normalizeId(args.payload?.error) ||
    normalizeId(metadata?.error_message) ||
    normalizeId(metadata?.error) ||
    'Job failed before step logs were captured.'
  )
}

function isPendingLikeStep(step: AnalysisStepSummary): boolean {
  const status = (step.status || '').trim().toLowerCase()
  return (
    (!status || status === 'pending' || status === 'queued' || status === 'claimed' || status === 'unknown') &&
    !step.detail
  )
}

function coerceFailedPlaceholderSteps(args: {
  items: AnalysisStepSummary[]
  status: AnalysisStatus
  job: Record<string, unknown> | null
  payload: Record<string, unknown> | null
}): AnalysisStepSummary[] {
  if (args.status !== 'failed' && args.status !== 'timeout') return args.items

  const detail = failureDetail({ job: args.job, payload: args.payload })
  if (!args.items.length) {
    return [
      {
        id: 'job_failed',
        name: args.status === 'timeout' ? 'Job timed out' : 'Job failed',
        status: args.status,
        detail,
      },
    ]
  }

  if (!args.items.every(isPendingLikeStep)) return args.items

  return args.items.map((step, index) => ({
    ...step,
    status: index === 0 ? args.status : 'skipped',
    ...(index === 0 ? { detail } : {}),
  }))
}

function artifactLooksLikeLog(artifact: Record<string, unknown>): boolean {
  const text = [
    artifact.name,
    artifact.file_name,
    artifact.path,
    artifact.type,
    artifact.mime_type,
  ]
    .map((value) => (typeof value === 'string' ? value.toLowerCase() : ''))
    .join(' ')
  return /\b(log|stdout|stderr|trace|events|command)\b/.test(text) || /\.(log|txt|jsonl)$/i.test(text)
}

function extractLogsSummary(args: {
  artifacts: unknown[] | null
  runcard: unknown | null
  job: Record<string, unknown> | null
}): AnalysisLogSummary[] {
  const items: AnalysisLogSummary[] = []
  const seen = new Set<string>()
  const add = (entry: Record<string, unknown>) => {
    const name =
      normalizeId(entry.name) ||
      normalizeId(entry.file_name) ||
      normalizeId(entry.path) ||
      normalizeId(entry.url)
    if (!name) return
    const path = normalizeId(entry.path)
    const url = normalizeId(entry.download_url) || normalizeId(entry.url)
    const kind = normalizeId(entry.type) || normalizeId(entry.mime_type) || normalizeId(entry.kind)
    const key = path || url || name
    if (seen.has(key)) return
    seen.add(key)
    items.push({
      name,
      ...(path ? { path } : {}),
      ...(url ? { url } : {}),
      ...(kind ? { kind } : {}),
    })
  }

  if (Array.isArray(args.artifacts)) {
    args.artifacts.map(safeRecord).forEach((artifact) => {
      if (artifact && artifactLooksLikeLog(artifact)) add(artifact)
    })
  }

  const runcardLogs = safeRecord(args.runcard)?.logs
  if (Array.isArray(runcardLogs)) {
    runcardLogs.map(safeRecord).forEach((log) => {
      if (log) add(log)
    })
  }

  const jobLogs = args.job?.logs
  if (Array.isArray(jobLogs)) {
    jobLogs.map(safeRecord).forEach((log) => {
      if (log) add(log)
    })
  }

  return items.slice(0, 10)
}

function extractHandoffPack(args: {
  plan: Record<string, unknown> | null
  payload: Record<string, unknown> | null
}): Record<string, unknown> | null {
  const metadata = safeRecord(args.payload?.metadata)
  const metadataParameters = safeRecord(metadata?.parameters)
  const clientMetadata = safeRecord(metadataParameters?._client_metadata)
  return (
    safeRecord(args.plan?.handoff_pack) ??
    safeRecord(args.plan?.handoff) ??
    safeRecord(args.payload?.handoff_pack) ??
    safeRecord(args.payload?.handoff) ??
    safeRecord(metadata?.handoff_pack) ??
    safeRecord(clientMetadata?.handoff_pack) ??
    null
  )
}

function extractExecutionStatus(args: {
  plan: Record<string, unknown> | null
  payload: Record<string, unknown> | null
  handoffPack: Record<string, unknown> | null
}): Record<string, unknown> | null {
  const metadata = safeRecord(args.payload?.metadata)
  const metadataParameters = safeRecord(metadata?.parameters)
  const clientMetadata = safeRecord(metadataParameters?._client_metadata)
  return (
    safeRecord(args.plan?.execution_status) ??
    safeRecord(args.payload?.execution_status) ??
    safeRecord(metadata?.execution_status) ??
    safeRecord(clientMetadata?.execution_status) ??
    safeRecord(args.handoffPack?.execution_status) ??
    null
  )
}

function extractArtifactContract(
  handoffPack: Record<string, unknown> | null,
  plan: Record<string, unknown> | null,
): Record<string, unknown> | null {
  const execution = safeRecord(handoffPack?.execution)
  return (
    safeRecord(execution?.artifact_contract) ??
    safeRecord(handoffPack?.artifact_contract) ??
    safeRecord(plan?.artifact_contract) ??
    null
  )
}

function extractPreflightSnapshot(
  handoffPack: Record<string, unknown> | null,
): AnalysisPreflightSnapshot | null {
  const execution = safeRecord(handoffPack?.execution)
  const launchTrace = safeRecord(handoffPack?.launch_trace)
  const status =
    normalizeId(execution?.preflight_status) ||
    normalizeId(launchTrace?.preflight_status) ||
    normalizeId(handoffPack?.preflight_status)
  const detail =
    normalizeId(execution?.preflight_detail) ||
    normalizeId(launchTrace?.preflight_detail) ||
    normalizeId(handoffPack?.preflight_detail)
  const route =
    normalizeId(execution?.preflight_route) ||
    normalizeId(launchTrace?.preflight_route)
  const rawChecks = Array.isArray(handoffPack?.checks) ? handoffPack.checks : []
  const checks = rawChecks
    .map((check) => safeRecord(check))
    .filter((check): check is Record<string, unknown> => check != null)
    .slice(0, 20)

  if (!status && !detail && !route && checks.length === 0) return null
  return {
    ...(status ? { status } : {}),
    ...(detail ? { detail } : {}),
    ...(route ? { route } : {}),
    ...(checks.length ? { checks } : {}),
  }
}

function extractDatasetSummary(raw: unknown): { id?: string; name?: string; source?: string } | null {
  const runcard = safeRecord(raw)
  if (!runcard) return null
  const inputs = safeRecord(runcard.inputs)
  const datasets = inputs?.datasets
  if (!Array.isArray(datasets) || datasets.length === 0) return null
  const first = safeRecord(datasets[0])
  if (!first) return null
  const id = typeof first.id === 'string' && first.id.trim() ? first.id.trim() : undefined
  const name = typeof first.name === 'string' && first.name.trim() ? first.name.trim() : undefined
  const source = typeof first.source === 'string' && first.source.trim() ? first.source.trim() : undefined
  if (!id && !name && !source) return null
  return { id, name, source }
}

function extractPlanSteps(plan: Record<string, unknown> | null): Array<{ name: string; tool?: string }> {
  if (!plan) return []
  const steps = plan.steps
  if (!Array.isArray(steps)) return []

  const items: Array<{ name: string; tool?: string }> = []
  for (const step of steps.slice(0, 12)) {
    const obj = safeRecord(step)
    if (!obj) continue
    const tool = typeof obj.tool === 'string' && obj.tool.trim() ? obj.tool.trim() : undefined
    const name = tool || (typeof obj.name === 'string' && obj.name.trim() ? obj.name.trim() : 'Step')
    items.push({ name, tool })
  }
  return items
}

function buildDraftMethodsText(args: {
  analysisId: string
  status: AnalysisStatus
  dataset: {
    id: string
    name: string
    source_repo: string
    subjects_count?: number
    sessions_count?: number
    modalities?: string[]
  } | null
  datasetId: string
  templateId: string
  parameters: Record<string, unknown> | null
  runcard: unknown | null
  plan: Record<string, unknown> | null
  warnings: string[]
}): string {
  const lines: string[] = []
  lines.push('Draft Methods (auto-generated)')
  lines.push('')
  lines.push('This draft was generated from execution metadata and may need edits before publication.')
  lines.push('')

  const datasetFromRuncard = args.runcard ? extractDatasetSummary(args.runcard) : null

  if (args.dataset) {
    const modalities =
      Array.isArray(args.dataset.modalities) && args.dataset.modalities.length
        ? `; modalities: ${args.dataset.modalities.join(', ')}`
        : ''
    const subjects = typeof args.dataset.subjects_count === 'number' ? `; subjects: ${args.dataset.subjects_count}` : ''
    const sessions = typeof args.dataset.sessions_count === 'number' ? `; sessions: ${args.dataset.sessions_count}` : ''
    lines.push(
      `Dataset: ${args.dataset.name} (${args.dataset.id}); source: ${args.dataset.source_repo}${subjects}${sessions}${modalities}`,
    )
  } else if (datasetFromRuncard) {
    const label = datasetFromRuncard.name || datasetFromRuncard.id || 'Unknown dataset'
    const id = datasetFromRuncard.id && datasetFromRuncard.name ? ` (${datasetFromRuncard.id})` : ''
    const source = datasetFromRuncard.source ? `; source: ${datasetFromRuncard.source}` : ''
    lines.push(`Dataset: ${label}${id}${source}`)
  } else if (args.datasetId) {
    lines.push(`Dataset: ${args.datasetId}`)
  }

  if (args.templateId) {
    lines.push(`Workflow: ${args.templateId}`)
  }

  lines.push(`Run ID: ${args.analysisId}`)
  lines.push(`Status: ${args.status}`)

  const tools = args.runcard ? extractToolVersions(args.runcard) : []
  const toolsLineFromRuncard = tools.length
    ? tools
        .slice(0, 8)
        .map((t) => (t.version ? `${t.name} ${t.version}` : t.name))
        .join('; ')
    : ''

  const planTools = (() => {
    const planSteps = extractPlanSteps(args.plan)
    const unique = Array.from(new Set(planSteps.map((s) => s.tool || s.name).filter(Boolean)))
    return unique.slice(0, 8).join('; ')
  })()

  const toolsLine = toolsLineFromRuncard || planTools
  if (toolsLine) {
    lines.push(`Tools: ${toolsLine}${tools.length > 8 ? '; …' : ''}`)
  }

  const parameters = args.parameters
  const keyParams: Array<{ label: string; value: unknown }> = []
  if (parameters) {
    const pick = (label: string, keys: string[]) => {
      for (const key of keys) {
        if (!(key in parameters)) continue
        const value = (parameters as any)[key]
        if (value == null) continue
        keyParams.push({ label, value })
        return
      }
    }

    pick('Smoothing (FWHM)', ['smoothing_fwhm', 'smoothing', 'fwhm', 'smoothing_mm'])
    pick('HRF model', ['hrf_model'])
    pick('High-pass filter', ['high_pass', 'highpass', 'high_pass_hz', 'high_pass_sec'])
    pick('Voxel-wise threshold', ['threshold', 'p_threshold', 'voxel_p', 'p_value', 'p'])
    pick('Cluster threshold', ['cluster_threshold', 'cluster_size', 'min_cluster_size'])
    pick('Multiple comparisons', ['correction', 'multiple_comparisons', 'fdr', 'fwe'])
    pick('Atlas/parcellation', ['atlas', 'parcellation', 'roi_atlas'])
    pick('Confounds', ['confounds_strategy', 'confounds'])
    pick('Random seed', ['random_seed', 'seed'])
  }

  if (keyParams.length) {
    lines.push('')
    lines.push('Key parameters:')
    for (const item of keyParams) {
      lines.push(`- ${item.label}: ${formatValue(item.value)}`)
    }
  }

  const stepItems = args.runcard ? extractExecutionSteps(args.runcard) : []
  const steps = stepItems.length ? stepItems : extractPlanSteps(args.plan)
  if (steps.length) {
    lines.push('')
    lines.push('Execution steps:')
    steps.forEach((step, idx) => {
      lines.push(`${idx + 1}. ${step.name}${step.tool ? ` (${step.tool})` : ''}`)
    })
  }

  if (args.warnings.length) {
    lines.push('')
    lines.push('Note: Some metadata sources were unavailable; this draft may be incomplete.')
  }

  return lines.join('\n')
}

export async function buildAnalysisDetail(args: {
  analysisId: string
  headers: Headers
}): Promise<BuildResult> {
  const analysisId = normalizeId(args.analysisId)
  if (!analysisId) {
    return { ok: false, status: 400, body: { detail: 'analysisId is required.' } }
  }

  const headers = args.headers
  const orchBase = resolveOrchestratorBaseUrl()

  // Internal orchestrator calls (server-only) to hydrate analysis details.
  const [orchJob, orchObservation] = await Promise.all([
    fetchJson(`${orchBase}/api/jobs/${encodeURIComponent(analysisId)}`, { method: 'GET', headers }),
    fetchJson(`${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/observation`, { method: 'GET', headers }),
  ])

  const synthResponse = (ok: boolean, status: number, json: unknown | null, text = '') => ({
    ok,
    status,
    json,
    text,
  })

  let orchRuncard = synthResponse(false, 404, null, '')
  let orchArtifacts = synthResponse(false, 404, null, '')

  const observationRecord = safeRecord(orchObservation.json)
  const observationRunCard =
    observationRecord?.run_card ?? observationRecord?.runCard ?? null
  const observationArtifacts = observationRecord?.artifacts ?? null

  if (observationRunCard) {
    orchRuncard = synthResponse(true, orchObservation.status, observationRunCard)
  }
  if (Array.isArray(observationArtifacts) && observationArtifacts.length > 0) {
    orchArtifacts = synthResponse(true, orchObservation.status, observationArtifacts)
  }

  if (!orchRuncard.ok) {
    orchRuncard = await fetchJson(
      `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/runcard`,
      { method: 'GET', headers },
    )
  }
  if (!orchArtifacts.ok) {
    orchArtifacts = await fetchJson(
      `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/artifacts`,
      { method: 'GET', headers },
    )
  }

  const internalWarnings: string[] = []
  const warnings: string[] = []

  const jobJson = safeRecord(orchJob.json)
  const jobPayload = parsePayloadJson(jobJson?.payload_json)
  const jobMetadata = safeRecord(jobPayload?.metadata)

  if (!orchObservation.ok) {
    internalWarnings.push(`orchestrator:/api/jobs/${analysisId}/observation -> ${orchObservation.status}`)
  }
  if (!orchJob.ok) {
    internalWarnings.push(`orchestrator:/api/jobs/${analysisId} -> ${orchJob.status}`)
    warnings.push('Some job status metadata is temporarily unavailable.')
  }

  if (!orchJob.ok) {
    if (orchJob.status === 404) {
      return { ok: false, status: 404, body: { detail: 'Run not found.', warnings } }
    }

    return { ok: false, status: 502, body: { detail: 'Upstream unavailable.', warnings } }
  }

  const runId = normalizeId(jobJson?.run_id) || analysisId
  const jobId = normalizeId((jobJson as any)?.job_id) || normalizeId((jobJson as any)?.id) || analysisId

  const jobStatus = normalizeStatus(jobJson?.status)
  const status = jobStatus

  const isActive =
    status === 'pending' ||
    status === 'queued' ||
    status === 'running' ||
    status === 'retrying' ||
    status === 'cancelling'

  if (!orchRuncard.ok) {
    internalWarnings.push(`orchestrator:/api/jobs/${analysisId}/runcard -> ${orchRuncard.status}`)
    if (!(isActive && orchRuncard.status === 404)) {
      warnings.push('Result package metadata is not available yet.')
    }
  }
  if (!orchArtifacts.ok) {
    internalWarnings.push(`orchestrator:/api/jobs/${analysisId}/artifacts -> ${orchArtifacts.status}`)
    if (!(isActive && orchArtifacts.status === 404)) {
      warnings.push('Some result artifacts are not available yet.')
    }
  }

  const jobCreatedAt = toEpochSeconds(jobJson?.created_at)
  const createdAt = jobCreatedAt

  const jobStartedAt = toEpochSeconds(jobJson?.started_at)
  const startedAt = jobStartedAt

  const jobFinishedAt = toEpochSeconds(jobJson?.completed_at) ?? toEpochSeconds(jobJson?.finished_at)
  const finishedAt = jobFinishedAt

  const plan = buildPlanFromJobPayload(jobPayload)
  const parametersFromPlan = safeRecord(plan?.parameters)
  const parametersFromRuncard = orchRuncard.ok ? extractParameters(orchRuncard.json) : null
  const parameters =
    parametersFromPlan && Object.keys(parametersFromPlan).length
      ? parametersFromPlan
      : parametersFromRuncard

  const datasetId =
    normalizeId(plan?.dataset_id) || normalizeId(parameters?.dataset_id) || ''
  const dataset = datasetId ? getDataset(datasetId) : null

  const analysisPresetId = normalizeId(parameters?.analysis_id)
  const pipelinePresetId = normalizeId(parameters?.pipeline_id)
  const templateId =
    analysisPresetId && pipelinePresetId ? `${analysisPresetId}/${pipelinePresetId}` : normalizeId(plan?.template_id) || ''

  const title =
    (typeof jobPayload?.name === 'string' && jobPayload.name.trim()) ||
    (typeof plan?.intent === 'string' && plan.intent.trim()) ||
    (typeof plan?.prompt === 'string' && plan.prompt.trim().slice(0, 120)) ||
    `Run ${analysisId.slice(0, 8)}`

  const explicitMethodsText = orchRuncard.ok ? extractMethodsText(orchRuncard.json) : null
  const draftMethodsText = explicitMethodsText
    ? null
    : buildDraftMethodsText({
        analysisId,
        status,
        dataset,
        datasetId,
        templateId,
        parameters,
        runcard: orchRuncard.ok ? orchRuncard.json : null,
        plan,
        warnings: internalWarnings,
      })

  const normalizedArtifacts = (() => {
    if (!orchArtifacts.ok) return null
    if (Array.isArray(orchArtifacts.json)) return orchArtifacts.json
    const obj = safeRecord(orchArtifacts.json)
    if (obj && Array.isArray(obj.artifacts)) return obj.artifacts
    return []
  })()

  const handoffPack = extractHandoffPack({ plan, payload: jobPayload })
  const executionStatus = extractExecutionStatus({ plan, payload: jobPayload, handoffPack })
  const artifactContract = extractArtifactContract(handoffPack, plan)
  const preflight = extractPreflightSnapshot(handoffPack)
  const launchTrace = safeRecord(handoffPack?.launch_trace)
  const stepsSummary = extractDetailSteps({
    runcard: orchRuncard.ok ? orchRuncard.json : null,
    plan,
    payload: jobPayload,
    job: jobJson as Record<string, unknown>,
    status,
  })
  const logsSummary = extractLogsSummary({
    artifacts: normalizedArtifacts,
    runcard: orchRuncard.ok ? orchRuncard.json : null,
    job: jobJson as Record<string, unknown>,
  })

  const detail: AnalysisDetail = {
    analysis_id: analysisId,
    run_id: runId,
    job_id: jobId,
    thread_id:
      normalizeId(jobJson?.session_id) ||
      normalizeId(jobMetadata?.thread_id) ||
      normalizeId(safeRecord(jobMetadata?.client_plan_envelope)?.thread_id) ||
      null,
    status,
    created_at: createdAt,
    started_at: startedAt,
    finished_at: finishedAt,
    title,
    dataset: dataset
      ? { dataset_id: dataset.id, name: dataset.name, source: dataset.source_repo }
      : datasetId
        ? { dataset_id: datasetId }
        : undefined,
    template: templateId
      ? { template_id: templateId, analysis_id: analysisPresetId || undefined, pipeline_id: pipelinePresetId || undefined }
      : undefined,
    plan,
    parameters,
    methods: explicitMethodsText
      ? { text: explicitMethodsText, generated: false }
      : draftMethodsText
        ? { text: draftMethodsText, generated: true }
        : null,
    artifacts: normalizedArtifacts,
    runcard: orchRuncard.ok ? orchRuncard.json : null,
    job: orchJob.ok ? (jobJson as Record<string, unknown>) : null,
    handoff_pack: handoffPack,
    execution_status: executionStatus,
    artifact_contract: artifactContract,
    preflight,
    launch_trace: launchTrace,
    steps_summary: stepsSummary,
    logs_summary: logsSummary,
    warnings: warnings.length ? warnings : undefined,
  }

  return { ok: true, detail }
}
