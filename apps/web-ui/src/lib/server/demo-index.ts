import fs from 'fs'
import path from 'path'

export type DemoIndexEntry = {
  slug: string
  analysis_id: string
  title: string
  description?: string
  primary_prompt?: string
  coding_prompt?: string
  mcp_prompt?: string
  prompt_path?: string
  prerequisites?: string[]
  tags?: string[]
  created_at?: string
  demo_type?: string
  stage_tags?: string[]
  evidence_mode?: 'real' | 'hybrid' | 'template'
  log_mode?: 'redacted_full_trace' | 'summary_only' | 'raw_trace'
  source_run_ids?: string[]
  manuscript_figure?: string
  canonical_name?: string
  report_title?: string
  is_template?: boolean
  template_reason?: string
}

export type DemoIndex = {
  demos: DemoIndexEntry[]
}

const INDEX_FILENAME = 'demo_index.json'

const JOB_PREFIXES = ['job_', 'run_', 'builder_', 'pipeline_']

function resolveIndexPath(): string | null {
  const override =
    process.env.BR_DEMO_INDEX_PATH ||
    process.env.DEMO_INDEX_PATH ||
    process.env.NEXT_PUBLIC_DEMO_INDEX_PATH

  const candidates = [
    override ? path.resolve(override) : null,
    path.resolve(process.cwd(), 'configs', 'demo', INDEX_FILENAME),
    path.resolve(process.cwd(), '..', 'configs', 'demo', INDEX_FILENAME),
    path.resolve(process.cwd(), '..', '..', 'configs', 'demo', INDEX_FILENAME),
    path.resolve(process.cwd(), '..', '..', '..', 'configs', 'demo', INDEX_FILENAME),
  ].filter(Boolean) as string[]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }

  return override ? path.resolve(override) : null
}

function isLikelyUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  )
}

function isJobIdentifier(value: string): boolean {
  const lower = value.toLowerCase()
  return JOB_PREFIXES.some((prefix) => lower.startsWith(prefix)) || isLikelyUuid(value)
}

function safeEntry(raw: unknown): DemoIndexEntry | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const entry = raw as Record<string, unknown>
  const slug = typeof entry.slug === 'string' ? entry.slug.trim() : ''
  const analysisId =
    typeof entry.analysis_id === 'string' ? entry.analysis_id.trim() : ''
  const title = typeof entry.title === 'string' ? entry.title.trim() : ''
  if (!slug || !analysisId || !title) return null
  const description = typeof entry.description === 'string' ? entry.description.trim() : undefined
  const primaryPrompt =
    typeof entry.primary_prompt === 'string' ? entry.primary_prompt.trim() : undefined
  const codingPrompt =
    typeof entry.coding_prompt === 'string' ? entry.coding_prompt.trim() : undefined
  const mcpPrompt =
    typeof entry.mcp_prompt === 'string' ? entry.mcp_prompt.trim() : undefined
  const promptPath =
    typeof entry.prompt_path === 'string' ? entry.prompt_path.trim() : undefined
  const prerequisites =
    Array.isArray(entry.prerequisites) && entry.prerequisites.length > 0
      ? entry.prerequisites
          .filter((item) => typeof item === 'string')
          .map((item) => item.trim())
          .filter(Boolean)
      : undefined
  const tags =
    Array.isArray(entry.tags)
      ? entry.tags.filter((tag) => typeof tag === 'string').map((tag) => tag.trim())
      : undefined
  const stageTags =
    Array.isArray(entry.stage_tags)
      ? entry.stage_tags
          .filter((tag) => typeof tag === 'string')
          .map((tag) => String(tag).trim())
      : undefined
  const sourceRunIds =
    Array.isArray(entry.source_run_ids)
      ? entry.source_run_ids
          .filter((runId) => typeof runId === 'string')
          .map((runId) => String(runId).trim())
      : undefined
  const demoType = typeof entry.demo_type === 'string' ? entry.demo_type.trim() : undefined
  const evidenceMode =
    entry.evidence_mode === 'real' ||
    entry.evidence_mode === 'hybrid' ||
    entry.evidence_mode === 'template'
      ? entry.evidence_mode
      : undefined
  const logMode =
    entry.log_mode === 'redacted_full_trace' ||
    entry.log_mode === 'summary_only' ||
    entry.log_mode === 'raw_trace'
      ? entry.log_mode
      : undefined
  const manuscriptFigure =
    typeof entry.manuscript_figure === 'string' ? entry.manuscript_figure.trim() : undefined
  const canonicalName =
    typeof entry.canonical_name === 'string' ? entry.canonical_name.trim() : undefined
  const reportTitle =
    typeof entry.report_title === 'string' ? entry.report_title.trim() : undefined
  const isTemplate = typeof entry.is_template === 'boolean' ? entry.is_template : undefined
  const templateReason =
    typeof entry.template_reason === 'string' ? entry.template_reason.trim() : undefined
  const createdAt = typeof entry.created_at === 'string' ? entry.created_at.trim() : undefined
  return {
    slug,
    analysis_id: analysisId,
    title,
    description,
    primary_prompt: primaryPrompt,
    coding_prompt: codingPrompt,
    mcp_prompt: mcpPrompt,
    prompt_path: promptPath,
    prerequisites,
    tags,
    created_at: createdAt,
    demo_type: demoType,
    stage_tags: stageTags,
    evidence_mode: evidenceMode,
    log_mode: logMode,
    source_run_ids: sourceRunIds,
    manuscript_figure: manuscriptFigure,
    canonical_name: canonicalName,
    report_title: reportTitle,
    is_template: isTemplate,
    template_reason: templateReason,
  }
}

export function loadDemoIndex(): DemoIndex {
  const indexPath = resolveIndexPath()
  try {
    if (!indexPath || !fs.existsSync(indexPath)) return { demos: [] }
    const raw = fs.readFileSync(indexPath, 'utf-8')
    const parsed = raw ? JSON.parse(raw) : {}
    const demosRaw = Array.isArray(parsed?.demos) ? parsed.demos : []
    const demos = demosRaw.map(safeEntry).filter(Boolean) as DemoIndexEntry[]
    return { demos }
  } catch {
    return { demos: [] }
  }
}

export function resolveDemoEntry(value: string): DemoIndexEntry | null {
  const key = value.trim().toLowerCase()
  if (!key) return null
  const { demos } = loadDemoIndex()
  return (
    demos.find((demo) => demo.slug.toLowerCase() === key) ??
    demos.find((demo) => demo.analysis_id.toLowerCase() === key) ??
    null
  )
}

export function resolveDemoAnalysisId(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const entry = resolveDemoEntry(trimmed)
  if (entry) return entry.analysis_id
  return isJobIdentifier(trimmed) ? trimmed : null
}
