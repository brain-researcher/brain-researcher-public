import fs from 'fs'
import path from 'path'

import YAML from 'yaml'

import type { AnalysisDetail } from '@/types/analysis'

import {
  bundleArtifacts,
  type DemoRunBundle,
  type DemoRunBundleArtifact,
  type DemoRunBundleReplayStep,
} from '@/lib/server/demo-bundles'
import type { DemoIndexEntry } from '@/lib/server/demo-index'

type ReplayStepStatus = 'completed' | 'running' | 'failed' | 'pending'
type CapabilityStage = 'R0' | 'R1' | 'R2' | 'R3' | 'R4' | 'R5'

export type ReplayStep = {
  step_id: string
  stage: string
  title: string
  narrative_title: string
  narrative_order: number
  status: ReplayStepStatus
  tool: string | null
  tool_calls: string[]
  prompt_text: string
  response_text: string
  artifact_refs: string[]
  started_at: number | null
  finished_at: number | null
  duration_ms: number | null
}

export type ReplayPromptPack = {
  primary_prompt: string
  followup_prompts: string[]
  coding_agent_prompts: string[]
  mcp_prompts: string[]
  source_path: string | null
}

export type ReplayReferenceOutput = {
  summary: string
  summary_kind: 'answer' | 'query' | 'synthetic'
  highlights: string[]
  documents: Array<{
    id?: string
    path: string
    mime_type: string
    content: string
    truncated: boolean
  }>
  generated_at?: string | null
  dataset_version?: string | null
}

export type ReplayReproduceSnippet = {
  snippet_id: string
  title: string
  language: 'text' | 'bash'
  lines: string[]
}

export type ReplayReproduceSpec = {
  requirements: string[]
  commands: string[]
  snippets: ReplayReproduceSnippet[]
  source_path: string | null
}

export type ReplayPresentation = {
  mode: 'live' | 'curated'
  disclaimer: string
  overview: string
}

const STAGE_PATTERN = /^R([0-5])$/i

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function safeString(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

function dedupeStrings(values: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const clean = value.trim()
    if (!clean || seen.has(clean)) continue
    seen.add(clean)
    out.push(clean)
  }
  return out
}

function toEpochSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e11 ? Math.floor(value / 1000) : Math.floor(value)
  }
  if (typeof value !== 'string' || !value.trim()) return null
  const ms = Date.parse(value)
  if (!Number.isFinite(ms)) return null
  return Math.floor(ms / 1000)
}

function normalizeStatus(value: unknown): ReplayStepStatus {
  const normalized = safeString(value).toLowerCase()
  if (
    normalized === 'success' ||
    normalized === 'succeeded' ||
    normalized === 'done' ||
    normalized === 'completed'
  ) {
    return 'completed'
  }
  if (normalized === 'running' || normalized === 'in_progress' || normalized === 'processing') {
    return 'running'
  }
  if (normalized === 'failed' || normalized === 'error' || normalized === 'timeout') {
    return 'failed'
  }
  return 'pending'
}

function normalizeStage(value: string, index: number): CapabilityStage {
  const raw = value.trim().toUpperCase()
  if (STAGE_PATTERN.test(raw)) return raw as CapabilityStage
  if (index <= 0) return 'R0'
  if (index === 1) return 'R1'
  if (index === 2) return 'R2'
  if (index === 3) return 'R3'
  if (index === 4) return 'R4'
  return 'R5'
}

function stageTitle(stage: string): string {
  const normalized = stage.trim().toUpperCase()
  if (normalized === 'R0') return 'Frame Query'
  if (normalized === 'R1') return 'Evidence Retrieval'
  if (normalized === 'R2') return 'Conflict Mapping'
  if (normalized === 'R3') return 'Design Recommendation'
  if (normalized === 'R4') return 'Execution'
  if (normalized === 'R5') return 'RunCard / Export'
  return stage
}

function narrativeTitleForStage(capabilityStage: CapabilityStage): string {
  return `${capabilityStage} ${stageTitle(capabilityStage)}`
}

function narrativeOrderForStage(capabilityStage: CapabilityStage): number {
  return Number.parseInt(capabilityStage.slice(1), 10)
}

function resolveRepoPath(rawPath: string): string | null {
  const clean = rawPath.trim()
  if (!clean) return null
  const candidates: string[] = path.isAbsolute(clean)
    ? [path.resolve(clean)]
    : [
        path.resolve(process.cwd(), clean),
        path.resolve(process.cwd(), '..', clean),
        path.resolve(process.cwd(), '..', '..', clean),
        path.resolve(process.cwd(), '..', '..', '..', clean),
      ]
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  return null
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

function isTextualMimeType(mimeType: string): boolean {
  return mimeType.startsWith('text/') || mimeType.includes('json') || mimeType.includes('yaml')
}

function readPreview(filePath: string, maxChars = 1200): string {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    return raw.slice(0, maxChars).trim()
  } catch {
    return ''
  }
}

function readTextDocument(
  filePath: string,
  maxChars = 20000,
): { content: string; truncated: boolean } {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8').trim()
    if (raw.length <= maxChars) return { content: raw, truncated: false }
    return {
      content: `${raw.slice(0, maxChars).trimEnd()}\n\n… [truncated]`,
      truncated: true,
    }
  } catch {
    return { content: '', truncated: false }
  }
}

function artifactById(bundle: DemoRunBundle | null, artifactId: string): DemoRunBundleArtifact | null {
  if (!bundle || !artifactId) return null
  const artifacts = bundleArtifacts(bundle)
  return artifacts.find((item) => item.id === artifactId) || null
}

function artifactPathById(bundle: DemoRunBundle | null, artifactId: string): string | null {
  return artifactById(bundle, artifactId)?.path || null
}

function extractFencedBlocks(text: string): string[] {
  const blocks: string[] = []
  const regex = /```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g
  let match = regex.exec(text)
  while (match) {
    const block = match[1]?.trim()
    if (block) blocks.push(block)
    match = regex.exec(text)
  }
  return blocks
}

function extractSection(text: string, heading: string): string | null {
  const pattern = new RegExp(`##\\s*${heading}[\\s\\S]*?(?=\\n##\\s+|$)`, 'i')
  const match = text.match(pattern)
  return match?.[0]?.trim() || null
}

function normalizePromptText(value: string): string {
  const trimmed = value.trim()
  const noQuotes =
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
      ? trimmed.slice(1, -1).trim()
      : trimmed
  return noQuotes
}

function extractUserQueryFromMarkdown(raw: string): string {
  const step0Section =
    extractSection(raw, 'Step\\s*0[^\\n]*User Query[^\\n]*') ||
    extractSection(raw, 'User Query[^\\n]*')
  const step0Blocks = step0Section ? extractFencedBlocks(step0Section) : []
  if (step0Blocks.length > 0) return normalizePromptText(step0Blocks[0])

  const taskStatementSection = extractSection(raw, 'Task Statement[^\\n]*')
  if (taskStatementSection) {
    const blocks = extractFencedBlocks(taskStatementSection)
    if (blocks.length > 0) return normalizePromptText(blocks[0])
  }

  const jsonLikeMatch = raw.match(
    /"(?:user_query|research_question|claim_statement|claim_text)"\s*:\s*"([^"]+)"/i,
  )
  if (jsonLikeMatch?.[1]) return normalizePromptText(jsonLikeMatch[1])

  return ''
}

function extractPrimaryPromptFromMarkdown(filePath: string): string {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    const step0Section = extractSection(raw, 'Step\\s*0[^\\n]*')
    const step0Blocks = step0Section ? extractFencedBlocks(step0Section) : []
    const primaryBase = step0Blocks.length
      ? normalizePromptText(step0Blocks[0])
      : normalizePromptText(extractFencedBlocks(raw)[0] || '')
    const userQuery = extractUserQueryFromMarkdown(raw)
    if (userQuery && primaryBase && !primaryBase.toLowerCase().includes(userQuery.toLowerCase())) {
      return `User Query: ${userQuery}\n\nTask Prompt:\n${primaryBase}`
    }
    return userQuery || primaryBase
  } catch {
    return ''
  }
}

function pickTextField(obj: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = obj[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  for (const key of keys) {
    const nested = safeRecord(obj[key])
    if (!nested) continue
    for (const nestedValue of Object.values(nested)) {
      if (typeof nestedValue === 'string' && nestedValue.trim()) return nestedValue.trim()
    }
  }
  return ''
}

function extractToolCalls(step: Record<string, unknown>): string[] {
  const direct = step.tool_calls
  const values = Array.isArray(direct) ? direct : []
  const calls: string[] = []
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      calls.push(value.trim())
      continue
    }
    const obj = safeRecord(value)
    if (!obj) continue
    const name =
      safeString(obj.name) ||
      safeString(obj.tool_name) ||
      safeString(obj.tool) ||
      safeString(obj.id)
    if (name) calls.push(name)
  }
  return dedupeStrings(calls)
}

function extractArtifactRefs(step: Record<string, unknown>): string[] {
  const refs: string[] = []
  const addRef = (value: unknown) => {
    if (typeof value === 'string' && value.trim()) {
      refs.push(value.trim())
      return
    }
    const obj = safeRecord(value)
    if (!obj) return
    const candidate =
      safeString(obj.id) || safeString(obj.path) || safeString(obj.name) || safeString(obj.url)
    if (candidate) refs.push(candidate)
  }

  const artifacts = step.artifacts
  if (Array.isArray(artifacts)) {
    for (const item of artifacts) addRef(item)
  }
  const outputArtifacts = step.outputs
  if (Array.isArray(outputArtifacts)) {
    for (const item of outputArtifacts) addRef(item)
  }
  return dedupeStrings(refs)
}

function replayStepFromBundle(args: {
  step: DemoRunBundleReplayStep
  index: number
  promptPack: ReplayPromptPack
}): ReplayStep {
  const capabilityStage = normalizeStage(args.step.stage || '', args.index)
  const started = typeof args.step.started_at === 'number' ? args.step.started_at : null
  const finished = typeof args.step.finished_at === 'number' ? args.step.finished_at : null
  return {
    step_id: args.step.step_id || `step_${args.index + 1}`,
    stage: capabilityStage,
    title: args.step.title || stageTitle(capabilityStage),
    narrative_title: narrativeTitleForStage(capabilityStage),
    narrative_order: narrativeOrderForStage(capabilityStage),
    status: normalizeStatus(args.step.status),
    tool: args.step.tool || null,
    tool_calls: dedupeStrings(args.step.tool_calls || []),
    prompt_text:
      args.step.prompt_text?.trim() || (args.index === 0 ? args.promptPack.primary_prompt : ''),
    response_text: args.step.response_text?.trim() || '',
    artifact_refs: dedupeStrings(args.step.artifact_ref_ids || []),
    started_at: started,
    finished_at: finished,
    duration_ms:
      typeof args.step.duration_ms === 'number'
        ? args.step.duration_ms
        : started != null && finished != null && finished >= started
          ? (finished - started) * 1000
          : null,
  }
}

function replayStepsFromRuncard(args: {
  analysis: AnalysisDetail
  promptPack: ReplayPromptPack
}): ReplayStep[] {
  const runcard = safeRecord(args.analysis.runcard)
  const execution = safeRecord(runcard?.execution)
  const rawSteps = Array.isArray(execution?.steps) ? execution?.steps : []
  const parsed: ReplayStep[] = []

  for (let idx = 0; idx < rawSteps.length; idx += 1) {
    const step = safeRecord(rawSteps[idx])
    if (!step) continue
    const capabilityStage = normalizeStage(safeString(step.stage) || safeString(step.phase), idx)
    const title =
      safeString(step.name) || safeString(step.title) || safeString(step.tool) || `Step ${idx + 1}`
    const started = toEpochSeconds(step.started_at)
    const finished = toEpochSeconds(step.finished_at)
    parsed.push({
      step_id: safeString(step.id) || `step_${idx + 1}`,
      stage: capabilityStage,
      title,
      narrative_title: narrativeTitleForStage(capabilityStage),
      narrative_order: narrativeOrderForStage(capabilityStage),
      status: normalizeStatus(step.status),
      tool: safeString(step.tool) || null,
      tool_calls: extractToolCalls(step),
      prompt_text:
        pickTextField(step, ['prompt', 'query', 'input', 'instruction', 'message', 'request']) ||
        (idx === 0 ? args.promptPack.primary_prompt : ''),
      response_text: pickTextField(step, ['response', 'output', 'result', 'summary', 'observation']),
      artifact_refs: extractArtifactRefs(step),
      started_at: started,
      finished_at: finished,
      duration_ms:
        started != null && finished != null && finished >= started
          ? (finished - started) * 1000
          : null,
    })
  }

  return parsed
}

export function buildReplaySteps(args: {
  analysis: AnalysisDetail
  demo: DemoIndexEntry
  promptPack: ReplayPromptPack
  bundle: DemoRunBundle | null
  referenceSummary: string
}): ReplayStep[] {
  const fromBundle = Array.isArray(args.bundle?.replay?.steps) ? args.bundle?.replay?.steps : []
  if (fromBundle.length > 0) {
    return fromBundle.map((step, index) =>
      replayStepFromBundle({
        step,
        index,
        promptPack: args.promptPack,
      }),
    )
  }

  const fromRuncard = replayStepsFromRuncard({
    analysis: args.analysis,
    promptPack: args.promptPack,
  })
  if (fromRuncard.length > 0) return fromRuncard

  const stageTags =
    Array.isArray(args.demo.stage_tags) && args.demo.stage_tags.length > 0
      ? args.demo.stage_tags
      : ['R0', 'R2', 'R4']

  return stageTags.map((rawStage, index) => {
    const capabilityStage = normalizeStage(rawStage, index)
    return {
      step_id: `stage_${capabilityStage}_${index + 1}`,
      stage: capabilityStage,
      title: stageTitle(capabilityStage),
      narrative_title: narrativeTitleForStage(capabilityStage),
      narrative_order: narrativeOrderForStage(capabilityStage),
      status: 'completed',
      tool: null,
      tool_calls: [],
      prompt_text: index === 0 ? args.promptPack.primary_prompt : '',
      response_text: '',
      artifact_refs: [],
      started_at: toEpochSeconds(args.analysis.started_at),
      finished_at: toEpochSeconds(args.analysis.finished_at),
      duration_ms: null,
    }
  })
}

function promptSourceFromArtifacts(bundle: DemoRunBundle | null): DemoRunBundleArtifact | null {
  const artifacts = bundleArtifacts(bundle)
  return artifacts.find((item) => item.roles.includes('prompt_source')) || null
}

export function buildPromptPack(args: {
  demo: DemoIndexEntry
  analysis: AnalysisDetail
  bundle: DemoRunBundle | null
}): ReplayPromptPack {
  const bundlePromptPack = args.bundle?.prompt_pack
  const sourceArtifact = promptSourceFromArtifacts(args.bundle)
  const sourceFromBundle = artifactPathById(args.bundle, bundlePromptPack?.source_artifact_id || '')

  const extractedPrompt = sourceArtifact ? extractPrimaryPromptFromMarkdown(sourceArtifact.path) : ''
  const primaryPrompt =
    safeString(args.demo.primary_prompt) ||
    safeString(bundlePromptPack?.primary_prompt) ||
    extractedPrompt ||
    safeString(args.demo.description) ||
    safeString(args.demo.title)

  const followupPrompts = dedupeStrings(bundlePromptPack?.followup_prompts || [])
  const codingAgentPrompts = safeString(args.demo.coding_prompt)
    ? [safeString(args.demo.coding_prompt)]
    : dedupeStrings(bundlePromptPack?.coding_agent_prompts || [])
  const mcpPrompts = safeString(args.demo.mcp_prompt)
    ? [safeString(args.demo.mcp_prompt)]
    : dedupeStrings(bundlePromptPack?.mcp_prompts || [])

  return {
    primary_prompt: primaryPrompt,
    followup_prompts: followupPrompts,
    coding_agent_prompts: codingAgentPrompts,
    mcp_prompts: mcpPrompts,
    source_path: sourceFromBundle || safeString(args.demo.prompt_path) || sourceArtifact?.path || null,
  }
}

function documentIdsFallback(artifacts: DemoRunBundleArtifact[]): string[] {
  const scored = artifacts
    .filter((artifact) => !artifact.roles.includes('prompt_source'))
    .map((artifact) => {
      const lower = artifact.path.toLowerCase()
      const score = artifact.roles.includes('figure')
        ? 0
        : lower.endsWith('.csv')
          ? 1
          : artifact.roles.includes('reference_summary_source')
            ? 2
            : lower.endsWith('.md')
              ? 3
              : 4
      return { artifact, score }
    })
    .sort((a, b) => a.score - b.score || a.artifact.path.localeCompare(b.artifact.path))
  return scored.slice(0, 8).map((entry) => entry.artifact.id)
}

function extractStructuredHighlightsFromArtifact(pathValue: string): string[] {
  const lower = pathValue.toLowerCase()
  if (!(lower.endsWith('.yaml') || lower.endsWith('.yml') || lower.endsWith('.json'))) return []
  const resolved = resolveRepoPath(pathValue)
  if (!resolved) return []

  try {
    const raw = fs.readFileSync(resolved, 'utf-8')
    const parsed = lower.endsWith('.json') ? JSON.parse(raw) : YAML.parse(raw)
    const obj = safeRecord(parsed)
    if (!obj) return []

    const highlights: string[] = []
    const r2 = safeRecord(obj.r2_output)
    const dominant = safeRecord(r2?.dominant_driver_discovered)
    if (dominant) {
      const axis = safeString(dominant.axis)
      const contribution = dominant.contribution
      if (axis) {
        highlights.push(
          contribution != null
            ? `Dominant driver: ${axis} (${String(contribution)})`
            : `Dominant driver: ${axis}`,
        )
      }
    }
    const risk = safeRecord(r2?.default_pipeline_risk)
    const riskStatement = safeString(risk?.risk_statement)
    if (riskStatement) highlights.push(riskStatement)

    const r4 = safeRecord(obj.r4_output)
    const keyResults = Array.isArray(r4?.key_results) ? r4?.key_results : []
    for (const result of keyResults.slice(0, 2)) {
      const item = safeRecord(result)
      const finding = safeString(item?.finding)
      if (finding) highlights.push(finding)
    }

    return dedupeStrings(highlights)
  } catch {
    return []
  }
}

function collectReferenceDocuments(args: {
  bundle: DemoRunBundle | null
  documentIds: string[]
}): ReplayReferenceOutput['documents'] {
  const docs: ReplayReferenceOutput['documents'] = []
  for (const docId of args.documentIds) {
    const artifact = artifactById(args.bundle, docId)
    if (!artifact) continue
    const resolved = resolveRepoPath(artifact.path)
    if (!resolved) continue
    const mimeType = artifact.mime_type || inferMimeType(artifact.path)
    if (isTextualMimeType(mimeType)) {
      const { content, truncated } = readTextDocument(resolved)
      if (!content) continue
      docs.push({
        id: artifact.id,
        path: artifact.path,
        mime_type: mimeType,
        content,
        truncated,
      })
      continue
    }
    if (!mimeType.startsWith('image/')) continue
    docs.push({
      id: artifact.id,
      path: artifact.path,
      mime_type: mimeType,
      content: '',
      truncated: false,
    })
  }
  return docs
}

function inferDatasetVersion(args: {
  analysis: AnalysisDetail
  bundle: DemoRunBundle | null
}): string | null {
  const bundleRecord = safeRecord(args.bundle)
  const bundleDemo = safeRecord(args.bundle?.demo)
  const dataset = safeRecord(args.analysis.dataset)
  const candidates = [
    safeString(bundleRecord?.dataset_version),
    safeString(bundleDemo?.dataset_version),
    safeString(dataset?.dataset_version),
    safeString(dataset?.version),
    safeString(dataset?.release),
    safeString(dataset?.snapshot),
  ]
  for (const candidate of candidates) {
    if (candidate) return candidate
  }
  return null
}

export function buildReferenceOutput(args: {
  analysis: AnalysisDetail
  demo: DemoIndexEntry
  bundle: DemoRunBundle | null
}): ReplayReferenceOutput {
  const artifacts = bundleArtifacts(args.bundle)
  const bundleReference = args.bundle?.reference_output

  const documentIds =
    bundleReference?.document_ids && bundleReference.document_ids.length > 0
      ? bundleReference.document_ids
      : documentIdsFallback(artifacts)

  const documents = collectReferenceDocuments({
    bundle: args.bundle,
    documentIds,
  })

  let highlights = dedupeStrings(bundleReference?.highlights || [])
  if (highlights.length === 0) {
    for (const artifact of artifacts) {
      if (!artifact.roles.includes('evidence') && !artifact.roles.includes('reference_summary_source')) {
        continue
      }
      for (const item of extractStructuredHighlightsFromArtifact(artifact.path)) {
        if (!highlights.includes(item)) highlights.push(item)
        if (highlights.length >= 4) break
      }
      if (highlights.length >= 4) break
    }
  }

  const summary =
    safeString(bundleReference?.summary) ||
    highlights[0] ||
    safeString(args.demo.description) ||
    `Replay for ${args.demo.title} loaded with ${artifacts.length} evidence artifact(s).`

  const summaryKindRaw = safeString(bundleReference?.summary_kind)
  const summaryKind: ReplayReferenceOutput['summary_kind'] =
    summaryKindRaw === 'answer' || summaryKindRaw === 'query' || summaryKindRaw === 'synthetic'
      ? summaryKindRaw
      : highlights.length > 0
        ? 'answer'
        : 'synthetic'

  return {
    summary,
    summary_kind: summaryKind,
    highlights,
    documents,
    generated_at: safeString(bundleReference?.generated_at) || safeString(args.bundle?.generated_at) || null,
    dataset_version: safeString(bundleReference?.dataset_version) || inferDatasetVersion(args),
  }
}

function buildSnippet(args: {
  snippetId: string
  title: string
  language: 'text' | 'bash'
  lines: string[]
}): ReplayReproduceSnippet | null {
  const normalized = dedupeStrings(args.lines.map((line) => line.trim()).filter(Boolean))
  if (normalized.length === 0) return null
  return {
    snippet_id: args.snippetId,
    title: args.title,
    language: args.language,
    lines: normalized,
  }
}

export function buildReproduceSpec(args: {
  demo: DemoIndexEntry
  promptPack: ReplayPromptPack
  bundle: DemoRunBundle | null
}): ReplayReproduceSpec {
  const configuredPrerequisites = Array.isArray(args.demo.prerequisites)
    ? args.demo.prerequisites
    : []
  const requirements: string[] = dedupeStrings([...configuredPrerequisites])
  const commands: string[] = [
    `Open /demos/${args.demo.slug}`,
    `Open /api/demo/bundles/${args.demo.slug}`,
    args.promptPack.primary_prompt,
  ]

  if (args.promptPack.coding_agent_prompts.length > 0) {
    commands.push(args.promptPack.coding_agent_prompts[0])
  }
  if (args.promptPack.mcp_prompts.length > 0) {
    commands.push(args.promptPack.mcp_prompts[0])
  }
  if (Array.isArray(args.bundle?.source_run_ids) && args.bundle?.source_run_ids.length > 0) {
    commands.push(`run_get(run_id=${args.bundle.source_run_ids[0]})`)
    commands.push(`artifact_list(run_id=${args.bundle.source_run_ids[0]})`)
  }

  const finalCommands = dedupeStrings(commands).slice(0, 8)
  const snippets = [
    buildSnippet({
      snippetId: 'prerequisites',
      title: 'Prerequisites',
      language: 'text',
      lines: requirements,
    }),
    buildSnippet({
      snippetId: 'primary_prompt',
      title: 'Primary Prompt',
      language: 'text',
      lines: [args.promptPack.primary_prompt],
    }),
    buildSnippet({
      snippetId: 'coding_agent_prompt',
      title: 'Coding Agent Prompt',
      language: 'text',
      lines: args.promptPack.coding_agent_prompts.slice(0, 1),
    }),
    buildSnippet({
      snippetId: 'mcp_prompt',
      title: 'MCP Prompt',
      language: 'text',
      lines: args.promptPack.mcp_prompts.slice(0, 1),
    }),
    buildSnippet({
      snippetId: 'replay_commands',
      title: 'Replay Commands',
      language: 'bash',
      lines: finalCommands,
    }),
  ].filter(Boolean) as ReplayReproduceSnippet[]

  return {
    requirements,
    commands: finalCommands,
    snippets,
    source_path: args.promptPack.source_path,
  }
}

function demoSourceRunIds(args: {
  demo: DemoIndexEntry
  bundle: DemoRunBundle | null
}): string[] {
  const fromBundle = Array.isArray(args.bundle?.source_run_ids) ? args.bundle.source_run_ids : []
  const fromDemo = Array.isArray(args.demo.source_run_ids) ? args.demo.source_run_ids : []
  return dedupeStrings([...fromBundle, ...fromDemo])
}

function presentationMode(args: {
  demo: DemoIndexEntry
  bundle: DemoRunBundle | null
}): 'live' | 'curated' {
  if (args.demo.demo_type === 'manuscript_case_report') return 'curated'
  if (args.bundle?.replay?.source === 'bundle_steps' && demoSourceRunIds(args).length === 0) {
    return 'curated'
  }
  return args.demo.evidence_mode === 'real' ? 'live' : 'curated'
}

export function buildPresentation(args: {
  demo: DemoIndexEntry
  replaySteps: ReplayStep[]
  bundle: DemoRunBundle | null
}): ReplayPresentation {
  const artifacts = bundleArtifacts(args.bundle)
  const artifactCount =
    typeof args.bundle?.artifact_count === 'number' ? args.bundle.artifact_count : artifacts.length
  const overviewBase = safeString(args.demo.description) || args.demo.title
  const overview = `${overviewBase} Replay includes ${args.replaySteps.length} step(s) and ${artifactCount} evidence artifact(s).`
  const mode = presentationMode({
    demo: args.demo,
    bundle: args.bundle,
  })
  const disclaimer =
    mode === 'live'
      ? 'Live evidence replay: outputs should still be treated as non-deterministic across reruns.'
      : 'Curated replay mode: evidence is shown from recorded artifacts; treat summaries as reference and verify provenance links.'
  return {
    mode,
    disclaimer,
    overview,
  }
}

export function buildTransparentEvidenceNotes(args: {
  demo: DemoIndexEntry
  bundle: DemoRunBundle | null
  replaySource: 'runcard' | 'bundle_steps' | 'synthetic'
}): string[] {
  const sourceRunIds = demoSourceRunIds({
    demo: args.demo,
    bundle: args.bundle,
  })

  const notes = [
    'Reference output shown here is a replay artifact, not a guaranteed identical rerun.',
    'Your rerun may differ slightly due to model stochasticity and runtime environment.',
    `Evidence provenance: mode=${args.demo.evidence_mode || 'hybrid'}; log_mode=${args.demo.log_mode || 'redacted_full_trace'}; replay_source=${args.replaySource}.`,
    sourceRunIds.length > 0
      ? `Declared source run IDs: ${sourceRunIds.join(', ')}.`
      : 'Declared source run IDs: none.',
    args.demo.is_template || args.demo.evidence_mode === 'template'
      ? `Template disclosure: ${safeString(args.demo.template_reason) || 'This demo includes template-backed sections.'}`
      : 'Template disclosure: demo is marked non-template in index metadata.',
  ]

  if (!args.bundle) {
    notes.push('Bundle disclosure: curated run_bundle.json was not found; replay fields may be synthesized.')
  } else {
    const fallbackLevel = safeString(args.bundle.fallback?.level)
    const reasons = dedupeStrings(args.bundle.fallback?.reasons || [])
    if (fallbackLevel && fallbackLevel !== 'none') {
      notes.push(`Fallback disclosure: level=${fallbackLevel}${reasons.length ? `; reasons=${reasons.join(', ')}` : ''}.`)
    }
    if (args.bundle.replay?.source) {
      notes.push(`Bundle replay source: ${args.bundle.replay.source}.`)
    }
  }

  return dedupeStrings(notes)
}

export function buildPromptSourceFiles(args: {
  demo: DemoIndexEntry
  bundle: DemoRunBundle | null
}): string[] {
  const fromBundle = bundleArtifacts(args.bundle)
    .filter((artifact) => artifact.roles.includes('prompt_source'))
    .map((artifact) => artifact.path)
  const fallback = safeString(args.demo.prompt_path)
  return dedupeStrings([...fromBundle, ...(fallback ? [fallback] : [])])
}

export function artifactPreview(args: {
  slug: string
  artifactPath: string
  resolver: (slug: string, artifactPath: string) => { filePath: string; mimeType: string } | null
}): { mime_type: string; preview: string } | null {
  const resolved = args.resolver(args.slug, args.artifactPath)
  if (!resolved) return null
  const isTextual =
    resolved.mimeType.startsWith('text/') ||
    resolved.mimeType.includes('json') ||
    resolved.mimeType.includes('yaml')
  if (!isTextual) return { mime_type: resolved.mimeType, preview: '' }
  return {
    mime_type: resolved.mimeType,
    preview: readPreview(resolved.filePath, 1200),
  }
}

export function debugString(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
