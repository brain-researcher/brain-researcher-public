import fs from 'fs'
import path from 'path'

export type DemoBundleReplaySource = 'runcard' | 'bundle_steps' | 'synthetic'
export type DemoBundleFallbackLevel = 'none' | 'partial' | 'synthetic'
export type DemoBundleSummaryKind = 'answer' | 'query' | 'synthetic'
export type DemoBundlePromptOrigin = 'runcard' | 'bundle' | 'none'
export type DemoBundleResponseOrigin = 'runcard' | 'bundle' | 'none'

export type DemoRunBundleArtifactRole =
  | 'prompt_source'
  | 'reference_summary_source'
  | 'evidence'
  | 'runbook'
  | 'figure'
  | 'artifact'

export type DemoRunBundleArtifact = {
  id: string
  path: string
  mime_type?: string
  roles: DemoRunBundleArtifactRole[]
  stage?: string | null
  title?: string | null
}

export type DemoRunBundlePromptPack = {
  primary_prompt: string
  source_artifact_id?: string | null
  followup_prompts?: string[]
  coding_agent_prompts?: string[]
  mcp_prompts?: string[]
}

export type DemoRunBundleReferenceOutput = {
  summary: string
  summary_kind?: DemoBundleSummaryKind
  source_artifact_id?: string | null
  document_ids?: string[]
  highlights?: string[]
  generated_at?: string | null
  dataset_version?: string | null
}

export type DemoRunBundleReplayStep = {
  step_id: string
  stage: string
  title: string
  status: 'completed' | 'running' | 'failed' | 'pending'
  tool?: string | null
  tool_calls?: string[]
  prompt_text?: string | null
  response_text?: string | null
  prompt_origin?: DemoBundlePromptOrigin
  response_origin?: DemoBundleResponseOrigin
  artifact_ref_ids?: string[]
  started_at?: number | null
  finished_at?: number | null
  duration_ms?: number | null
}

export type DemoRunBundleReplay = {
  source: DemoBundleReplaySource
  steps: DemoRunBundleReplayStep[]
}

export type DemoRunBundleFallback = {
  level: DemoBundleFallbackLevel
  reasons: string[]
}

export type DemoRunBundle = {
  schema_version?: string
  generated_at?: string
  demo?: Record<string, unknown>
  source_run_ids?: string[]
  artifact_count?: number
  artifacts?: DemoRunBundleArtifact[]
  prompt_pack?: DemoRunBundlePromptPack
  reference_output?: DemoRunBundleReferenceOutput
  replay?: DemoRunBundleReplay
  fallback?: DemoRunBundleFallback
  // legacy compatibility during migration
  matched_artifacts?: string[]
}

export type DemoRunBundleSummary = {
  available: boolean
  artifact_count: number
  generated_at?: string
  source_run_ids: string[]
}

const RUN_BUNDLE_FILENAME = 'run_bundle.json'
const STAGE_PATTERN = /^R[0-5]$/i
const ALLOWED_ROLES = new Set<DemoRunBundleArtifactRole>([
  'prompt_source',
  'reference_summary_source',
  'evidence',
  'runbook',
  'figure',
  'artifact',
])

function isSafeSlug(value: string): boolean {
  return /^[a-zA-Z0-9_-]+$/.test(value)
}

function resolveBundlesRoot(): string | null {
  const override =
    process.env.BR_DEMO_RUN_BUNDLE_ROOT || process.env.DEMO_RUN_BUNDLE_ROOT
  const candidates = [
    override ? path.resolve(override) : null,
    path.resolve(process.cwd(), 'configs', 'demo', 'run_bundles'),
    path.resolve(process.cwd(), '..', 'configs', 'demo', 'run_bundles'),
    path.resolve(process.cwd(), '..', '..', 'configs', 'demo', 'run_bundles'),
    path.resolve(process.cwd(), '..', '..', '..', 'configs', 'demo', 'run_bundles'),
    path.resolve(process.cwd(), 'data', 'demo_runs'),
    path.resolve(process.cwd(), '..', 'data', 'demo_runs'),
    path.resolve(process.cwd(), '..', '..', 'data', 'demo_runs'),
    path.resolve(process.cwd(), '..', '..', '..', 'data', 'demo_runs'),
  ].filter(Boolean) as string[]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  return override ? path.resolve(override) : null
}

function safeRecord(raw: unknown): Record<string, unknown> | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  return raw as Record<string, unknown>
}

function safeString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function toArrayOfStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item) => typeof item === 'string')
    .map((item) => String(item).trim())
    .filter(Boolean)
}

function normalizeStage(value: unknown): string | null {
  const raw = safeString(value).toUpperCase()
  if (!raw || !STAGE_PATTERN.test(raw)) return null
  return raw
}

function inferMimeType(filePath: string): string {
  const lower = filePath.toLowerCase()
  if (lower.endsWith('.json')) return 'application/json'
  if (lower.endsWith('.yaml') || lower.endsWith('.yml')) return 'application/yaml'
  if (lower.endsWith('.md')) return 'text/markdown; charset=utf-8'
  if (lower.endsWith('.csv')) return 'text/csv; charset=utf-8'
  if (lower.endsWith('.txt')) return 'text/plain; charset=utf-8'
  if (lower.endsWith('.pdf')) return 'application/pdf'
  if (lower.endsWith('.png')) return 'image/png'
  if (lower.endsWith('.svg')) return 'image/svg+xml'
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg'
  return 'application/octet-stream'
}

function dedupeArtifacts(artifacts: DemoRunBundleArtifact[]): DemoRunBundleArtifact[] {
  const seen = new Set<string>()
  const out: DemoRunBundleArtifact[] = []
  for (const artifact of artifacts) {
    const key = artifact.id || artifact.path
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(artifact)
  }
  return out
}

function safeArtifact(raw: unknown, index: number): DemoRunBundleArtifact | null {
  const item = safeRecord(raw)
  if (!item) return null
  const id = safeString(item.id) || `artifact_${index + 1}`
  const pathValue = safeString(item.path)
  if (!pathValue) return null
  const rolesRaw = toArrayOfStrings(item.roles)
  const roles = rolesRaw
    .map((role) => role as DemoRunBundleArtifactRole)
    .filter((role) => ALLOWED_ROLES.has(role))
  const mimeType = safeString(item.mime_type) || inferMimeType(pathValue)
  return {
    id,
    path: pathValue,
    mime_type: mimeType,
    roles: roles.length > 0 ? roles : ['artifact'],
    stage: normalizeStage(item.stage),
    title: safeString(item.title) || null,
  }
}

function safePromptPack(raw: unknown): DemoRunBundlePromptPack | undefined {
  const value = safeRecord(raw)
  if (!value) return undefined
  const primary = safeString(value.primary_prompt)
  if (!primary) return undefined
  return {
    primary_prompt: primary,
    source_artifact_id: safeString(value.source_artifact_id) || null,
    followup_prompts: toArrayOfStrings(value.followup_prompts),
    coding_agent_prompts: toArrayOfStrings(value.coding_agent_prompts),
    mcp_prompts: toArrayOfStrings(value.mcp_prompts),
  }
}

function safeReferenceOutput(raw: unknown): DemoRunBundleReferenceOutput | undefined {
  const value = safeRecord(raw)
  if (!value) return undefined
  const summary = safeString(value.summary)
  if (!summary) return undefined
  const summaryKindRaw = safeString(value.summary_kind) as DemoBundleSummaryKind
  const summaryKind: DemoBundleSummaryKind =
    summaryKindRaw === 'answer' || summaryKindRaw === 'query' || summaryKindRaw === 'synthetic'
      ? summaryKindRaw
      : 'synthetic'
  return {
    summary,
    summary_kind: summaryKind,
    source_artifact_id: safeString(value.source_artifact_id) || null,
    document_ids: toArrayOfStrings(value.document_ids),
    highlights: toArrayOfStrings(value.highlights),
    generated_at: safeString(value.generated_at) || null,
    dataset_version: safeString(value.dataset_version) || null,
  }
}

function safeReplayStep(raw: unknown, index: number): DemoRunBundleReplayStep | null {
  const step = safeRecord(raw)
  if (!step) return null
  const stepId = safeString(step.step_id) || safeString(step.id) || `step_${index + 1}`
  const stage = normalizeStage(step.stage) || `R${Math.min(index + 1, 5)}`
  const title = safeString(step.title) || `Step ${index + 1}`
  const statusRaw = safeString(step.status).toLowerCase()
  const status: DemoRunBundleReplayStep['status'] =
    statusRaw === 'completed' || statusRaw === 'running' || statusRaw === 'failed'
      ? statusRaw
      : 'pending'
  const promptOriginRaw = safeString(step.prompt_origin) as DemoBundlePromptOrigin
  const promptOrigin: DemoBundlePromptOrigin =
    promptOriginRaw === 'runcard' || promptOriginRaw === 'bundle'
      ? promptOriginRaw
      : 'none'
  const responseOriginRaw = safeString(step.response_origin) as DemoBundleResponseOrigin
  const responseOrigin: DemoBundleResponseOrigin =
    responseOriginRaw === 'runcard' || responseOriginRaw === 'bundle'
      ? responseOriginRaw
      : 'none'
  const startedAt = typeof step.started_at === 'number' ? step.started_at : null
  const finishedAt = typeof step.finished_at === 'number' ? step.finished_at : null
  const durationMs = typeof step.duration_ms === 'number' ? step.duration_ms : null
  return {
    step_id: stepId,
    stage,
    title,
    status,
    tool: safeString(step.tool) || null,
    tool_calls: toArrayOfStrings(step.tool_calls),
    prompt_text: safeString(step.prompt_text) || null,
    response_text: safeString(step.response_text) || null,
    prompt_origin: promptOrigin,
    response_origin: responseOrigin,
    artifact_ref_ids: toArrayOfStrings(step.artifact_ref_ids),
    started_at: startedAt,
    finished_at: finishedAt,
    duration_ms: durationMs,
  }
}

function safeReplay(raw: unknown): DemoRunBundleReplay | undefined {
  const value = safeRecord(raw)
  if (!value) return undefined
  const sourceRaw = safeString(value.source) as DemoBundleReplaySource
  const source: DemoBundleReplaySource =
    sourceRaw === 'runcard' || sourceRaw === 'bundle_steps' || sourceRaw === 'synthetic'
      ? sourceRaw
      : 'synthetic'
  const rawSteps = Array.isArray(value.steps) ? value.steps : []
  const steps = rawSteps
    .map((item, index) => safeReplayStep(item, index))
    .filter(Boolean) as DemoRunBundleReplayStep[]
  return {
    source,
    steps,
  }
}

function safeFallback(raw: unknown): DemoRunBundleFallback | undefined {
  const value = safeRecord(raw)
  if (!value) return undefined
  const levelRaw = safeString(value.level) as DemoBundleFallbackLevel
  const level: DemoBundleFallbackLevel =
    levelRaw === 'none' || levelRaw === 'partial' || levelRaw === 'synthetic'
      ? levelRaw
      : 'none'
  return {
    level,
    reasons: toArrayOfStrings(value.reasons),
  }
}

function legacyArtifactsFromPaths(paths: string[]): DemoRunBundleArtifact[] {
  return paths.map((entry, index) => ({
    id: `artifact_${index + 1}`,
    path: entry,
    mime_type: inferMimeType(entry),
    roles: ['artifact'],
    stage: null,
    title: null,
  }))
}

function safeBundle(raw: unknown): DemoRunBundle | null {
  const bundle = safeRecord(raw)
  if (!bundle) return null
  const sourceRunIds = toArrayOfStrings(bundle.source_run_ids)
  const rawArtifacts = Array.isArray(bundle.artifacts) ? bundle.artifacts : []
  const parsedArtifacts = rawArtifacts
    .map((item, index) => safeArtifact(item, index))
    .filter(Boolean) as DemoRunBundleArtifact[]
  const matchedArtifacts = toArrayOfStrings(bundle.matched_artifacts)
  const artifacts =
    parsedArtifacts.length > 0
      ? dedupeArtifacts(parsedArtifacts)
      : dedupeArtifacts(legacyArtifactsFromPaths(matchedArtifacts))
  const artifactCount =
    typeof bundle.artifact_count === 'number' && Number.isFinite(bundle.artifact_count)
      ? bundle.artifact_count
      : artifacts.length
  return {
    schema_version: safeString(bundle.schema_version) || undefined,
    generated_at: safeString(bundle.generated_at) || undefined,
    demo: safeRecord(bundle.demo) || undefined,
    source_run_ids: sourceRunIds,
    artifact_count: artifactCount,
    artifacts,
    prompt_pack: safePromptPack(bundle.prompt_pack),
    reference_output: safeReferenceOutput(bundle.reference_output),
    replay: safeReplay(bundle.replay),
    fallback: safeFallback(bundle.fallback),
    matched_artifacts: matchedArtifacts,
  }
}

export function loadDemoRunBundle(slug: string): DemoRunBundle | null {
  const normalized = slug.trim()
  if (!normalized || !isSafeSlug(normalized)) return null
  const root = resolveBundlesRoot()
  if (!root) return null
  const bundlePath = path.join(root, normalized, RUN_BUNDLE_FILENAME)
  try {
    if (!fs.existsSync(bundlePath)) return null
    const raw = fs.readFileSync(bundlePath, 'utf-8')
    const parsed = raw ? JSON.parse(raw) : null
    return safeBundle(parsed)
  } catch {
    return null
  }
}

export function bundleArtifacts(bundle: DemoRunBundle | null): DemoRunBundleArtifact[] {
  if (!bundle) return []
  const direct = Array.isArray(bundle.artifacts) ? bundle.artifacts : []
  if (direct.length > 0) return direct
  const legacy = Array.isArray(bundle.matched_artifacts) ? bundle.matched_artifacts : []
  return legacyArtifactsFromPaths(legacy)
}

export function loadDemoRunBundleSummary(slug: string): DemoRunBundleSummary {
  const bundle = loadDemoRunBundle(slug)
  if (!bundle) {
    return {
      available: false,
      artifact_count: 0,
      source_run_ids: [],
    }
  }
  const artifacts = bundleArtifacts(bundle)
  return {
    available: true,
    artifact_count:
      typeof bundle.artifact_count === 'number' && Number.isFinite(bundle.artifact_count)
        ? bundle.artifact_count
        : artifacts.length,
    generated_at: bundle.generated_at,
    source_run_ids: bundle.source_run_ids || [],
  }
}

export function resolveBundleArtifactFile(
  slug: string,
  rawArtifactPath: string,
): { filePath: string; mimeType: string } | null {
  const normalizedSlug = slug.trim()
  if (!normalizedSlug || !isSafeSlug(normalizedSlug)) return null
  const bundle = loadDemoRunBundle(normalizedSlug)
  if (!bundle) return null

  const requestedPath = rawArtifactPath.trim().replace(/\\/g, '/')
  if (
    !requestedPath ||
    requestedPath.includes('..') ||
    requestedPath.startsWith('/') ||
    requestedPath.includes('\0')
  ) {
    return null
  }

  const toAbsoluteCandidates = (entryPath: string): string[] => {
    if (path.isAbsolute(entryPath)) {
      return [path.resolve(entryPath)]
    }
    const cwd = process.cwd()
    return [
      path.resolve(cwd, entryPath),
      path.resolve(cwd, '..', entryPath),
      path.resolve(cwd, '..', '..', entryPath),
      path.resolve(cwd, '..', '..', '..', entryPath),
    ]
  }

  const artifacts = bundleArtifacts(bundle)
  const candidates = artifacts.map((entry) => {
    const clean = entry.path.replace(/\\/g, '/').trim()
    if (!clean) return null
    const canonical = clean.startsWith('./') ? clean.slice(2) : clean
    return {
      id: entry.id,
      canonical,
      basename: path.basename(canonical),
      mimeType: entry.mime_type || inferMimeType(clean),
      absoluteCandidates: Array.from(new Set(toAbsoluteCandidates(canonical))),
    }
  })

  const matched = candidates.find(
    (entry) =>
      entry &&
      (entry.id === requestedPath ||
        entry.canonical === requestedPath ||
        entry.basename === requestedPath),
  )
  if (!matched) return null
  const absolute = matched.absoluteCandidates.find((candidate) => fs.existsSync(candidate))
  if (!absolute) return null
  return { filePath: absolute, mimeType: matched.mimeType }
}
