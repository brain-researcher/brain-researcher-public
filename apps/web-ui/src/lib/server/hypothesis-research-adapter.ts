import { resolveAgentBaseUrl } from '@/lib/server/downstream'
import {
  buildReadableLabel,
  displayUrlFromUrl,
  inferEvidenceQuality,
  inferSourceType,
  isGroundingRedirectCandidate,
  isUnresolvedGroundingRedirect,
  normalizeEvidenceUrl,
  sourceHostFromUrl,
} from '@/lib/server/evidence-normalizer'
import type { HypothesisEvidenceItem } from '@/types/hypothesis'

type JsonRecord = Record<string, unknown>

type ToolRunResponse = {
  resultStatus: string | null
  toolError: string | null
  payload: JsonRecord | null
}

type EvidenceCandidateWithTitle = {
  item: HypothesisEvidenceItem
  validationTitle: string | null
}

type LinkValidationResult = {
  finalUrl: string | null
  status: 'missing_url' | 'skipped' | 'confirmed' | 'corrected' | 'dropped'
  validatedBy?: 'arxiv' | 'openalex' | 'crossref' | 'doi' | null
  matchedTitle?: string | null
  reason?: string | null
  matchScore?: number | null
}

type DegenerateEvidenceMode = 'soft_keep_top1' | 'none'

export type DeepResearchDegenerateEvidenceDiagnostics = {
  degenerate: boolean
  reason: string | null
  mode: DegenerateEvidenceMode
  dedupeStats: {
    before: number
    after: number
    collapsedGroups: number
  }
}

export type DeepResearchDiscardReasonCode =
  | 'redirect_unresolved'
  | 'duplicate_cluster'
  | 'duplicate_similarity'
  | 'synthetic_summary'
  | 'top_n_trim'
  | 'missing_url_or_label'
  | 'unknown'

export type DeepResearchReportSource = {
  id: string
  label: string
  display_title: string | null
  summary: string | null
  url: string | null
  raw_url: string | null
  final_url: string | null
  source_host: string | null
  kind: HypothesisEvidenceItem['kind']
  source_type: HypothesisEvidenceItem['source_type'] | null
  quality_tier: HypothesisEvidenceItem['quality_tier'] | null
  traceability_score: number | null
}

export type DeepResearchDiscardReasonMeta = {
  attempted: boolean
  resolver: 'none' | 'query_param' | 'head' | 'get'
  http_status: number | null
  error: string | null
  skipped_by_budget: boolean
}

export type DeepResearchDiscardedSource = DeepResearchReportSource & {
  reason_code: DeepResearchDiscardReasonCode
  reason_detail: string | null
  reason_meta?: DeepResearchDiscardReasonMeta | null
}

export type DeepResearchSearchTrail = {
  stage: 'start' | 'poll' | 'sync_fallback'
  tool: string
  status: string
  detail: string | null
  ts?: string | null
}

export type DeepResearchSynthesisSource = 'upstream' | 'llm_fallback' | 'fallback_rule'

export type DeepResearchDiscardAggregate = {
  reason_code: DeepResearchDiscardReasonCode
  count: number
  detail: string
  stats?: Record<string, number>
}

export type DeepResearchFallbackPath =
  | 'none'
  | 'sync_after_terminal_failure'
  | 'sync_after_quality_gate'
  | 'sync_after_missing_ids'
  | 'sync_after_recoverable_poll_error'

export type DeepResearchQualityGate = {
  min_citable_sources: number
  min_primary_sources: number
  citable_count: number
  primary_count: number
  pass: boolean
  low_confidence: boolean
  reason: string | null
}

export type DeepResearchClaimReview = {
  source_run_id: string
  source_artifact: 'claim_report.json'
  summary: string | null
  overall_verdict: string | null
  caveats: string[]
  unresolved_questions: string[]
  claim_count: number
  rendered_markdown: string
}

export type DeepResearchReportPayload = {
  query: string
  status: string
  source_run_id: string | null
  interaction_id: string | null
  idempotency_key: string | null
  summary: string
  synthesis_full_text: string
  raw_summary: string
  raw_synthesis_full_text: string
  claim_review: DeepResearchClaimReview | null
  synthesis_generated_by: DeepResearchSynthesisSource
  synthesis_source_count: number
  search_trails: DeepResearchSearchTrail[]
  historical_trails_available: boolean
  source_inventory: DeepResearchReportSource[]
  discarded_sources: DeepResearchDiscardedSource[]
  discarded_aggregates: DeepResearchDiscardAggregate[]
  quality_gate: DeepResearchQualityGate
  fallback_path: DeepResearchFallbackPath
  search_stats: {
    scanned_count: number
    qualifying_count: number
    unique_after_dedupe_count: number
    final_citable_count: number
    discarded_count: number
  }
  generated_at: string
}

const DEFAULT_TOOL_TIMEOUT_MS = 45_000
const DEFAULT_POLL_INTERVAL_MS = 2_500
const DEFAULT_MAX_POLLS = 0
const DEFAULT_START_GRACE_POLLS = 2
const DEFAULT_BACKGROUND_CAP_SEC = 21_600
const DEFAULT_TRANSIENT_TOOL_RETRIES = 2
const DEFAULT_TRANSIENT_RETRY_BASE_MS = 500
const DEFAULT_TRANSIENT_RETRY_MAX_MS = 4_000
const DEFAULT_EVIDENCE_URL_RESOLVE_TIMEOUT_MS = 1_800
const DEFAULT_EVIDENCE_URL_RESOLVE_MAX_DOCS = 4
const DEFAULT_IDENTIFIER_VALIDATION_TIMEOUT_MS = 2_000
const DEFAULT_IDENTIFIER_VALIDATION_MAX_DOCS = 6
const DEFAULT_IDENTIFIER_VALIDATION_CONCURRENCY = 3
const DEFAULT_SYNTHESIS_SUMMARY_FALLBACK =
  'Deep research completed. Evidence synthesized from web and file-search sources.'
const DEFAULT_SYNTHESIS_MIN_WORDS = 40
const DEFAULT_REDIRECT_AGGREGATE_THRESHOLD = 3
const DEFAULT_MIN_CITABLE_SOURCES = 2
const DEFAULT_MIN_PRIMARY_SOURCES = 1

const TERMINAL_DEEP_RESEARCH_STATES = new Set([
  'ok',
  'partial',
  'cached',
  'complete',
  'completed',
  'done',
  'finished',
  'ready',
  'succeeded',
  'success',
])

const TERMINAL_DEEP_RESEARCH_FAILURE_STATES = new Set([
  'failed',
  'error',
  'cancelled',
  'canceled',
  'expired',
])

const GOOGLE_DEEP_RESEARCH_START_TOOL = 'google_deep_research_start'
const GOOGLE_DEEP_RESEARCH_POLL_TOOL = 'run_get'
const GOOGLE_DEEP_RESEARCH_COMPAT_GET_TOOL = 'google_deep_research_get'
const GOOGLE_DEEP_RESEARCH_SYNC_TOOL = 'google_deep_research'

const NO_SEED_ENTITIES_PATTERN = /no seed entities found/i
const URL_PATTERN = /^https?:\/\//i
const OPAQUE_TOKEN_PATTERN = /^[A-Za-z0-9+/_=-]{32,}$/
const DOI_PATTERN = /\b10\.\d{4,9}\/[-._;()/:a-z0-9]+\b/i
const ARXIV_PATTERN = /\b(?:arxiv\.org\/(?:abs|pdf|html)\/)?(\d{4}\.\d{4,5})(?:v\d+)?\b/i
const ARXIV_DOI_PATTERN = /\b10\.48550\/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?\b/i
const ARXIV_TITLE_PREFIX_PATTERN = /^\[\d{4}\.\d{4,5}(?:v\d+)?\]\s*/i
const NON_ALNUM_PATTERN = /[^a-z0-9]+/g
const TITLE_MATCH_THRESHOLD = 0.86
const TITLE_STOPWORDS = new Set(['a', 'an', 'and', 'for', 'from', 'in', 'of', 'on', 'the', 'to', 'via', 'with'])
const GENERIC_SOURCE_TITLES = new Set([
  'abstract',
  'access denied',
  'access denied.',
  'article',
  'attention required!',
  'bad gateway',
  'biorxiv',
  'content',
  'download',
  'error',
  'forbidden',
  'full text',
  'fulltext',
  'internal server error',
  'journal',
  'just a moment',
  'just a moment...',
  'landing page',
  'manuscript',
  'not found',
  'page not found',
  'paper',
  'pdf',
  'preprint',
  'researchgate',
  'sciencedaily',
  'service unavailable',
  'source',
  'status page',
  'supplement',
  'supplementary',
  'view article',
])
const VENUE_ONLY_TITLES = new Set([
  'arxiv',
  'biorxiv',
  'cell',
  'elsevier',
  'frontiers',
  'mdpi',
  'medrxiv',
  'nature',
  'plos',
  'pnas',
  'research square',
  'science',
  'springer',
  'the lancet',
  'wiley',
])

export const DEEP_RESEARCH_ERROR_CODES = {
  EMPTY_QUERY: 'deep_research_empty_query',
  TOOL_NOT_FOUND: 'deep_research_tool_not_found',
  TERMINAL_FAILURE_STATE: 'deep_research_terminal_failure_state',
  MAX_POLLS_EXCEEDED: 'deep_research_max_polls_exceeded',
  BACKGROUND_CAP_EXCEEDED: 'deep_research_background_cap_exceeded',
  MISSING_INTERACTION_ID: 'deep_research_missing_interaction_id',
  TRANSIENT_TOOL_FAILURE: 'deep_research_transient_tool_failure',
  REQUEST_FAILED: 'deep_research_request_failed',
} as const

export type DeepResearchErrorCode =
  (typeof DEEP_RESEARCH_ERROR_CODES)[keyof typeof DEEP_RESEARCH_ERROR_CODES]

type DeepResearchRuntimeError = Error & {
  code: DeepResearchErrorCode
  retryable?: boolean
  cause?: unknown
}

type AgentToolErrorCode = 'http_error' | 'result_error' | 'timeout' | 'network_error'

type AgentToolError = Error & {
  code: AgentToolErrorCode
  tool: string
  status: number | null
  detail: string | null
  cause?: unknown
}

type DeepResearchRetryConfig = {
  transientRetries: number
  retryBaseMs: number
  retryMaxMs: number
}

function isDeepResearchErrorCodeValue(value: unknown): value is DeepResearchErrorCode {
  return typeof value === 'string' && Object.values(DEEP_RESEARCH_ERROR_CODES).includes(value as DeepResearchErrorCode)
}

export function getDeepResearchErrorCode(error: unknown): DeepResearchErrorCode | null {
  if (!error || typeof error !== 'object') return null
  const code = (error as { code?: unknown }).code
  return isDeepResearchErrorCodeValue(code) ? code : null
}

function createDeepResearchError(args: {
  code: DeepResearchErrorCode
  message: string
  retryable?: boolean
  cause?: unknown
}): DeepResearchRuntimeError {
  const error = new Error(args.message) as DeepResearchRuntimeError
  error.name = 'DeepResearchError'
  error.code = args.code
  if (typeof args.retryable === 'boolean') {
    error.retryable = args.retryable
  }
  if (args.cause !== undefined) {
    error.cause = args.cause
  }
  return error
}

function isAgentToolError(error: unknown): error is AgentToolError {
  if (!error || typeof error !== 'object') return false
  const code = (error as { code?: unknown }).code
  return (
    code === 'http_error' ||
    code === 'result_error' ||
    code === 'timeout' ||
    code === 'network_error'
  )
}

function createAgentToolError(args: {
  code: AgentToolErrorCode
  tool: string
  message: string
  status?: number | null
  detail?: string | null
  cause?: unknown
}): AgentToolError {
  const error = new Error(args.message) as AgentToolError
  error.name = 'AgentToolError'
  error.code = args.code
  error.tool = args.tool
  error.status = args.status ?? null
  error.detail = args.detail ?? null
  if (args.cause !== undefined) {
    error.cause = args.cause
  }
  return error
}

function resolveKgMultihopToolTimeoutMs(): number | null {
  const raw = Number(process.env.HYPOTHESIS_KG_MULTIHOP_TOOL_TIMEOUT_MS ?? 0)
  if (!Number.isFinite(raw)) return null
  const normalized = Math.trunc(raw)
  return normalized > 0 ? normalized : null
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as JsonRecord
}

function asString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized.length ? normalized : null
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function normalizeNonNegativeInt(value: unknown, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  const normalized = Math.trunc(value)
  return normalized < 0 ? fallback : normalized
}

function normalizePositiveInt(value: unknown, fallback: number): number {
  const normalized = normalizeNonNegativeInt(value, fallback)
  return normalized > 0 ? normalized : fallback
}

function extractErrorMessage(error: unknown): string {
  if (isAgentToolError(error)) {
    return error.detail || error.message
  }
  if (error instanceof Error) return error.message
  return String(error)
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => asString(item))
    .filter((item): item is string => Boolean(item))
}

function asRecordArray(value: unknown): JsonRecord[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => asRecord(item))
    .filter((item): item is JsonRecord => Boolean(item))
}

function joinMarkdownSection(title: string, items: string[]): string {
  if (!items.length) return ''
  return [`### ${title}`, items.map((item) => `- ${item}`).join('\n')].join('\n\n')
}

function buildClaimReviewSummary(review: DeepResearchClaimReview): string {
  if (review.summary) return review.summary
  if (review.overall_verdict) {
    return `Calibrated claim review loaded from claim_report.json. Overall verdict: ${review.overall_verdict}.`
  }
  return 'Calibrated claim review loaded from claim_report.json.'
}

function buildClaimReviewMarkdown(review: DeepResearchClaimReview): string {
  const sections = [
    '## Calibrated Claim Review',
    buildClaimReviewSummary(review),
  ]

  if (review.overall_verdict) {
    sections.push(`Overall verdict: \`${review.overall_verdict}\``)
  }

  const caveatSection = joinMarkdownSection('Caveats', review.caveats)
  if (caveatSection) sections.push(caveatSection)

  const unresolvedSection = joinMarkdownSection(
    'Unresolved Questions',
    review.unresolved_questions,
  )
  if (unresolvedSection) sections.push(unresolvedSection)

  sections.push(
    `Source: calibrated \`claim_report.json\` from run \`${review.source_run_id}\`.`,
  )

  return sections.filter(Boolean).join('\n\n').trim()
}

function buildWithheldClaimReviewSummary(sourceRunId: string | null): string {
  if (sourceRunId) {
    return `No calibrated claim_report.json was available for run ${sourceRunId}; final verdict withheld.`
  }
  return 'No calibrated claim_report.json was available for this deep research report; final verdict withheld.'
}

function buildWithheldClaimReviewMarkdown(sourceRunId: string | null): string {
  const sections = [
    '## Calibrated Claim Review',
    buildWithheldClaimReviewSummary(sourceRunId),
    'Verdict and caveats are withheld instead of being inferred from raw claim synthesis.',
  ]
  return sections.join('\n\n')
}

function normalizeClaimReviewPayload(
  payload: JsonRecord | null,
  sourceRunId: string | null,
): DeepResearchClaimReview | null {
  if (!payload || !sourceRunId) return null

  const summary = asString(payload.summary)
  const overallVerdict = asString(payload.overall_verdict ?? payload.overallVerdict)
  const caveats = asStringArray(payload.caveats)
  const unresolvedQuestions = asStringArray(
    payload.unresolved_questions ?? payload.unresolvedQuestions,
  )
  const claimCount = asRecordArray(payload.claims).length

  if (!summary && !overallVerdict && !caveats.length && !unresolvedQuestions.length && claimCount === 0) {
    return null
  }

  const review: DeepResearchClaimReview = {
    source_run_id: sourceRunId,
    source_artifact: 'claim_report.json',
    summary,
    overall_verdict: overallVerdict,
    caveats,
    unresolved_questions: unresolvedQuestions,
    claim_count: claimCount,
    rendered_markdown: '',
  }
  review.rendered_markdown = buildClaimReviewMarkdown(review)
  return review
}

function isHttpUrl(value: unknown): value is string {
  const normalized = asString(value)
  if (!normalized) return false
  return URL_PATTERN.test(normalized)
}

function canonicalizeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    parsed.hash = ''
    return parsed.toString()
  } catch {
    return null
  }
}

function cleanSourceTitle(value: unknown): string | null {
  const initial = stripMarkup(asString(value))
  if (!initial) return null
  let text = initial
    .replace(/^[|:\-\s]+/, '')
    .replace(/[|:\-\s]+$/, '')
    .replace(/^\|\s*/, '')
    .replace(/\s+\|\s+.*$/, '')
    .replace(/\s+-\s+.*$/, '')
    .trim()
  if (!text) return null
  const lower = text.toLowerCase()
  if (
    GENERIC_SOURCE_TITLES.has(lower) ||
    VENUE_ONLY_TITLES.has(lower) ||
    /^deep research source\b/.test(lower) ||
    /^source\s+\d+$/.test(lower)
  ) {
    return null
  }
  if (
    lower.startsWith('http://') ||
    lower.startsWith('https://') ||
    lower.startsWith('doi:') ||
    lower.startsWith('pmid:') ||
    lower.startsWith('arxiv:')
  ) {
    return null
  }
  if (DOI_PATTERN.test(lower)) return null
  if (
    ['404', '403', 'access denied', 'not found', 'status page', 'attention required', 'just a moment', 'internal server error', 'service unavailable', 'bad gateway'].some(
      (marker) => lower.includes(marker),
    )
  ) {
    return null
  }
  if (/^[a-z0-9._/\-]+$/.test(lower) && (/\d/.test(lower) || lower.includes('.') || lower.includes('/'))) {
    return null
  }
  return text
}

function normalizeTitleForMatch(value: unknown): string {
  const text = cleanSourceTitle(value) || stripMarkup(asString(value)) || ''
  if (!text) return ''
  return decodeHtmlEntities(text)
    .replace(ARXIV_TITLE_PREFIX_PATTERN, '')
    .replace(/\(arxiv[:\s]*\d{4}\.\d{4,5}(?:v\d+)?\)/i, '')
    .toLowerCase()
    .replace(NON_ALNUM_PATTERN, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function titleTokens(value: unknown): Set<string> {
  return new Set(
    normalizeTitleForMatch(value)
      .split(/\s+/)
      .filter((token) => token && !TITLE_STOPWORDS.has(token)),
  )
}

function diceCoefficient(left: string, right: string): number {
  if (!left || !right) return 0
  if (left === right) return 1
  if (left.length < 2 || right.length < 2) return left === right ? 1 : 0

  const leftBigrams = new Map<string, number>()
  for (let idx = 0; idx < left.length - 1; idx += 1) {
    const key = left.slice(idx, idx + 2)
    leftBigrams.set(key, (leftBigrams.get(key) || 0) + 1)
  }

  let overlap = 0
  for (let idx = 0; idx < right.length - 1; idx += 1) {
    const key = right.slice(idx, idx + 2)
    const count = leftBigrams.get(key) || 0
    if (count <= 0) continue
    overlap += 1
    leftBigrams.set(key, count - 1)
  }

  return (2 * overlap) / ((left.length - 1) + (right.length - 1))
}

function titleMatchScore(left: unknown, right: unknown): number {
  const leftNorm = normalizeTitleForMatch(left)
  const rightNorm = normalizeTitleForMatch(right)
  if (!leftNorm || !rightNorm) return 0
  if (leftNorm === rightNorm) return 1
  const shorter = Math.min(leftNorm.length, rightNorm.length)
  if (shorter >= 24 && (leftNorm.includes(rightNorm) || rightNorm.includes(leftNorm))) {
    return 0.98
  }

  const tokenLeft = titleTokens(leftNorm)
  const tokenRight = titleTokens(rightNorm)
  const overlap = new Set<string>()
  const union = new Set<string>()
  tokenLeft.forEach((token) => {
    union.add(token)
    if (tokenRight.has(token)) overlap.add(token)
  })
  tokenRight.forEach((token) => {
    union.add(token)
  })
  const jaccard = union.size ? overlap.size / union.size : 0
  const coverage = Math.min(tokenLeft.size, tokenRight.size)
    ? overlap.size / Math.max(1, Math.min(tokenLeft.size, tokenRight.size))
    : 0
  return Math.max(diceCoefficient(leftNorm, rightNorm), jaccard, coverage)
}

function extractArxivId(value: unknown): string | null {
  const text = asString(value)
  if (!text) return null
  const doiMatch = text.match(ARXIV_DOI_PATTERN)
  if (doiMatch?.[1]) return doiMatch[1]
  const match = text.match(ARXIV_PATTERN)
  return match?.[1] || null
}

function extractDoi(value: unknown): string | null {
  const text = asString(value)
  if (!text) return null
  const match = text.match(DOI_PATTERN)
  return match?.[0]?.toLowerCase() || null
}

function canonicalScholarlyUrl(...values: Array<unknown>): string | null {
  for (const value of values) {
    const arxivId = extractArxivId(value)
    if (arxivId) return `https://arxiv.org/abs/${arxivId}`
  }
  for (const value of values) {
    const doi = extractDoi(value)
    if (doi) return `https://doi.org/${doi}`
  }
  for (const value of values) {
    const canonical = canonicalizeHttpUrl(asString(value))
    if (canonical) return canonical
  }
  return null
}

async function fetchArxivMetadata(
  arxivId: string,
  timeoutMs: number,
): Promise<{ title: string; url: string } | null> {
  const url = new URL('https://export.arxiv.org/api/query')
  url.searchParams.set('id_list', arxivId)
  const xml = await fetchTextWithTimeout(url.toString(), timeoutMs)
  if (!xml) return null
  const entry = xml.match(/<entry\b[\s\S]*?<\/entry>/i)?.[0]
  if (!entry) return null
  const title = cleanSourceTitle(entry.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1])
  const entryId = stripMarkup(entry.match(/<id[^>]*>([\s\S]*?)<\/id>/i)?.[1])
  const canonicalUrl = canonicalScholarlyUrl(entryId, arxivId)
  if (!title || !canonicalUrl) return null
  return { title, url: canonicalUrl }
}

async function fetchOpenAlexDoiMetadata(
  doi: string,
  timeoutMs: number,
): Promise<{ title: string; url: string } | null> {
  const url = new URL('https://api.openalex.org/works')
  url.searchParams.set('filter', `doi:${doi}`)
  url.searchParams.set('per-page', '1')
  const payload = await fetchJsonWithTimeout(url.toString(), timeoutMs)
  const results = Array.isArray(payload?.results) ? payload.results : []
  const record = asRecord(results[0])
  if (!record) return null
  const primaryLocation = asRecord(record.primary_location)
  const ids = asRecord(record.ids)
  const title = cleanSourceTitle(record.display_name) || cleanSourceTitle(record.title)
  const canonicalUrl = canonicalScholarlyUrl(primaryLocation?.landing_page_url, record.doi, ids?.doi)
  if (!title || !canonicalUrl) return null
  return { title, url: canonicalUrl }
}

async function fetchCrossrefDoiMetadata(
  doi: string,
  timeoutMs: number,
): Promise<{ title: string; url: string } | null> {
  const payload = await fetchJsonWithTimeout(
    `https://api.crossref.org/works/${encodeURIComponent(doi)}`,
    timeoutMs,
  )
  const message = asRecord(payload?.message)
  const title = cleanSourceTitle(asStringArray(message?.title).join(' '))
  const canonicalUrl = canonicalScholarlyUrl(`https://doi.org/${doi}`)
  if (!title || !canonicalUrl) return null
  return { title, url: canonicalUrl }
}

async function lookupOpenAlexTitle(
  title: string,
  timeoutMs: number,
): Promise<{ title: string; url: string; matchScore: number } | null> {
  const url = new URL('https://api.openalex.org/works')
  url.searchParams.set('search', title)
  url.searchParams.set('per-page', '5')
  const payload = await fetchJsonWithTimeout(url.toString(), timeoutMs)
  const results = Array.isArray(payload?.results) ? payload.results : []

  let best: { title: string; url: string; matchScore: number } | null = null
  for (const item of results) {
    const record = asRecord(item)
    if (!record) continue
    const candidateTitle = cleanSourceTitle(record.display_name) || cleanSourceTitle(record.title)
    if (!candidateTitle) continue
    const primaryLocation = asRecord(record.primary_location)
    const ids = asRecord(record.ids)
    const canonicalUrl = canonicalScholarlyUrl(primaryLocation?.landing_page_url, record.doi, ids?.doi)
    if (!canonicalUrl) continue
    const score = titleMatchScore(title, candidateTitle)
    if (!best || score >= best.matchScore) {
      best = { title: candidateTitle, url: canonicalUrl, matchScore: score }
    }
  }
  return best
}

async function validatePaperLink(
  finalUrl: string | null | undefined,
  title: string | null,
  timeoutMs: number,
): Promise<LinkValidationResult> {
  const canonicalUrl = canonicalScholarlyUrl(finalUrl)
  const cleanTitle = cleanSourceTitle(title)
  if (!canonicalUrl) {
    return { finalUrl: null, status: 'missing_url', reason: 'missing_url' }
  }
  if (!cleanTitle) {
    return { finalUrl: canonicalUrl, status: 'skipped', reason: 'missing_or_generic_title' }
  }

  const arxivId = extractArxivId(canonicalUrl)
  if (arxivId) {
    const arxivMeta = await fetchArxivMetadata(arxivId, timeoutMs)
    if (arxivMeta) {
      const score = titleMatchScore(cleanTitle, arxivMeta.title)
      if (score >= TITLE_MATCH_THRESHOLD) {
        return {
          finalUrl: arxivMeta.url,
          status: 'confirmed',
          validatedBy: 'arxiv',
          matchedTitle: arxivMeta.title,
          matchScore: score,
        }
      }
      const corrected = await lookupOpenAlexTitle(cleanTitle, timeoutMs)
      if (corrected && corrected.matchScore >= TITLE_MATCH_THRESHOLD) {
        return {
          finalUrl: corrected.url,
          status: 'corrected',
          validatedBy: 'openalex',
          matchedTitle: corrected.title,
          reason: `arxiv_title_mismatch:${arxivId}`,
          matchScore: corrected.matchScore,
        }
      }
      return {
        finalUrl: null,
        status: 'dropped',
        validatedBy: 'arxiv',
        matchedTitle: arxivMeta.title,
        reason: `arxiv_title_mismatch:${arxivId}`,
        matchScore: score,
      }
    }
    const corrected = await lookupOpenAlexTitle(cleanTitle, timeoutMs)
    if (corrected && corrected.matchScore >= TITLE_MATCH_THRESHOLD) {
      return {
        finalUrl: corrected.url,
        status: 'corrected',
        validatedBy: 'openalex',
        matchedTitle: corrected.title,
        reason: `arxiv_lookup_failed:${arxivId}`,
        matchScore: corrected.matchScore,
      }
    }
    return {
      finalUrl: null,
      status: 'dropped',
      validatedBy: 'arxiv',
      reason: `arxiv_lookup_failed:${arxivId}`,
    }
  }

  const doi = extractDoi(canonicalUrl)
  if (doi) {
    const openAlexMeta = await fetchOpenAlexDoiMetadata(doi, timeoutMs)
    if (openAlexMeta) {
      const score = titleMatchScore(cleanTitle, openAlexMeta.title)
      if (score >= TITLE_MATCH_THRESHOLD) {
        return {
          finalUrl: openAlexMeta.url,
          status: 'confirmed',
          validatedBy: 'openalex',
          matchedTitle: openAlexMeta.title,
          matchScore: score,
        }
      }
    }

    const crossrefMeta = await fetchCrossrefDoiMetadata(doi, timeoutMs)
    if (crossrefMeta) {
      const score = titleMatchScore(cleanTitle, crossrefMeta.title)
      if (score >= TITLE_MATCH_THRESHOLD) {
        return {
          finalUrl: crossrefMeta.url,
          status: 'confirmed',
          validatedBy: 'crossref',
          matchedTitle: crossrefMeta.title,
          matchScore: score,
        }
      }
    }

    const corrected = await lookupOpenAlexTitle(cleanTitle, timeoutMs)
    if (corrected && corrected.matchScore >= TITLE_MATCH_THRESHOLD) {
      return {
        finalUrl: corrected.url,
        status: 'corrected',
        validatedBy: 'openalex',
        matchedTitle: corrected.title,
        reason: `doi_title_mismatch:${doi}`,
        matchScore: corrected.matchScore,
      }
    }

    return {
      finalUrl: null,
      status: 'dropped',
      validatedBy: 'doi',
      reason: `doi_title_mismatch:${doi}`,
    }
  }

  return {
    finalUrl: canonicalUrl,
    status: 'skipped',
    reason: 'non_identifier_url',
  }
}

function pickFirstString(record: JsonRecord, keys: string[]): string | null {
  for (const key of keys) {
    const value = asString(record[key])
    if (value) return value
  }
  return null
}

function extractCandidateSources(payload: unknown): Array<{
  url: string
  title: string | null
  snippet: string | null
  publisher: string | null
}> {
  const collected: Array<{
    url: string
    title: string | null
    snippet: string | null
    publisher: string | null
  }> = []
  const seen = new Set<string>()

  const add = (entry: {
    url: string
    title?: string | null
    snippet?: string | null
    publisher?: string | null
  }): void => {
    const url = asString(entry.url)
    if (!url || !isHttpUrl(url)) return
    const normalizedKey = url.toLowerCase()
    if (seen.has(normalizedKey)) return
    seen.add(normalizedKey)
    collected.push({
      url,
      title: asString(entry.title) || null,
      snippet: asString(entry.snippet) || null,
      publisher: asString(entry.publisher) || null,
    })
  }

  const visit = (node: unknown, parent?: JsonRecord | null): void => {
    if (Array.isArray(node)) {
      for (const item of node) visit(item, parent)
      return
    }

    if (typeof node === 'string') {
      if (isHttpUrl(node)) {
        add({
          url: node,
          title: parent ? pickFirstString(parent, ['title', 'name', 'label']) : null,
          snippet: parent ? pickFirstString(parent, ['snippet', 'summary', 'text', 'content']) : null,
          publisher: parent ? pickFirstString(parent, ['publisher', 'site_name', 'domain']) : null,
        })
      }
      return
    }

    const record = asRecord(node)
    if (!record) return

    const directUrl = pickFirstString(record, [
      'url',
      'uri',
      'link',
      'href',
      'source_url',
      'sourceUrl',
      'canonical_url',
      'canonicalUrl',
    ])
    if (directUrl && isHttpUrl(directUrl)) {
      add({
        url: directUrl,
        title: pickFirstString(record, ['title', 'name', 'label']),
        snippet: pickFirstString(record, ['snippet', 'summary', 'text', 'content', 'quote']),
        publisher: pickFirstString(record, ['publisher', 'site_name', 'siteName', 'domain']),
      })
    }

    for (const value of Object.values(record)) {
      visit(value, record)
    }
  }

  visit(payload)
  return collected
}

function collectDeepResearchDocuments(result: JsonRecord): JsonRecord[] {
  const directCandidates: unknown[] = []

  const appendArray = (value: unknown): void => {
    if (!Array.isArray(value)) return
    directCandidates.push(...value)
  }

  appendArray(result.documents)
  appendArray(result.sources)
  appendArray(result.references)
  appendArray(result.citations)

  const response = asRecord(result.response)
  if (response) {
    appendArray(response.documents)
    appendArray(response.sources)
    appendArray(response.references)
    appendArray(response.citations)
  }

  const raw = asRecord(result.raw)
  if (raw) {
    appendArray(raw.documents)
    appendArray(raw.sources)
    appendArray(raw.references)
    appendArray(raw.citations)
  }

  const fromDirect = directCandidates
    .map((item) => asRecord(item) || (typeof item === 'string' ? ({ url: item } as JsonRecord) : null))
    .filter((item): item is JsonRecord => Boolean(item))

  const nestedCandidates = extractCandidateSources({
    result,
    response,
    raw,
  }).map((item, index) => {
    const snippets = item.snippet ? [item.snippet] : []
    return {
      doc_id: `nested-${index + 1}`,
      title: item.title,
      url: item.url,
      publisher: item.publisher,
      snippets,
    } satisfies JsonRecord
  })

  const merged: JsonRecord[] = []
  const seen = new Set<string>()
  for (const doc of [...fromDirect, ...nestedCandidates]) {
    const url = pickFirstString(doc, ['url', 'uri', 'link', 'href'])
    const key = (url || asString(doc.doc_id) || JSON.stringify(doc)).toLowerCase()
    if (!key || seen.has(key)) continue
    seen.add(key)
    merged.push(doc)
  }

  return merged
}

function clampText(value: string | null, max = 220): string {
  if (!value) return ''
  if (value.length <= max) return value
  return `${value.slice(0, max - 3)}...`
}

function isOpaqueDeepResearchText(value: string | null | undefined): boolean {
  const text = (value || '').trim()
  if (!text) return false
  if (URL_PATTERN.test(text)) return false
  if (/\s/.test(text)) return false
  if (text.toUpperCase().startsWith('AUZIYQ') && text.length >= 24) return true
  if (text.length < 40 || !OPAQUE_TOKEN_PATTERN.test(text)) return false
  if (!text.includes('.') && !text.includes('/')) return true
  return (text.match(/[_-]/g) || []).length >= 2 && text.length >= 56
}

function normalizeDeepResearchText(value: string | null | undefined, max: number): string {
  const normalized = clampText(asString(value), max)
  if (!normalized) return ''
  if (isOpaqueDeepResearchText(normalized)) return ''
  return normalized
}

function countWords(value: string | null | undefined): number {
  const text = (value || '').trim()
  if (!text) return 0
  return text.split(/\s+/).filter(Boolean).length
}

function isSynthesisInformative(value: string | null | undefined): boolean {
  const text = (value || '').trim()
  if (!text) return false
  if (isOpaqueDeepResearchText(text)) return false
  return countWords(text) >= DEFAULT_SYNTHESIS_MIN_WORDS
}

function extractAgentChatText(payload: JsonRecord | null): string {
  if (!payload) return ''
  const directText =
    asString(payload.text) ||
    asString(payload.content) ||
    asString((asRecord(payload.message) || {}).content)
  if (directText) return directText

  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : []
  for (const artifact of artifacts) {
    const record = asRecord(artifact)
    const value = asString(record?.text) || asString(record?.content) || asString(record?.summary)
    if (value) return value
  }
  return ''
}

function buildSynthesisPrompt(args: {
  query: string
  sourceInventory: DeepResearchReportSource[]
}): string {
  const topSources = args.sourceInventory
    .slice(0, 8)
    .map((item, index) => {
      const title = item.display_title || item.label || `Source ${index + 1}`
      const summary = item.summary || 'No summary provided.'
      const sourceHint = item.final_url || item.url || item.source_host || 'unknown source'
      return `${index + 1}. Title: ${title}\nSummary: ${summary}\nSource: ${sourceHint}`
    })
    .join('\n\n')

  return [
    'You are preparing a concise deep-research synthesis for scientists.',
    `Question: ${args.query}`,
    '',
    'Evidence snippets:',
    topSources || 'No snippets available.',
    '',
    'Write exactly 3-5 sentences that include:',
    '1) Core findings supported across sources.',
    '2) Any disagreement or uncertainty between sources.',
    '3) Practical implication for the question.',
    'Rules: be objective; do not invent sources or claims beyond the provided evidence.',
  ].join('\n')
}

async function tryGenerateLlmSynthesis(args: {
  query: string
  sourceInventory: DeepResearchReportSource[]
  authHeaders?: Headers
}): Promise<string | null> {
  const fallbackEnabled = process.env.HYPOTHESIS_SYNTHESIS_LLM_FALLBACK !== '0'
  if (!fallbackEnabled) return null
  if (!args.authHeaders || !args.sourceInventory.length) return null

  const headers = new Headers(args.authHeaders)
  headers.set('content-type', 'application/json')
  const response = await fetch(`${resolveAgentBaseUrl()}/api/chat`, {
    method: 'POST',
    headers,
    cache: 'no-store',
    body: JSON.stringify({
      tool_mode: 'none',
      messages: [{ role: 'user', content: buildSynthesisPrompt(args) }],
    }),
  }).catch(() => null)

  if (!response || !response.ok) return null
  const payload = (await response.json().catch(() => null)) as JsonRecord | null
  const text = normalizeDeepResearchText(extractAgentChatText(payload), 20_000)
  if (!text) return null
  return isOpaqueDeepResearchText(text) ? null : text
}

function buildRuleBasedSynthesis(args: {
  query: string
  sourceInventory: DeepResearchReportSource[]
  summary: string
}): string {
  const sourceCount = args.sourceInventory.length
  const top = args.sourceInventory.slice(0, 3)
  const findingFragments = top
    .map((item) => normalizeDeepResearchText(item.summary, 180))
    .filter((item): item is string => Boolean(item))
  const sourceNames = top
    .map((item) => item.display_title || item.label || item.source_host)
    .filter((item): item is string => Boolean(item))
    .slice(0, 3)

  const intro = `Deep research reviewed ${sourceCount} citeable source${sourceCount === 1 ? '' : 's'} for "${args.query}".`
  const finding =
    findingFragments.length > 0
      ? `Across the reviewed material, common signals include: ${findingFragments.join(' ')}`
      : `The available summaries provide limited detail, so interpretation remains cautious.`
  const divergence =
    sourceNames.length > 1
      ? `Evidence coverage spans ${sourceNames.join(', ')}, and differences across sources should be treated as unresolved until additional primary reports are retrieved.`
      : `Most retained evidence traces to a narrow source base, so conclusions should be treated as preliminary.`
  const implication =
    normalizeDeepResearchText(args.summary, 320) ||
    'Use this synthesis as directional context and verify claims against full-text primary sources before final decisions.'
  return [intro, finding, divergence, implication].join(' ')
}

function buildDiscardedAggregates(
  discardedSources: DeepResearchDiscardedSource[],
): DeepResearchDiscardAggregate[] {
  const groups = new Map<DeepResearchDiscardReasonCode, DeepResearchDiscardedSource[]>()
  for (const item of discardedSources) {
    const reason = item.reason_code || 'unknown'
    const bucket = groups.get(reason)
    if (bucket) bucket.push(item)
    else groups.set(reason, [item])
  }

  const aggregates: DeepResearchDiscardAggregate[] = []
  groups.forEach((items, reasonCode) => {
    if (reasonCode === 'redirect_unresolved') {
      const stats: Record<string, number> = {}
      for (const item of items) {
        const meta = item.reason_meta
        if (!meta) continue
        if (meta.attempted) stats.attempted = (stats.attempted || 0) + 1
        if (meta.skipped_by_budget) {
          stats.skipped_by_budget = (stats.skipped_by_budget || 0) + 1
        }
        const resolver = meta.resolver || 'none'
        stats[`resolver_${resolver}`] = (stats[`resolver_${resolver}`] || 0) + 1
        if (typeof meta.http_status === 'number' && Number.isFinite(meta.http_status)) {
          stats[`http_${Math.trunc(meta.http_status)}`] =
            (stats[`http_${Math.trunc(meta.http_status)}`] || 0) + 1
        }
      }
      aggregates.push({
        reason_code: reasonCode,
        count: items.length,
        detail: `${items.length} source${items.length === 1 ? '' : 's'} from grounding redirects could not be resolved to citeable URLs.`,
        stats,
      })
      return
    }

    aggregates.push({
      reason_code: reasonCode,
      count: items.length,
      detail: `${items.length} source${items.length === 1 ? '' : 's'} removed due to ${reasonCode}.`,
    })
  })

  return aggregates.sort((left, right) => right.count - left.count)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function isToolNotFoundError(error: unknown): boolean {
  const message = extractErrorMessage(error).toLowerCase()
  return (
    message.includes('not found') ||
    message.includes('unknown tool') ||
    message.includes('tool_not_allowed')
  )
}

function isRecoverableDeepResearchError(error: unknown): boolean {
  const message = extractErrorMessage(error).toLowerCase()
  return (
    message.includes('datetime') ||
    message.includes('json serializable') ||
    message.includes('serialization') ||
    message.includes('requires interaction_id')
  )
}

function isNoSeedEntitiesError(error: unknown): boolean {
  const message = extractErrorMessage(error)
  return NO_SEED_ENTITIES_PATTERN.test(message)
}

function isTransientToolCallFailure(error: unknown): boolean {
  if (isAgentToolError(error)) {
    if (error.code === 'timeout' || error.code === 'network_error') {
      return true
    }
    if (error.code === 'http_error' && typeof error.status === 'number') {
      return error.status === 429 || error.status >= 500
    }
  }

  const message = extractErrorMessage(error).toLowerCase()
  return (
    message.includes('network') ||
    message.includes('timed out') ||
    message.includes('econnreset') ||
    message.includes('socket hang up') ||
    message.includes('temporarily unavailable')
  )
}

function toDeepResearchError(error: unknown): DeepResearchRuntimeError {
  const existingCode = getDeepResearchErrorCode(error)
  if (existingCode && error instanceof Error) {
    return error as DeepResearchRuntimeError
  }

  const message = extractErrorMessage(error) || 'Deep research request failed.'
  if (isToolNotFoundError(error)) {
    return createDeepResearchError({
      code: DEEP_RESEARCH_ERROR_CODES.TOOL_NOT_FOUND,
      message,
      cause: error,
    })
  }
  if (isTransientToolCallFailure(error)) {
    return createDeepResearchError({
      code: DEEP_RESEARCH_ERROR_CODES.TRANSIENT_TOOL_FAILURE,
      message,
      retryable: true,
      cause: error,
    })
  }
  return createDeepResearchError({
    code: DEEP_RESEARCH_ERROR_CODES.REQUEST_FAILED,
    message,
    cause: error,
  })
}

function readNestedDataField(payload: JsonRecord | null, key: string): unknown {
  if (!payload) return null

  const data = asRecord(payload.data)
  const result = asRecord(payload.result)
  const response = asRecord(payload.response)
  const outputs =
    asRecord(payload.outputs) || asRecord(data?.outputs) || asRecord(result?.outputs)

  const candidates: Array<JsonRecord | null> = [payload, data, result, outputs, response]
  for (const candidate of candidates) {
    if (!candidate) continue
    if (Object.prototype.hasOwnProperty.call(candidate, key)) {
      return candidate[key]
    }
  }

  return null
}

function extractToolRunResponse(raw: unknown): ToolRunResponse {
  const root = asRecord(raw) || {}
  const result = asRecord(root.result)
  const resultData = asRecord(result?.data)
  const rootData = asRecord(root.data)

  const resultStatus =
    asString(result?.status)?.toLowerCase() || asString(root.status)?.toLowerCase() || null
  const toolError =
    asString(result?.error) || asString(root.error) || asString(root.detail) || null

  const payloadCandidates: Array<JsonRecord | null> = [
    asRecord(resultData?.data),
    asRecord(rootData?.data),
    resultData,
    asRecord(result?.result),
    rootData,
    asRecord(root.result),
    result,
    root,
  ]

  const payload =
    payloadCandidates.find((candidate) => {
      if (!candidate) return false
      return (
        Object.prototype.hasOwnProperty.call(candidate, 'ok') ||
        Object.prototype.hasOwnProperty.call(candidate, 'status') ||
        Object.prototype.hasOwnProperty.call(candidate, 'state') ||
        Object.prototype.hasOwnProperty.call(candidate, 'text') ||
        Object.prototype.hasOwnProperty.call(candidate, 'result') ||
        Object.prototype.hasOwnProperty.call(candidate, 'interaction_id') ||
        Object.prototype.hasOwnProperty.call(candidate, 'idempotency_key') ||
        Object.prototype.hasOwnProperty.call(candidate, 'documents') ||
        Object.prototype.hasOwnProperty.call(candidate, 'concepts') ||
        Object.prototype.hasOwnProperty.call(candidate, 'summary') ||
        Object.prototype.hasOwnProperty.call(candidate, 'paths') ||
        Object.prototype.hasOwnProperty.call(candidate, 'answer') ||
        Object.prototype.hasOwnProperty.call(candidate, 'warnings') ||
        Object.prototype.hasOwnProperty.call(candidate, 'outputs')
      )
    }) || null

  return {
    resultStatus,
    toolError,
    payload,
  }
}

async function loadCalibratedClaimReview(args: {
  runId: string | null
  authHeaders?: Headers
}): Promise<DeepResearchClaimReview | null> {
  if (!args.runId) return null

  try {
    const response = await runAgentTool({
      tool: 'artifact_read_text',
      authHeaders: args.authHeaders,
      arguments: {
        run_id: args.runId,
        relpath: 'claim_report.json',
        max_bytes: 200_000,
      },
    })
    const payload = response.payload
    const ok = readNestedDataField(payload, 'ok')
    if (ok === false) return null

    const text = asString(readNestedDataField(payload, 'text'))
    if (!text) return null

    const parsed = JSON.parse(text) as unknown
    return normalizeClaimReviewPayload(asRecord(parsed), args.runId)
  } catch {
    return null
  }
}

async function runAgentTool(args: {
  tool: string
  arguments: Record<string, unknown>
  authHeaders?: Headers
  timeoutMs?: number | null
}): Promise<ToolRunResponse> {
  const headers = new Headers(args.authHeaders || undefined)
  headers.set('content-type', 'application/json')

  const controller = new AbortController()
  const resolvedTimeoutMs =
    args.timeoutMs === undefined
      ? DEFAULT_TOOL_TIMEOUT_MS
      : args.timeoutMs === null
        ? 0
        : Number.isFinite(args.timeoutMs)
          ? Math.trunc(args.timeoutMs)
          : DEFAULT_TOOL_TIMEOUT_MS
  const useTimeout = resolvedTimeoutMs > 0
  const timeoutId = useTimeout ? setTimeout(() => controller.abort(), resolvedTimeoutMs) : null

  try {
    const requestInit: RequestInit = {
      method: 'POST',
      headers,
      cache: 'no-store',
      body: JSON.stringify({
        tool: args.tool,
        arguments: args.arguments,
        args: args.arguments,
      }),
    }
    if (useTimeout) {
      requestInit.signal = controller.signal
    }
    const response = await fetch(`${resolveAgentBaseUrl()}/api/tools/run`, requestInit)

    const rawText = await response
      .clone()
      .text()
      .catch(() => response.text().catch(() => ''))
    let payload: unknown = null
    if (rawText) {
      try {
        payload = JSON.parse(rawText)
      } catch {
        payload = { detail: rawText }
      }
    }

    if (!response.ok) {
      const parsed = asRecord(payload) || {}
      const detail = asString(parsed.detail) || asString(parsed.error) || `HTTP ${response.status}`
      throw createAgentToolError({
        code: 'http_error',
        tool: args.tool,
        status: response.status,
        detail,
        message: `Tool ${args.tool} failed: ${detail}`,
      })
    }

    const parsed = extractToolRunResponse(payload)
    if (parsed.resultStatus === 'error') {
      const detail = parsed.toolError || 'unknown error'
      throw createAgentToolError({
        code: 'result_error',
        tool: args.tool,
        detail,
        message: `Tool ${args.tool} failed: ${detail}`,
      })
    }
    return parsed
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw createAgentToolError({
        code: 'timeout',
        tool: args.tool,
        message: `Tool ${args.tool} timed out after ${resolvedTimeoutMs}ms`,
        cause: error,
      })
    }
    if (isAgentToolError(error)) {
      throw error
    }
    throw createAgentToolError({
      code: 'network_error',
      tool: args.tool,
      message: `Tool ${args.tool} failed: ${extractErrorMessage(error)}`,
      cause: error,
    })
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
  }
}

function classifyEvidenceKind(
  document: JsonRecord,
  normalizedUrl?: string | null,
): HypothesisEvidenceItem['kind'] {
  const url = (normalizedUrl || asString(document.url) || '').toLowerCase()
  const title = asString(document.title)?.toLowerCase() || ''
  const combined = `${url} ${title}`

  if (
    combined.includes('dataset') ||
    combined.includes('openneuro') ||
    combined.includes('dandi') ||
    combined.includes('kaggle')
  ) {
    return 'dataset'
  }

  if (combined.includes('preprint') || combined.includes('arxiv') || combined.includes('biorxiv')) {
    return 'paper'
  }

  return 'paper'
}

function dedupTokenize(value: string): Set<string> {
  return new Set(
    value
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .map((token) => token.trim())
      .filter((token) => token.length >= 4 && !/^\d+$/.test(token)),
  )
}

function dedupJaccard(left: Set<string>, right: Set<string>): number {
  if (!left.size || !right.size) return 0
  let overlap = 0
  left.forEach((token) => {
    if (right.has(token)) overlap += 1
  })
  if (!overlap) return 0
  const union = left.size + right.size - overlap
  return union > 0 ? overlap / union : 0
}

function normalizeEvidenceTextForDedup(value: string | null | undefined): string {
  if (typeof value !== 'string') return ''
  return value
    .toLowerCase()
    .replace(/[#*_`>]+/g, ' ')
    .replace(/\[[^\]]+\]\((https?:\/\/[^\s)]+)\)/g, '$1')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeTitleForDegenerate(value: string | null | undefined): string {
  return normalizeEvidenceTextForDedup(value)
    .replace(/^#+\s*/, '')
    .replace(/^title\s*:\s*/i, '')
    .trim()
}

function normalizeSummaryForDegenerate(value: string | null | undefined): string {
  return normalizeEvidenceTextForDedup(value)
    .replace(/\b(executive summary|key points|highlights?|introduction|conclusion)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function summaryFingerprint(value: string | null | undefined): string {
  const normalized = normalizeSummaryForDegenerate(value)
  if (normalized.length < 40) return ''
  return normalized
}

function evidenceContentFingerprint(item: HypothesisEvidenceItem): string {
  const label = normalizeEvidenceTextForDedup(item.label)
  const summary = normalizeEvidenceTextForDedup(item.summary || null)
  return `${label} | ${summary}`.trim()
}

function isLikelySyntheticSummaryText(value: string | null | undefined): boolean {
  if (typeof value !== 'string') return false
  const raw = value.toLowerCase()
  if (!raw.trim()) return false
  const hasStructuredHeadings = /(^|\n)\s*#{1,3}\s*(executive summary|key points|synthesis|comprehensive analysis|findings)/m.test(
    raw,
  )
  const hasNarrativeBoilerplate =
    raw.includes('paradigm shift') ||
    raw.includes('recent research') ||
    raw.includes('comprehensive analysis') ||
    raw.includes('synthesis')
  const hasListFormatting = raw.includes('* **') || raw.includes('- **')
  return hasStructuredHeadings || (hasNarrativeBoilerplate && hasListFormatting)
}

function isLikelySyntheticEvidence(item: HypothesisEvidenceItem): boolean {
  if (item.synthetic_summary) return true
  const label = normalizeEvidenceTextForDedup(item.label)
  const summary = normalizeEvidenceTextForDedup(item.summary || null)
  const combined = `${label} ${summary}`
  const hasSynthesisMarker =
    isLikelySyntheticSummaryText(item.summary || null) ||
    combined.includes('synthesis') ||
    combined.includes('key points') ||
    combined.includes('recent research') ||
    combined.includes('paradigm shift')
  return hasSynthesisMarker && (label.startsWith('advances in') || item.label.trim().startsWith('#'))
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, code: string) => {
      const parsed = Number(code)
      return Number.isFinite(parsed) ? String.fromCharCode(parsed) : ''
    })
    .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => {
      const parsed = Number.parseInt(code, 16)
      return Number.isFinite(parsed) ? String.fromCharCode(parsed) : ''
    })
}

function stripMarkup(value: string | null | undefined): string {
  if (typeof value !== 'string') return ''
  return decodeHtmlEntities(value.replace(/<[^>]+>/g, ' '))
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeAbstractCandidate(
  value: string | null | undefined,
  maxSummaryChars: number,
): string | null {
  const stripped = stripMarkup(value)
    .replace(/^abstract\s*[:.\-]?\s*/i, '')
    .trim()
  if (!stripped || stripped.length < 40) return null
  return clampText(stripped, maxSummaryChars)
}

function extractPubmedIdFromUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (!parsed.hostname.includes('pubmed.ncbi.nlm.nih.gov')) return null
    const segment = parsed.pathname.split('/').filter(Boolean)[0]
    return segment && /^\d+$/.test(segment) ? segment : null
  } catch {
    return null
  }
}

function extractPmcIdFromUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (!parsed.hostname.includes('pmc.ncbi.nlm.nih.gov')) return null
    const match = parsed.pathname.match(/\/articles\/(PMC\d+)/i)
    return match?.[1]?.toUpperCase() || null
  } catch {
    return null
  }
}

function extractDoiFromUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (parsed.hostname.includes('doi.org')) {
      const doiPath = decodeURIComponent(parsed.pathname.replace(/^\/+/, ''))
      return doiPath || null
    }
    const combined = decodeURIComponent(`${parsed.pathname}${parsed.search}`)
    const match = combined.match(/(10\.\d{4,9}\/[-._;()/:A-Z0-9]+)/i)
    return match?.[1] || null
  } catch {
    return null
  }
}

async function fetchTextWithTimeout(url: string, timeoutMs: number): Promise<string | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(url, {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
      headers: {
        accept: 'application/xml,text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
      },
    })
    if (!response.ok) return null
    const text = await response.text()
    if (!text) return null
    return text.slice(0, 500_000)
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

async function fetchJsonWithTimeout(url: string, timeoutMs: number): Promise<JsonRecord | null> {
  const text = await fetchTextWithTimeout(url, timeoutMs)
  if (!text) return null
  try {
    return JSON.parse(text) as JsonRecord
  } catch {
    return null
  }
}

function extractMetaDescription(html: string): string | null {
  const tags = html.match(/<meta\s+[^>]*>/gi) || []
  for (const tag of tags) {
    const lower = tag.toLowerCase()
    const isTarget =
      lower.includes('name="description"') ||
      lower.includes("name='description'") ||
      lower.includes('property="og:description"') ||
      lower.includes("property='og:description'") ||
      lower.includes('name="dc.description"') ||
      lower.includes("name='dc.description'")
    if (!isTarget) continue
    const contentMatch = tag.match(/content=(["'])([\s\S]*?)\1/i)
    if (!contentMatch?.[2]) continue
    const normalized = normalizeAbstractCandidate(contentMatch[2], 480)
    if (normalized) return normalized
  }
  return null
}

function extractAbstractFromHtml(html: string): string | null {
  const sectionPatterns = [
    /<section[^>]*id=(["'])[^"']*abstract[^"']*\1[^>]*>([\s\S]{0,7000}?)<\/section>/i,
    /<div[^>]*class=(["'])[^"']*abstract[^"']*\1[^>]*>([\s\S]{0,7000}?)<\/div>/i,
    /<p[^>]*class=(["'])[^"']*abstract[^"']*\1[^>]*>([\s\S]{0,4000}?)<\/p>/i,
  ]
  for (const pattern of sectionPatterns) {
    const match = html.match(pattern)
    if (!match?.[2]) continue
    const normalized = normalizeAbstractCandidate(match[2], 480)
    if (normalized) return normalized
  }
  return extractMetaDescription(html)
}

async function fetchPubMedAbstractByPmid(
  pmid: string,
  timeoutMs: number,
  maxSummaryChars: number,
): Promise<string | null> {
  const url = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=${encodeURIComponent(
    pmid,
  )}&retmode=xml`
  const xml = await fetchTextWithTimeout(url, timeoutMs)
  if (!xml) return null
  const abstracts: string[] = []
  const pattern = /<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/gi
  let match: RegExpExecArray | null
  while ((match = pattern.exec(xml)) !== null) {
    const normalized = normalizeAbstractCandidate(match[1], maxSummaryChars)
    if (normalized) abstracts.push(normalized)
  }
  if (!abstracts.length) return null
  return clampText(abstracts.join(' '), maxSummaryChars)
}

async function resolvePmidFromPmcId(pmcid: string, timeoutMs: number): Promise<string | null> {
  const url = `https://pmc.ncbi.nlm.nih.gov/utils/idconv/v1.0/?tool=brain_researcher&format=json&ids=${encodeURIComponent(
    pmcid,
  )}`
  const payload = await fetchJsonWithTimeout(url, timeoutMs)
  const records = Array.isArray(payload?.records) ? payload?.records : []
  const first = asRecord(records[0])
  const pmid = asString(first?.pmid)
  return pmid || null
}

async function fetchCrossrefAbstractByDoi(
  doi: string,
  timeoutMs: number,
  maxSummaryChars: number,
): Promise<string | null> {
  const url = `https://api.crossref.org/works/${encodeURIComponent(doi)}`
  const payload = await fetchJsonWithTimeout(url, timeoutMs)
  const message = asRecord(payload?.message)
  const abstract = asString(message?.abstract)
  return normalizeAbstractCandidate(abstract, maxSummaryChars)
}

async function fetchBestAbstractForUrl(args: {
  url: string
  timeoutMs: number
  maxSummaryChars: number
}): Promise<string | null> {
  const pubmedId = extractPubmedIdFromUrl(args.url)
  if (pubmedId) {
    const pubmedAbstract = await fetchPubMedAbstractByPmid(
      pubmedId,
      args.timeoutMs,
      args.maxSummaryChars,
    )
    if (pubmedAbstract) return pubmedAbstract
  }

  const pmcId = extractPmcIdFromUrl(args.url)
  if (pmcId) {
    const pmid = await resolvePmidFromPmcId(pmcId, args.timeoutMs)
    if (pmid) {
      const pubmedAbstract = await fetchPubMedAbstractByPmid(
        pmid,
        args.timeoutMs,
        args.maxSummaryChars,
      )
      if (pubmedAbstract) return pubmedAbstract
    }
  }

  const doi = extractDoiFromUrl(args.url)
  if (doi) {
    const crossrefAbstract = await fetchCrossrefAbstractByDoi(
      doi,
      args.timeoutMs,
      args.maxSummaryChars,
    )
    if (crossrefAbstract) return crossrefAbstract
  }

  const html = await fetchTextWithTimeout(args.url, args.timeoutMs)
  if (!html) return null
  return extractAbstractFromHtml(html)
}

async function runWithConcurrency<T>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  const limit = Math.max(1, Math.min(concurrency, items.length || 1))
  let index = 0
  const runners = Array.from({ length: limit }).map(async () => {
    while (index < items.length) {
      const current = items[index]
      index += 1
      await worker(current)
    }
  })
  await Promise.all(runners)
}

async function enrichEvidenceWithAbstracts(items: HypothesisEvidenceItem[]): Promise<HypothesisEvidenceItem[]> {
  const enabled = process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_ENRICH === '1'
  if (!enabled || !items.length) return items

  const timeoutMs = Math.max(
    500,
    Math.trunc(Number(process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_TIMEOUT_MS) || 3_000),
  )
  const maxDocs = Math.max(
    0,
    Math.trunc(Number(process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_MAX_DOCS) || 8),
  )
  const concurrency = Math.max(
    1,
    Math.min(8, Math.trunc(Number(process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_CONCURRENCY) || 5)),
  )
  const maxSummaryChars = Math.max(
    180,
    Math.min(700, Math.trunc(Number(process.env.HYPOTHESIS_EVIDENCE_ABSTRACT_MAX_CHARS) || 480)),
  )

  const candidateIndexes: number[] = []
  for (let idx = 0; idx < items.length; idx += 1) {
    const item = items[idx]
    if (item.kind !== 'paper') continue
    if (!isHttpUrl(item.url)) continue
    if (!item.url) continue
    if (!item.synthetic_summary) continue
    candidateIndexes.push(idx)
    if (candidateIndexes.length >= maxDocs) break
  }
  if (!candidateIndexes.length) return items

  const updates = new Map<number, HypothesisEvidenceItem>()
  await runWithConcurrency(candidateIndexes, concurrency, async (idx) => {
    const current = items[idx]
    if (!current?.url) return
    const abstract = await fetchBestAbstractForUrl({
      url: current.url,
      timeoutMs,
      maxSummaryChars,
    })
    if (!abstract) return
    if (isLikelySyntheticSummaryText(abstract)) return

    const sourceType = inferSourceType(current.url, current.label)
    const quality = inferEvidenceQuality({
      url: current.url,
      title: current.label,
      kind: sourceType === 'dataset' ? 'dataset' : 'paper',
      sourceType,
    })

    updates.set(idx, {
      ...current,
      summary: abstract,
      synthetic_summary: false,
      quality_tier: quality.tier,
      traceability_score: Math.max(current.traceability_score || 0, quality.traceabilityScore),
    })
  })

  if (!updates.size) return items
  return items.map((item, idx) => updates.get(idx) || item)
}

/** Resolve canonical ID (PMID preferred) for dedupe: PMID from URL, or PMC→PMID via NCBI. */
async function resolveCanonicalIdForItem(
  item: HypothesisEvidenceItem,
  timeoutMs: number,
): Promise<string | null> {
  const url = item.url || item.raw_url || item.display_url
  if (!url || !isHttpUrl(url)) return null
  const pmid = extractPubmedIdFromUrl(url)
  if (pmid) return pmid
  const pmcId = extractPmcIdFromUrl(url)
  if (!pmcId) return null
  const resolved = await resolvePmidFromPmcId(pmcId, timeoutMs)
  return resolved || pmcId
}

async function enrichEvidenceWithCanonicalIds(
  items: HypothesisEvidenceItem[],
): Promise<HypothesisEvidenceItem[]> {
  if (!items.length) return items
  const timeoutMs = Math.max(
    500,
    Math.trunc(Number(process.env.HYPOTHESIS_CANONICAL_ID_TIMEOUT_MS) || 2_000),
  )
  const maxDocs = Math.max(
    0,
    Math.min(items.length, Math.trunc(Number(process.env.HYPOTHESIS_CANONICAL_ID_MAX_DOCS) || 20)),
  )
  const concurrency = Math.max(1, Math.min(6, Math.trunc(Number(process.env.HYPOTHESIS_CANONICAL_ID_CONCURRENCY) || 3)))
  const candidateIndexes: number[] = []
  for (let idx = 0; idx < items.length && candidateIndexes.length < maxDocs; idx += 1) {
    const item = items[idx]
    if (item.kind !== 'paper') continue
    if (!item.url && !item.raw_url && !item.display_url) continue
    candidateIndexes.push(idx)
  }
  if (!candidateIndexes.length) return items

  const updates = new Map<number, HypothesisEvidenceItem>()
  await runWithConcurrency(candidateIndexes, concurrency, async (idx) => {
    const current = items[idx]
    const canonicalId = await resolveCanonicalIdForItem(current, timeoutMs)
    if (!canonicalId) return
    updates.set(idx, { ...current, canonical_id: canonicalId })
  })

  if (!updates.size) return items
  return items.map((item, idx) => updates.get(idx) || item)
}

async function validateEvidencePaperLinks(
  candidates: EvidenceCandidateWithTitle[],
): Promise<HypothesisEvidenceItem[]> {
  const enabled = process.env.HYPOTHESIS_IDENTIFIER_VALIDATION !== '0'
  if (!enabled || !candidates.length) return candidates.map(({ item }) => item)

  const timeoutMs = Math.max(
    500,
    Math.trunc(
      Number(process.env.HYPOTHESIS_IDENTIFIER_VALIDATION_TIMEOUT_MS) ||
        DEFAULT_IDENTIFIER_VALIDATION_TIMEOUT_MS,
    ),
  )
  const maxDocs = Math.max(
    0,
    Math.min(
      candidates.length,
      Math.trunc(
        Number(process.env.HYPOTHESIS_IDENTIFIER_VALIDATION_MAX_DOCS) ||
          DEFAULT_IDENTIFIER_VALIDATION_MAX_DOCS,
      ),
    ),
  )
  const concurrency = Math.max(
    1,
    Math.min(
      6,
      Math.trunc(
        Number(process.env.HYPOTHESIS_IDENTIFIER_VALIDATION_CONCURRENCY) ||
          DEFAULT_IDENTIFIER_VALIDATION_CONCURRENCY,
      ),
    ),
  )

  const candidateIndexes: number[] = []
  for (let idx = 0; idx < candidates.length && candidateIndexes.length < maxDocs; idx += 1) {
    const candidate = candidates[idx]
    if (candidate.item.kind !== 'paper') continue
    if (!candidate.item.url || !isHttpUrl(candidate.item.url)) continue
    if (!cleanSourceTitle(candidate.validationTitle)) continue
    if (!extractArxivId(candidate.item.url) && !extractDoi(candidate.item.url)) continue
    candidateIndexes.push(idx)
  }
  if (!candidateIndexes.length) return candidates.map(({ item }) => item)

  const updates = new Map<number, HypothesisEvidenceItem>()
  await runWithConcurrency(candidateIndexes, concurrency, async (idx) => {
    const current = candidates[idx]
    const validation = await validatePaperLink(
      current.item.url || null,
      current.validationTitle,
      timeoutMs,
    )

    const nextUrl = validation.finalUrl
    const nextLabel =
      current.item.label ||
      buildReadableLabel({
        title: current.validationTitle,
        url: nextUrl,
        fallbackId: current.item.id,
      })
    const nextSourceType = inferSourceType(nextUrl, nextLabel)
    const quality = inferEvidenceQuality({
      url: nextUrl,
      title: nextLabel,
      kind: nextSourceType === 'dataset' ? 'dataset' : 'paper',
      sourceType: nextSourceType,
    })
    const qualityTier = current.item.synthetic_summary ? 'tertiary' : quality.tier
    const traceabilityScore = current.item.synthetic_summary
      ? Math.min(quality.traceabilityScore, 0.35)
      : quality.traceabilityScore

    if (
      nextUrl === current.item.url &&
      nextLabel === current.item.label &&
      current.item.display_url === displayUrlFromUrl(nextUrl) &&
      current.item.source_host === sourceHostFromUrl(nextUrl) &&
      current.item.source_type === nextSourceType &&
      current.item.quality_tier === qualityTier &&
      current.item.traceability_score === traceabilityScore
    ) {
      return
    }

    updates.set(idx, {
      ...current.item,
      label: nextLabel,
      url: nextUrl,
      display_url: displayUrlFromUrl(nextUrl),
      source_host: sourceHostFromUrl(nextUrl),
      source_type: nextSourceType,
      quality_tier: qualityTier,
      traceability_score: traceabilityScore,
    })
  })

  return candidates.map(({ item }, idx) => updates.get(idx) || item)
}

function evidenceSortScore(item: HypothesisEvidenceItem): number {
  const tierWeight = item.quality_tier === 'primary' ? 3 : item.quality_tier === 'secondary' ? 2 : 1
  const traceability =
    typeof item.traceability_score === 'number' && Number.isFinite(item.traceability_score)
      ? item.traceability_score
      : 0
  const hostBonus = item.source_host ? 0.15 : 0
  const urlBonus = item.url ? 0.1 : 0
  const syntheticPenalty = isLikelySyntheticEvidence(item) ? -0.2 : 0
  return tierWeight + traceability + hostBonus + urlBonus + syntheticPenalty
}

function toDeepResearchReportSource(item: HypothesisEvidenceItem): DeepResearchReportSource {
  return {
    id: item.id,
    label: item.label,
    display_title: item.label || null,
    summary: item.summary || null,
    url: item.url || null,
    raw_url: item.raw_url || null,
    final_url: item.url || null,
    source_host: item.source_host || null,
    kind: item.kind,
    source_type: item.source_type || null,
    quality_tier: item.quality_tier || null,
    traceability_score:
      typeof item.traceability_score === 'number' && Number.isFinite(item.traceability_score)
        ? item.traceability_score
        : null,
  }
}

function toDiscardedSource(args: {
  item: HypothesisEvidenceItem
  reasonCode: DeepResearchDiscardReasonCode
  reasonDetail?: string | null
  reasonMeta?: DeepResearchDiscardReasonMeta | null
}): DeepResearchDiscardedSource {
  return {
    ...toDeepResearchReportSource(args.item),
    reason_code: args.reasonCode,
    reason_detail: args.reasonDetail || null,
    reason_meta: args.reasonMeta || null,
  }
}

function dedupeDiscardedSources(items: DeepResearchDiscardedSource[]): DeepResearchDiscardedSource[] {
  const seen = new Set<string>()
  const unique: DeepResearchDiscardedSource[] = []
  for (const item of items) {
    const key = [
      item.reason_code,
      item.id.toLowerCase(),
      (item.url || '').toLowerCase(),
      item.label.toLowerCase(),
    ].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(item)
  }
  return unique
}

function applyDegenerateEvidencePolicy(items: HypothesisEvidenceItem[]): {
  items: HypothesisEvidenceItem[]
  diagnostics: DeepResearchDegenerateEvidenceDiagnostics
  discarded: DeepResearchDiscardedSource[]
} {
  if (!items.length) {
    return {
      items,
      diagnostics: {
        degenerate: false,
        reason: null,
        mode: 'none',
        dedupeStats: {
          before: 0,
          after: 0,
          collapsedGroups: 0,
        },
      },
      discarded: [],
    }
  }

  const ungrouped: HypothesisEvidenceItem[] = []
  const grouped = new Map<string, HypothesisEvidenceItem[]>()
  const discarded: DeepResearchDiscardedSource[] = []

  for (const item of items) {
    const summaryKey = summaryFingerprint(item.summary || null)
    if (summaryKey) {
      const key = `summary:${summaryKey}`
      const bucket = grouped.get(key)
      if (bucket) {
        bucket.push(item)
      } else {
        grouped.set(key, [item])
      }
      continue
    }

    const titleKey = normalizeTitleForDegenerate(item.label)
    if (titleKey) {
      const key = `title:${titleKey}`
      const bucket = grouped.get(key)
      if (bucket) {
        bucket.push(item)
      } else {
        grouped.set(key, [item])
      }
      continue
    }

    const contentKey = evidenceContentFingerprint(item)
    if (!contentKey) {
      ungrouped.push(item)
      continue
    }

    const key = `content:${contentKey}`
    const bucket = grouped.get(key)
    if (bucket) {
      bucket.push(item)
    } else {
      grouped.set(key, [item])
    }
  }

  let collapsedGroups = 0
  const survivors: HypothesisEvidenceItem[] = [...ungrouped]
  for (const group of Array.from(grouped.values())) {
    if (group.length <= 1) {
      survivors.push(group[0])
      continue
    }
    collapsedGroups += 1
    const winner = [...group].sort(
      (left, right) => evidenceSortScore(right) - evidenceSortScore(left),
    )[0]
    survivors.push(winner)
    for (const item of group) {
      if (item.id === winner.id) continue
      discarded.push(
        toDiscardedSource({
          item,
          reasonCode: 'duplicate_cluster',
          reasonDetail: 'Collapsed by summary/title/content fingerprint cluster.',
        }),
      )
    }
  }

  const degenerate = collapsedGroups > 0
  const reason = degenerate
    ? `Detected ${collapsedGroups} repeated evidence group(s) by summary/title fingerprint; kept top-ranked source per group.`
    : null

  return {
    items: survivors,
    diagnostics: {
      degenerate,
      reason,
      mode: degenerate ? 'soft_keep_top1' : 'none',
      dedupeStats: {
        before: items.length,
        after: survivors.length,
        collapsedGroups,
      },
    },
    discarded,
  }
}

function dedupeDeepResearchEvidence(items: HypothesisEvidenceItem[]): {
  items: HypothesisEvidenceItem[]
  discarded: DeepResearchDiscardedSource[]
} {
  const sorted = [...items].sort((left, right) => evidenceSortScore(right) - evidenceSortScore(left))
  const kept: Array<{
    item: HypothesisEvidenceItem
    fp: string
    summaryFp: string
    tokens: Set<string>
  }> = []
  const discarded: DeepResearchDiscardedSource[] = []

  for (const item of sorted) {
    const fp = evidenceContentFingerprint(item)
    const summaryFp = summaryFingerprint(item.summary || null)
    const tokens = dedupTokenize(fp)
    const canonicalId = item.canonical_id ?? null
    let duplicate = false

    for (const existing of kept) {
      const existingCanonicalId = existing.item.canonical_id ?? null
      if (canonicalId && existingCanonicalId && canonicalId === existingCanonicalId) {
        duplicate = true
        break
      }
      if (summaryFp && existing.summaryFp && summaryFp === existing.summaryFp) {
        duplicate = true
        break
      }
      if (fp && existing.fp && fp === existing.fp) {
        duplicate = true
        break
      }
      if (!tokens.size || !existing.tokens.size) continue
      if (dedupJaccard(tokens, existing.tokens) >= 0.8) {
        duplicate = true
        break
      }
    }

    if (!duplicate) {
      kept.push({ item, fp, summaryFp, tokens })
    } else {
      const byCanonicalId = canonicalId && kept.some((e) => (e.item.canonical_id ?? null) === canonicalId)
      discarded.push(
        toDiscardedSource({
          item,
          reasonCode: 'duplicate_similarity',
          reasonDetail: byCanonicalId
            ? 'Same paper (PMC/PMID canonical ID); kept one source.'
            : 'Filtered by semantic/content dedupe.',
        }),
      )
    }
  }

  const nonSynthetic = kept.filter((entry) => !isLikelySyntheticEvidence(entry.item))
  const finalEntries = nonSynthetic.length > 0 ? nonSynthetic : kept
  if (nonSynthetic.length > 0) {
    for (const entry of kept) {
      if (!isLikelySyntheticEvidence(entry.item)) continue
      discarded.push(
        toDiscardedSource({
          item: entry.item,
          reasonCode: 'synthetic_summary',
          reasonDetail: 'Removed synthetic/boilerplate summary when non-synthetic sources existed.',
        }),
      )
    }
  }
  return {
    items: finalEntries.map((entry) => entry.item),
    discarded,
  }
}

function selectNetworkResolutionIndexes(args: {
  documents: JsonRecord[]
  resolveEnabled: boolean
  maxDocs: number
}): Set<number> {
  const selected = new Set<number>()
  if (!args.resolveEnabled || args.maxDocs <= 0) return selected

  const unresolvedRedirectCandidates: number[] = []
  const fallbackCandidates: number[] = []

  for (let index = 0; index < args.documents.length; index += 1) {
    const doc = asRecord(args.documents[index]) || {}
    const sourceUrl =
      pickFirstString(doc, ['url', 'uri', 'link', 'href']) ||
      (Array.isArray(doc.urls) && isHttpUrl(doc.urls[0]) ? doc.urls[0] : null)
    if (!sourceUrl) continue
    if (isUnresolvedGroundingRedirect(sourceUrl) || isGroundingRedirectCandidate(sourceUrl)) {
      unresolvedRedirectCandidates.push(index)
    } else {
      fallbackCandidates.push(index)
    }
  }

  for (const index of [...unresolvedRedirectCandidates, ...fallbackCandidates]) {
    if (selected.size >= args.maxDocs) break
    selected.add(index)
  }

  return selected
}

function buildRedirectDiscardDetail(args: {
  skippedByBudget: boolean
  attempted: boolean
  resolver: 'none' | 'query_param' | 'head' | 'get'
  httpStatus: number | null
  error: string | null
}): string {
  if (args.skippedByBudget) {
    return 'Removed unresolved grounding redirect URL (network resolution skipped by budget).'
  }
  if (!args.attempted) {
    return 'Removed unresolved grounding redirect URL (no resolvable target found).'
  }
  if (args.error) {
    if (/abort|timeout/i.test(args.error)) {
      return 'Removed unresolved grounding redirect URL (resolution timed out).'
    }
    return `Removed unresolved grounding redirect URL (resolution error: ${args.error}).`
  }
  if (typeof args.httpStatus === 'number' && Number.isFinite(args.httpStatus)) {
    return `Removed unresolved grounding redirect URL (HTTP ${args.httpStatus}).`
  }
  return 'Removed unresolved grounding redirect URL.'
}

async function normalizeDeepResearchEvidence(args: {
  query: string
  resultPayload: JsonRecord | null
  authHeaders?: Headers
}): Promise<{
  summary: string
  synthesisFullText: string
  synthesisGeneratedBy: DeepResearchSynthesisSource
  synthesisSourceCount: number
  evidence: HypothesisEvidenceItem[]
  diagnostics: DeepResearchDegenerateEvidenceDiagnostics
  report: {
    sourceInventory: DeepResearchReportSource[]
    discardedSources: DeepResearchDiscardedSource[]
    discardedAggregates: DeepResearchDiscardAggregate[]
    searchStats: DeepResearchReportPayload['search_stats']
  }
}> {
  const result = args.resultPayload || {}
  const response = asRecord(result.response)
  const documentsRaw = collectDeepResearchDocuments(result)
  const resolveEvidenceUrls = process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE !== '0'
  const resolveTimeoutMs = Math.max(
    250,
    Math.trunc(
      Number(process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_TIMEOUT_MS) ||
        DEFAULT_EVIDENCE_URL_RESOLVE_TIMEOUT_MS,
    ),
  )
  const resolveMaxDocsEnv = Number(process.env.HYPOTHESIS_EVIDENCE_URL_RESOLVE_MAX_DOCS)
  const resolveMaxDocs = Number.isFinite(resolveMaxDocsEnv)
    ? Math.max(0, Math.trunc(resolveMaxDocsEnv))
    : DEFAULT_EVIDENCE_URL_RESOLVE_MAX_DOCS
  const resolveNetworkIndexes = selectNetworkResolutionIndexes({
    documents: documentsRaw,
    resolveEnabled: resolveEvidenceUrls,
    maxDocs: resolveMaxDocs,
  })
  const runId = Date.now().toString(36)

  const normalizedOutcomes = await Promise.all(
    documentsRaw.map(async (item, index) => {
      const doc = asRecord(item) || {}
      const rawTitle = asString(doc.title) || asString(doc.name) || asString(doc.label)
      const sourceUrl =
        pickFirstString(doc, ['url', 'uri', 'link', 'href']) ||
        (Array.isArray(doc.urls) && isHttpUrl(doc.urls[0]) ? doc.urls[0] : null)
      const unresolvedRedirectCandidate = isUnresolvedGroundingRedirect(sourceUrl)
      const allowNetworkResolve = resolveNetworkIndexes.has(index)
      const normalizedUrl = await normalizeEvidenceUrl({
        url: sourceUrl,
        resolveRedirects: resolveEvidenceUrls,
        allowNetworkResolve,
        skippedByBudget:
          resolveEvidenceUrls && !allowNetworkResolve && unresolvedRedirectCandidate,
        timeoutMs: resolveTimeoutMs,
      })
      const label = buildReadableLabel({
        title: rawTitle,
        url: normalizedUrl.finalUrl || normalizedUrl.url,
        fallbackId: asString(doc.doc_id),
        index,
      })
      const snippets = Array.isArray(doc.snippets)
        ? doc.snippets
            .map((snippet) => asString(snippet))
            .filter((snippet): snippet is string => Boolean(snippet))
        : Array.isArray(doc.highlights)
          ? doc.highlights
              .map((snippet) => asString(snippet))
              .filter((snippet): snippet is string => Boolean(snippet))
          : []
      const publisher = asString(doc.publisher) || asString(doc.site_name) || asString(doc.domain)
      const summaryParts = [snippets[0], publisher].filter((part): part is string => Boolean(part))
      const sourceType = inferSourceType(normalizedUrl.finalUrl || normalizedUrl.url, rawTitle)
      const summaryText =
        normalizeDeepResearchText(summaryParts.join(' - '), 380) ||
        normalizeDeepResearchText(asString(result.summary), 380)
      const syntheticSummary =
        isLikelySyntheticSummaryText(summaryText) ||
        (typeof doc.synthetic_summary === 'boolean' && doc.synthetic_summary)
      const quality = inferEvidenceQuality({
        url: normalizedUrl.finalUrl || normalizedUrl.url,
        title: rawTitle,
        kind: sourceType === 'dataset' ? 'dataset' : 'paper',
        sourceType,
      })
      const qualityTier = syntheticSummary ? 'tertiary' : quality.tier
      const traceabilityScore = syntheticSummary
        ? Math.min(quality.traceabilityScore, 0.35)
        : quality.traceabilityScore
      const normalizedItem = {
        id: asString(doc.doc_id) || `ev-${runId}-${index + 1}`,
        label,
        kind:
          sourceType === 'dataset'
            ? 'dataset'
            : classifyEvidenceKind(doc, normalizedUrl.url),
        summary: summaryText,
        synthetic_summary: syntheticSummary,
        url: normalizedUrl.finalUrl || normalizedUrl.url,
        raw_url: normalizedUrl.rawUrl,
        display_url: normalizedUrl.displayUrl,
        source_host: normalizedUrl.sourceHost,
        source_type: sourceType,
        quality_tier: qualityTier,
        traceability_score: traceabilityScore,
      } satisfies HypothesisEvidenceItem

      if (isUnresolvedGroundingRedirect(normalizedUrl.finalUrl || normalizedUrl.url)) {
        return {
          item: null,
          validationTitle: rawTitle,
          discarded: toDiscardedSource({
            item: normalizedItem,
            reasonCode: 'redirect_unresolved',
            reasonDetail: buildRedirectDiscardDetail({
              skippedByBudget: normalizedUrl.resolution.skippedByBudget,
              attempted: normalizedUrl.resolution.attempted,
              resolver: normalizedUrl.resolution.resolvedVia,
              httpStatus: normalizedUrl.resolution.httpStatus,
              error: normalizedUrl.resolution.error,
            }),
            reasonMeta: {
              attempted: normalizedUrl.resolution.attempted,
              resolver: normalizedUrl.resolution.resolvedVia,
              http_status: normalizedUrl.resolution.httpStatus,
              error: normalizedUrl.resolution.error,
              skipped_by_budget: normalizedUrl.resolution.skippedByBudget,
            },
          }),
        }
      }

      if (!normalizedItem.url && !normalizedItem.label.trim()) {
        return {
          item: null,
          validationTitle: rawTitle,
          discarded: toDiscardedSource({
            item: normalizedItem,
            reasonCode: 'missing_url_or_label',
            reasonDetail: 'Source lacked both URL and readable label.',
          }),
        }
      }

      return {
        item: normalizedItem,
        validationTitle: rawTitle,
        discarded: null,
      }
    }),
  )

  const normalizedCandidates: EvidenceCandidateWithTitle[] = []
  const initialDiscarded: DeepResearchDiscardedSource[] = []
  for (const outcome of normalizedOutcomes) {
    if (outcome.item) {
      normalizedCandidates.push({
        item: outcome.item,
        validationTitle: outcome.validationTitle,
      })
    }
    if (outcome.discarded) initialDiscarded.push(outcome.discarded)
  }

  const validatedItems = await validateEvidencePaperLinks(normalizedCandidates)
  const enrichedItems = await enrichEvidenceWithAbstracts(validatedItems)
  const withCanonicalIds = await enrichEvidenceWithCanonicalIds(enrichedItems)
  const sourceInventory = withCanonicalIds.map(toDeepResearchReportSource)
  const degeneratePolicy = applyDegenerateEvidencePolicy(withCanonicalIds)
  const deduped = dedupeDeepResearchEvidence(degeneratePolicy.items)
  const topNTrimmed = deduped.items.slice(10).map((item) =>
    toDiscardedSource({
      item,
      reasonCode: 'top_n_trim',
      reasonDetail: 'Removed by top-N cap.',
    }),
  )
  const evidence = deduped.items.slice(0, 10)
  const discardedSources = dedupeDiscardedSources([
    ...initialDiscarded,
    ...degeneratePolicy.discarded,
    ...deduped.discarded,
    ...topNTrimmed,
  ])

  const upstreamSummary =
    normalizeDeepResearchText(asString(result.summary), 380) ||
    normalizeDeepResearchText(asString(result.text), 380) ||
    normalizeDeepResearchText(asString(result.output_text), 380) ||
    normalizeDeepResearchText(asString(response?.text), 380)
  const upstreamSynthesis =
    normalizeDeepResearchText(
      asString(result.synthesis_full_text ?? result.synthesisFullText),
      20_000,
    ) ||
    normalizeDeepResearchText(asString(result.text), 20_000) ||
    normalizeDeepResearchText(asString(result.output_text), 20_000) ||
    normalizeDeepResearchText(asString(response?.text), 20_000) ||
    normalizeDeepResearchText(asString(result.summary), 20_000)

  let synthesisGeneratedBy: DeepResearchSynthesisSource = 'upstream'
  let synthesisFullText = upstreamSynthesis

  if (!isSynthesisInformative(synthesisFullText)) {
    const llmSynthesis = await tryGenerateLlmSynthesis({
      query: args.query,
      sourceInventory,
      authHeaders: args.authHeaders,
    })
    if (llmSynthesis) {
      synthesisFullText = llmSynthesis
      synthesisGeneratedBy = 'llm_fallback'
    } else {
      synthesisFullText = buildRuleBasedSynthesis({
        query: args.query,
        sourceInventory,
        summary: upstreamSummary || DEFAULT_SYNTHESIS_SUMMARY_FALLBACK,
      })
      synthesisGeneratedBy = 'fallback_rule'
    }
  }

  const summary =
    upstreamSummary ||
    normalizeDeepResearchText(synthesisFullText, 380) ||
    DEFAULT_SYNTHESIS_SUMMARY_FALLBACK
  const discardedAggregates = buildDiscardedAggregates(discardedSources)
  const synthesisSourceCount = sourceInventory.filter(
    (source) => Boolean(source.summary || source.display_title || source.label),
  ).length

  return {
    summary,
    synthesisFullText,
    synthesisGeneratedBy,
    synthesisSourceCount,
    evidence,
    diagnostics: {
      ...degeneratePolicy.diagnostics,
      dedupeStats: {
        before: validatedItems.length,
        after: evidence.length,
        collapsedGroups: degeneratePolicy.diagnostics.dedupeStats.collapsedGroups,
      },
    },
    report: {
      sourceInventory,
      discardedSources,
      discardedAggregates,
      searchStats: {
        scanned_count: documentsRaw.length,
        qualifying_count: sourceInventory.length,
        unique_after_dedupe_count: deduped.items.length,
        final_citable_count: evidence.length,
        discarded_count: discardedSources.length,
      },
    },
  }
}

function parseDeepResearchState(payload: JsonRecord | null): {
  state: string
  runId: string | null
  interactionId: string | null
  idempotencyKey: string | null
  resultPayload: JsonRecord | null
  errorMessage: string | null
} {
  const source = payload || {}
  const data = asRecord(source.data)
  const nestedData = asRecord(data?.data)
  const result = asRecord(source.result)
  const outputs =
    asRecord(source.outputs) ||
    asRecord(data?.outputs) ||
    asRecord(nestedData?.outputs) ||
    asRecord(result?.outputs)
  const response = asRecord(source.response) || asRecord(data?.response) || asRecord(outputs?.response)
  const run = asRecord(source.run) || asRecord(data?.run) || asRecord(nestedData?.run)
  const hasInlineText =
    Boolean(asString(outputs?.text)) ||
    Boolean(asString(source.text)) ||
    Boolean(asString(data?.text)) ||
    Boolean(asString(response?.text))
  const fallbackState = source.ok === true && hasInlineText ? 'ok' : 'running'

  const state =
    asString(outputs?.status)?.toLowerCase() ||
    asString(source.status)?.toLowerCase() ||
    asString(source.state)?.toLowerCase() ||
    asString(data?.status)?.toLowerCase() ||
    asString(data?.state)?.toLowerCase() ||
    asString(nestedData?.status)?.toLowerCase() ||
    asString(nestedData?.state)?.toLowerCase() ||
    asString(result?.status)?.toLowerCase() ||
    fallbackState

  const resultPayload =
    asRecord(outputs?.result) ||
    asRecord(data?.result) ||
    asRecord(nestedData?.result) ||
    asRecord(result?.result) ||
    asRecord(source.result) ||
    asRecord(response ? { response } : null) ||
    asRecord(outputs?.documents ? outputs : null) ||
    asRecord(source.documents ? source : null) ||
    asRecord(data?.documents ? data : null) ||
    (() => {
      const text =
        asString(outputs?.text) ||
        asString(source.text) ||
        asString(data?.text) ||
        asString(response?.text)
      if (!text) return null
      return { text } satisfies JsonRecord
    })()

  const errorMessage =
    asString(outputs?.error) ||
    asString(source.error) ||
    asString(source.message) ||
    asString(data?.error) ||
    asString(data?.message) ||
    asString(nestedData?.error) ||
    asString(nestedData?.message) ||
    asString(result?.error) ||
    asString(result?.message) ||
    asString(response?.error) ||
    ((source.ok === false || data?.ok === false || nestedData?.ok === false)
      ? 'Deep research request failed.'
      : null)

  return {
    state,
    runId: asString(
      outputs?.run_id ??
        outputs?.runId ??
        source.run_id ??
        source.runId ??
        run?.run_id ??
        run?.runId ??
        data?.run_id ??
        data?.runId ??
        nestedData?.run_id ??
        nestedData?.runId,
    ),
    interactionId: asString(
      outputs?.interaction_id ??
        outputs?.interactionId ??
        source.interaction_id ??
        source.interactionId ??
        data?.interaction_id ??
        data?.interactionId ??
        nestedData?.interaction_id ??
        nestedData?.interactionId,
    ),
    idempotencyKey: asString(
      outputs?.idempotency_key ??
        outputs?.idempotencyKey ??
        source.idempotency_key ??
        source.idempotencyKey ??
        data?.idempotency_key ??
        data?.idempotencyKey ??
        nestedData?.idempotency_key ??
        nestedData?.idempotencyKey,
    ),
    resultPayload,
    errorMessage,
  }
}

function buildDeepResearchStartArgs(args: {
  query: string
  fileSearchStoreNames: string[]
}): Record<string, unknown> {
  return {
    input: args.query,
    query: args.query,
    file_search_store_names: args.fileSearchStoreNames,
  }
}

function buildDeepResearchPollRequest(args: {
  runId: string | null
  interactionId: string | null
}): { tool: string; arguments: Record<string, unknown> } | null {
  if (args.runId) {
    return {
      tool: GOOGLE_DEEP_RESEARCH_POLL_TOOL,
      arguments: {
        run_id: args.runId,
      },
    }
  }
  if (args.interactionId) {
    return {
      tool: GOOGLE_DEEP_RESEARCH_COMPAT_GET_TOOL,
      arguments: {
        interaction_id: args.interactionId,
      },
    }
  }
  return null
}

function buildDeepResearchSyncArgs(args: {
  query: string
  recencyDays?: number | null
  excludeDomains: string[]
}): Record<string, unknown> {
  return {
    query: args.query,
    recency_days: args.recencyDays,
    exclude_domains: args.excludeDomains,
  }
}

function normalizeSearchTrail(raw: unknown): DeepResearchSearchTrail | null {
  const record = asRecord(raw)
  if (!record) return null
  const tool = asString(record.tool)
  if (!tool) return null
  return {
    stage: ((() => {
      const stage = asString(record.stage)?.toLowerCase()
      return stage === 'start' || stage === 'sync_fallback' || stage === 'poll'
        ? stage
        : 'poll'
    })() as DeepResearchSearchTrail['stage']),
    tool,
    status: asString(record.status) || 'unknown',
    detail: asString(record.detail),
    ts: asString(record.ts),
  }
}

function extractSearchTrailsFromPayload(resultPayload: JsonRecord | null): DeepResearchSearchTrail[] {
  if (!resultPayload) return []
  const raw =
    (Array.isArray(resultPayload.search_trails) ? resultPayload.search_trails : null) ||
    (Array.isArray(resultPayload.searchTrails) ? resultPayload.searchTrails : null) ||
    []
  return raw
    .map((item) => normalizeSearchTrail(item))
    .filter((item): item is DeepResearchSearchTrail => Boolean(item))
}

function mergeSearchTrails(
  historical: DeepResearchSearchTrail[],
  current: DeepResearchSearchTrail[],
): DeepResearchSearchTrail[] {
  const merged: DeepResearchSearchTrail[] = []
  const seen = new Set<string>()
  for (const entry of [...historical, ...current]) {
    const key = [
      entry.stage,
      entry.tool,
      entry.status,
      entry.detail || '',
      entry.ts || '',
    ].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(entry)
  }
  if (merged.length > 40) {
    return merged.slice(merged.length - 40)
  }
  return merged
}

function appendSearchTrail(
  trails: DeepResearchSearchTrail[],
  entry: DeepResearchSearchTrail,
): void {
  trails.push(entry)
  if (trails.length > 40) {
    trails.splice(0, trails.length - 40)
  }
}

function buildDeepResearchReport(args: {
  query: string
  status: string
  sourceRunId: string | null
  interactionId: string | null
  idempotencyKey: string | null
  summary: string
  synthesisFullText: string
  claimReview: DeepResearchClaimReview | null
  synthesisGeneratedBy: DeepResearchSynthesisSource
  synthesisSourceCount: number
  sourceInventory: DeepResearchReportSource[]
  discardedSources: DeepResearchDiscardedSource[]
  discardedAggregates: DeepResearchDiscardAggregate[]
  qualityGate: DeepResearchQualityGate
  fallbackPath: DeepResearchFallbackPath
  searchStats: DeepResearchReportPayload['search_stats']
  searchTrails: DeepResearchSearchTrail[]
  historicalTrailsAvailable: boolean
}): DeepResearchReportPayload {
  const calibratedSummary = args.claimReview
    ? buildClaimReviewSummary(args.claimReview)
    : buildWithheldClaimReviewSummary(args.sourceRunId)
  const calibratedSynthesis = args.claimReview
    ? args.claimReview.rendered_markdown
    : buildWithheldClaimReviewMarkdown(args.sourceRunId)

  return {
    query: args.query,
    status: args.status,
    source_run_id: args.sourceRunId,
    interaction_id: args.interactionId,
    idempotency_key: args.idempotencyKey,
    summary: calibratedSummary,
    synthesis_full_text: calibratedSynthesis,
    raw_summary: args.summary,
    raw_synthesis_full_text: args.synthesisFullText,
    claim_review: args.claimReview,
    synthesis_generated_by: args.synthesisGeneratedBy,
    synthesis_source_count: args.synthesisSourceCount,
    search_trails: [...args.searchTrails],
    historical_trails_available: args.historicalTrailsAvailable,
    source_inventory: [...args.sourceInventory],
    discarded_sources: [...args.discardedSources],
    discarded_aggregates: [...args.discardedAggregates],
    quality_gate: { ...args.qualityGate },
    fallback_path: args.fallbackPath,
    search_stats: { ...args.searchStats },
    generated_at: new Date().toISOString(),
  }
}

function resolveQualityGateThresholds(options?: DeepResearchRuntimeOptions): {
  minCitableSources: number
  minPrimarySources: number
} {
  const minCitableSources = normalizeNonNegativeInt(
    options?.minCitableSources ??
      Number(process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_CITABLE_SOURCES),
    DEFAULT_MIN_CITABLE_SOURCES,
  )
  const minPrimarySources = normalizeNonNegativeInt(
    options?.minPrimarySources ??
      Number(process.env.HYPOTHESIS_DEEP_RESEARCH_MIN_PRIMARY_SOURCES),
    DEFAULT_MIN_PRIMARY_SOURCES,
  )
  return { minCitableSources, minPrimarySources }
}

function evaluateDeepResearchQualityGate(args: {
  evidence: HypothesisEvidenceItem[]
  thresholds: { minCitableSources: number; minPrimarySources: number }
}): DeepResearchQualityGate {
  const citableCount = args.evidence.filter((item) => Boolean(item.url || item.display_url)).length
  const primaryCount = args.evidence.filter((item) => item.quality_tier === 'primary').length
  const pass =
    citableCount >= args.thresholds.minCitableSources &&
    primaryCount >= args.thresholds.minPrimarySources

  let reason: string | null = null
  if (!pass) {
    reason = `Evidence gate unmet: citable ${citableCount}/${args.thresholds.minCitableSources}, primary ${primaryCount}/${args.thresholds.minPrimarySources}.`
  }

  return {
    min_citable_sources: args.thresholds.minCitableSources,
    min_primary_sources: args.thresholds.minPrimarySources,
    citable_count: citableCount,
    primary_count: primaryCount,
    pass,
    low_confidence: !pass,
    reason,
  }
}

function deepResearchResultScore(result: DeepResearchRuntimeResult): [number, number, number] {
  const primary = result.qualityGate.primary_count
  const citable = result.qualityGate.citable_count
  const traceability = Number(
    result.evidence.reduce((acc, item) => acc + (item.traceability_score || 0), 0).toFixed(4),
  )
  return [primary, citable, traceability]
}

function selectPreferredDeepResearchResult(
  currentResult: DeepResearchRuntimeResult,
  fallbackResult: DeepResearchRuntimeResult,
): DeepResearchRuntimeResult {
  const [currentPrimary, currentCitable, currentTraceability] = deepResearchResultScore(currentResult)
  const [fallbackPrimary, fallbackCitable, fallbackTraceability] =
    deepResearchResultScore(fallbackResult)
  if (fallbackPrimary > currentPrimary) return fallbackResult
  if (fallbackPrimary < currentPrimary) return currentResult
  if (fallbackCitable > currentCitable) return fallbackResult
  if (fallbackCitable < currentCitable) return currentResult
  if (fallbackTraceability > currentTraceability) return fallbackResult
  return currentResult
}

function resolveDeepResearchRetryConfig(options?: DeepResearchRuntimeOptions): DeepResearchRetryConfig {
  const transientRetries = normalizeNonNegativeInt(
    options?.transientRetries ??
      Number(process.env.HYPOTHESIS_DEEP_RESEARCH_TRANSIENT_RETRIES),
    DEFAULT_TRANSIENT_TOOL_RETRIES,
  )
  const retryBaseMs = normalizePositiveInt(
    options?.retryBaseMs ?? Number(process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_BASE_MS),
    DEFAULT_TRANSIENT_RETRY_BASE_MS,
  )
  const retryMaxMs = normalizePositiveInt(
    options?.retryMaxMs ?? Number(process.env.HYPOTHESIS_DEEP_RESEARCH_RETRY_MAX_MS),
    DEFAULT_TRANSIENT_RETRY_MAX_MS,
  )

  return {
    transientRetries,
    retryBaseMs,
    retryMaxMs: Math.max(retryBaseMs, retryMaxMs),
  }
}

function computeRetryBackoffMs(attempt: number, config: DeepResearchRetryConfig): number {
  const exponent = Math.max(0, attempt - 1)
  const nextDelay = config.retryBaseMs * 2 ** exponent
  return Math.max(1, Math.min(config.retryMaxMs, Math.trunc(nextDelay)))
}

function throwIfTerminalDeepResearchFailure(parsed: {
  state: string
  errorMessage: string | null
}): void {
  if (!TERMINAL_DEEP_RESEARCH_FAILURE_STATES.has(parsed.state)) {
    return
  }
  throw createDeepResearchError({
    code: DEEP_RESEARCH_ERROR_CODES.TERMINAL_FAILURE_STATE,
    message:
      parsed.errorMessage || `Deep research entered terminal failure state "${parsed.state}".`,
  })
}

function throwIfDeepResearchResponseError(parsed: {
  state: string
  errorMessage: string | null
}): void {
  throwIfTerminalDeepResearchFailure(parsed)
  if (!parsed.errorMessage) {
    return
  }
  throw createDeepResearchError({
    code: DEEP_RESEARCH_ERROR_CODES.REQUEST_FAILED,
    message: parsed.errorMessage,
  })
}

async function runDeepResearchToolWithRetry(args: {
  tool: string
  arguments: Record<string, unknown>
  authHeaders?: Headers
  retryConfig: DeepResearchRetryConfig
  onRetry?: (attempt: number, maxAttempts: number, delayMs: number) => void
}): Promise<ToolRunResponse> {
  const maxAttempts = Math.max(1, args.retryConfig.transientRetries + 1)

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await runAgentTool({
        tool: args.tool,
        authHeaders: args.authHeaders,
        arguments: args.arguments,
      })
    } catch (error) {
      if (!isTransientToolCallFailure(error) || attempt >= maxAttempts) {
        throw error
      }
      const delayMs = computeRetryBackoffMs(attempt, args.retryConfig)
      args.onRetry?.(attempt, maxAttempts, delayMs)
      await sleep(delayMs)
    }
  }

  throw createDeepResearchError({
    code: DEEP_RESEARCH_ERROR_CODES.TRANSIENT_TOOL_FAILURE,
    message: 'Deep research tool call retries exhausted.',
    retryable: true,
  })
}

async function runSyncFallback(args: {
  query: string
  recencyDays?: number | null
  excludeDomains: string[]
  authHeaders?: Headers
  retryConfig: DeepResearchRetryConfig
  qualityThresholds: { minCitableSources: number; minPrimarySources: number }
  fallbackPath: DeepResearchFallbackPath
  searchTrails?: DeepResearchSearchTrail[]
  onRetry?: (attempt: number, maxAttempts: number, delayMs: number) => void
}): Promise<DeepResearchRuntimeResult> {
  const sync = await runDeepResearchToolWithRetry({
    tool: GOOGLE_DEEP_RESEARCH_SYNC_TOOL,
    authHeaders: args.authHeaders,
    retryConfig: args.retryConfig,
    onRetry: args.onRetry,
    arguments: buildDeepResearchSyncArgs(args),
  })

  const parsed = parseDeepResearchState(sync.payload)
  throwIfDeepResearchResponseError(parsed)

  const normalized = await normalizeDeepResearchEvidence({
    query: args.query,
    resultPayload: parsed.resultPayload,
    authHeaders: args.authHeaders,
  })
  const qualityGate = evaluateDeepResearchQualityGate({
    evidence: normalized.evidence,
    thresholds: args.qualityThresholds,
  })
  const payloadTrails = extractSearchTrailsFromPayload(parsed.resultPayload)
  const searchTrails = mergeSearchTrails(payloadTrails, [...(args.searchTrails || [])])
  const historicalTrailsAvailable = parsed.state !== 'cached' || payloadTrails.length > 0
  const claimReview = await loadCalibratedClaimReview({
    runId: parsed.runId,
    authHeaders: args.authHeaders,
  })
  appendSearchTrail(searchTrails, {
    stage: 'sync_fallback',
    tool: GOOGLE_DEEP_RESEARCH_SYNC_TOOL,
    status: parsed.state || 'completed',
    detail: 'Synchronous fallback execution.',
  })
  if (!historicalTrailsAvailable && parsed.state === 'cached') {
    appendSearchTrail(searchTrails, {
      stage: 'sync_fallback',
      tool: GOOGLE_DEEP_RESEARCH_SYNC_TOOL,
      status: 'cached',
      detail: 'Cache hit; historical trails unavailable for this artifact version.',
    })
  }
  const normalizedStatus = qualityGate.pass ? parsed.state : 'partial'
  return {
    status: normalizedStatus,
    interactionId: parsed.interactionId,
    idempotencyKey: parsed.idempotencyKey,
    summary: normalized.summary,
    evidence: normalized.evidence,
    degenerateEvidence: normalized.diagnostics,
    qualityGate,
    fallbackPath: args.fallbackPath,
    report: buildDeepResearchReport({
      query: args.query,
      status: normalizedStatus,
      sourceRunId: parsed.runId,
      interactionId: parsed.interactionId,
      idempotencyKey: parsed.idempotencyKey,
      summary: normalized.summary,
      synthesisFullText: normalized.synthesisFullText,
      claimReview,
      synthesisGeneratedBy: normalized.synthesisGeneratedBy,
      synthesisSourceCount: normalized.synthesisSourceCount,
      sourceInventory: normalized.report.sourceInventory,
      discardedSources: normalized.report.discardedSources,
      discardedAggregates: normalized.report.discardedAggregates,
      qualityGate,
      fallbackPath: args.fallbackPath,
      searchStats: normalized.report.searchStats,
      searchTrails,
      historicalTrailsAvailable,
    }),
  }
}

export type DeepResearchRuntimeOptions = {
  recencyDays?: number | null
  excludeDomains?: string[]
  fileSearchStoreNames?: string[]
  language?: string
  pollIntervalMs?: number
  maxPolls?: number
  startGracePolls?: number
  uiWaitSec?: number
  backgroundCapSec?: number
  transientRetries?: number
  retryBaseMs?: number
  retryMaxMs?: number
  minCitableSources?: number
  minPrimarySources?: number
}

export type DeepResearchRuntimeResult = {
  status: string
  interactionId: string | null
  idempotencyKey: string | null
  summary: string
  evidence: HypothesisEvidenceItem[]
  degenerateEvidence: DeepResearchDegenerateEvidenceDiagnostics
  qualityGate: DeepResearchQualityGate
  fallbackPath: DeepResearchFallbackPath
  report?: DeepResearchReportPayload | null
}

export async function runDeepResearch(args: {
  query: string
  authHeaders?: Headers
  options?: DeepResearchRuntimeOptions
  onProgress?: (message: string, progress?: number) => void
}): Promise<DeepResearchRuntimeResult> {
  const query = asString(args.query)
  if (!query) {
    throw createDeepResearchError({
      code: DEEP_RESEARCH_ERROR_CODES.EMPTY_QUERY,
      message: 'Deep research query is empty.',
    })
  }

  const recencyDays = args.options?.recencyDays
  const excludeDomains = args.options?.excludeDomains || []
  const fileSearchStoreNames = args.options?.fileSearchStoreNames || []
  const language = asString(args.options?.language) || 'en'
  const pollIntervalMs = Math.max(1, Math.trunc(args.options?.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS))
  const maxPolls = Math.max(0, Math.trunc(args.options?.maxPolls ?? DEFAULT_MAX_POLLS))
  const unlimitedPolls = maxPolls === 0
  const startGracePolls = Math.max(
    0,
    Math.trunc(args.options?.startGracePolls ?? DEFAULT_START_GRACE_POLLS),
  )
  const backgroundCapSec = Math.max(
    1,
    Math.trunc(args.options?.backgroundCapSec ?? DEFAULT_BACKGROUND_CAP_SEC),
  )
  const retryConfig = resolveDeepResearchRetryConfig(args.options)
  const qualityThresholds = resolveQualityGateThresholds(args.options)
  const startedAt = Date.now()
  const searchTrails: DeepResearchSearchTrail[] = []
  let syncFallbackAttempted = false

  const emitRetryProgress =
    (scope: string, progress: number) => (attempt: number, maxAttempts: number, delayMs: number) => {
      const retryBudget = Math.max(1, maxAttempts - 1)
      args.onProgress?.(
        `${scope} transient failure; retrying in ${delayMs}ms (retry ${attempt}/${retryBudget})...`,
        Number(progress.toFixed(3)),
      )
    }

  const finalizeFromNormalized = async (params: {
    parsedState: string
    sourceRunId: string | null
    interactionId: string | null
    idempotencyKey: string | null
    normalized: Awaited<ReturnType<typeof normalizeDeepResearchEvidence>>
    mergedTrails: DeepResearchSearchTrail[]
    historicalTrailsAvailable: boolean
    fallbackPath?: DeepResearchFallbackPath
  }): Promise<DeepResearchRuntimeResult> => {
    const qualityGate = evaluateDeepResearchQualityGate({
      evidence: params.normalized.evidence,
      thresholds: qualityThresholds,
    })
    const status = qualityGate.pass ? params.parsedState : 'partial'
    const fallbackPath = params.fallbackPath || 'none'
    const claimReview = await loadCalibratedClaimReview({
      runId: params.sourceRunId,
      authHeaders: args.authHeaders,
    })
    return {
      status,
      interactionId: params.interactionId,
      idempotencyKey: params.idempotencyKey,
      summary: params.normalized.summary,
      evidence: params.normalized.evidence,
      degenerateEvidence: params.normalized.diagnostics,
      qualityGate,
      fallbackPath,
      report: buildDeepResearchReport({
        query,
        status,
        sourceRunId: params.sourceRunId,
        interactionId: params.interactionId,
        idempotencyKey: params.idempotencyKey,
        summary: params.normalized.summary,
        synthesisFullText: params.normalized.synthesisFullText,
        claimReview,
        synthesisGeneratedBy: params.normalized.synthesisGeneratedBy,
        synthesisSourceCount: params.normalized.synthesisSourceCount,
        sourceInventory: params.normalized.report.sourceInventory,
        discardedSources: params.normalized.report.discardedSources,
        discardedAggregates: params.normalized.report.discardedAggregates,
        qualityGate,
        fallbackPath,
        searchStats: params.normalized.report.searchStats,
        searchTrails: params.mergedTrails,
        historicalTrailsAvailable: params.historicalTrailsAvailable,
      }),
    }
  }

  const withFallbackPath = (
    result: DeepResearchRuntimeResult,
    fallbackPath: Exclude<DeepResearchFallbackPath, 'none'>,
  ): DeepResearchRuntimeResult => ({
    ...result,
    fallbackPath,
    report: result.report
      ? {
          ...result.report,
          fallback_path: fallbackPath,
        }
      : result.report,
  })

  const attemptSyncFallback = async (
    fallbackPath: Exclude<DeepResearchFallbackPath, 'none'>,
    progress: number,
  ): Promise<DeepResearchRuntimeResult> => {
    if (syncFallbackAttempted) {
      throw createDeepResearchError({
        code: DEEP_RESEARCH_ERROR_CODES.REQUEST_FAILED,
        message: 'Deep research sync fallback already attempted.',
      })
    }
    syncFallbackAttempted = true
    return runSyncFallback({
      query,
      recencyDays,
      excludeDomains,
      authHeaders: args.authHeaders,
      retryConfig,
      qualityThresholds,
      fallbackPath,
      searchTrails,
      onRetry: emitRetryProgress('Deep research sync fallback', progress),
    })
  }

  try {
    args.onProgress?.('Starting Google Deep Research...', 0.24)
    const start = await runDeepResearchToolWithRetry({
      tool: GOOGLE_DEEP_RESEARCH_START_TOOL,
      authHeaders: args.authHeaders,
      retryConfig,
      onRetry: emitRetryProgress('Google deep research start', 0.28),
      arguments: buildDeepResearchStartArgs({
        query,
        fileSearchStoreNames,
      }),
    })

    let parsed = parseDeepResearchState(start.payload)
    let runId = parsed.runId
    let interactionId = parsed.interactionId
    let idempotencyKey = parsed.idempotencyKey
    if (TERMINAL_DEEP_RESEARCH_FAILURE_STATES.has(parsed.state)) {
      args.onProgress?.(
        `Deep research entered terminal state "${parsed.state}"; retrying via sync fallback...`,
        0.3,
      )
      return await attemptSyncFallback('sync_after_terminal_failure', 0.3)
    }
    throwIfDeepResearchResponseError(parsed)
    appendSearchTrail(searchTrails, {
      stage: 'start',
      tool: GOOGLE_DEEP_RESEARCH_START_TOOL,
      status: parsed.state || 'running',
      detail: 'Google interactions start',
    })

    if (TERMINAL_DEEP_RESEARCH_STATES.has(parsed.state) && parsed.resultPayload) {
      const normalized = await normalizeDeepResearchEvidence({
        query,
        resultPayload: parsed.resultPayload,
        authHeaders: args.authHeaders,
      })
      const payloadTrails = extractSearchTrailsFromPayload(parsed.resultPayload)
      const mergedTrails = mergeSearchTrails(payloadTrails, searchTrails)
      const historicalTrailsAvailable = parsed.state !== 'cached' || payloadTrails.length > 0
      if (!historicalTrailsAvailable && parsed.state === 'cached') {
        appendSearchTrail(mergedTrails, {
          stage: 'poll',
          tool: GOOGLE_DEEP_RESEARCH_POLL_TOOL,
          status: 'cached',
          detail: 'Cache hit; historical trails unavailable for this artifact version.',
        })
      }
      const currentResult = await finalizeFromNormalized({
        parsedState: parsed.state,
        sourceRunId: runId,
        interactionId,
        idempotencyKey,
        normalized,
        mergedTrails,
        historicalTrailsAvailable,
      })
      if (!currentResult.qualityGate.pass) {
        args.onProgress?.(
          'Deep research completed but evidence gate was not met; retrying via sync fallback...',
          0.32,
        )
        try {
          const fallbackResult = await attemptSyncFallback('sync_after_quality_gate', 0.32)
          return selectPreferredDeepResearchResult(
            withFallbackPath(currentResult, 'sync_after_quality_gate'),
            fallbackResult,
          )
        } catch {
          return withFallbackPath(currentResult, 'sync_after_quality_gate')
        }
      }
      return currentResult
    }

    let progress = 0.3
    let pollAttempts = 0
    let missingIdentifiersAttempts = 0

    while (true) {
      const elapsedSec = Math.floor((Date.now() - startedAt) / 1000)
      if (elapsedSec >= backgroundCapSec) {
        throw createDeepResearchError({
          code: DEEP_RESEARCH_ERROR_CODES.BACKGROUND_CAP_EXCEEDED,
          message: `Deep research exceeded background cap (${backgroundCapSec}s). Increase deep_research_background_cap_sec if longer runtime is expected.`,
        })
      }

      if (!runId && !parsed.interactionId) {
        if (missingIdentifiersAttempts >= startGracePolls) {
          args.onProgress?.(
            'Deep research did not return polling identifiers; falling back to sync mode...',
            Number(progress.toFixed(3)),
          )
          try {
            return await attemptSyncFallback('sync_after_missing_ids', progress)
          } catch (error) {
            throw createDeepResearchError({
              code: DEEP_RESEARCH_ERROR_CODES.MISSING_INTERACTION_ID,
              message: `Deep research did not return interaction identifiers and sync fallback failed: ${extractErrorMessage(
                error,
              )}`,
              cause: error,
            })
          }
        }

        missingIdentifiersAttempts += 1
        await sleep(pollIntervalMs)

        const retryStart = await runDeepResearchToolWithRetry({
          tool: GOOGLE_DEEP_RESEARCH_START_TOOL,
          authHeaders: args.authHeaders,
          retryConfig,
          onRetry: emitRetryProgress('Deep research identifier refresh', progress),
          arguments: buildDeepResearchStartArgs({
            query,
            fileSearchStoreNames,
          }),
        })
        parsed = parseDeepResearchState(retryStart.payload)
        if (parsed.runId) runId = parsed.runId
        if (parsed.interactionId) interactionId = parsed.interactionId
        if (parsed.idempotencyKey) idempotencyKey = parsed.idempotencyKey
        if (TERMINAL_DEEP_RESEARCH_FAILURE_STATES.has(parsed.state)) {
          args.onProgress?.(
            `Deep research entered terminal state "${parsed.state}"; retrying via sync fallback...`,
            Number(progress.toFixed(3)),
          )
          return await attemptSyncFallback('sync_after_terminal_failure', progress)
        }
        throwIfDeepResearchResponseError(parsed)
        appendSearchTrail(searchTrails, {
          stage: 'start',
          tool: GOOGLE_DEEP_RESEARCH_START_TOOL,
          status: parsed.state || 'running',
          detail: 'Identifier refresh',
        })
        continue
      }

      if (!unlimitedPolls && pollAttempts >= maxPolls) {
        throw createDeepResearchError({
          code: DEEP_RESEARCH_ERROR_CODES.MAX_POLLS_EXCEEDED,
          message: `Deep research did not complete after max attempts (${maxPolls}). Set deep_research_max_polls=0 for unlimited polling.`,
        })
      }

      pollAttempts += 1
      await sleep(pollIntervalMs)

      progress = Math.min(0.74, progress + 0.015)
      args.onProgress?.(
        `Deep research running (${parsed.state || 'pending'})...`,
        Number(progress.toFixed(3)),
      )

      const pollRequest = buildDeepResearchPollRequest({
        runId,
        interactionId: parsed.interactionId,
      })
      if (!pollRequest) {
        throw createDeepResearchError({
          code: DEEP_RESEARCH_ERROR_CODES.MISSING_INTERACTION_ID,
          message: 'Deep research did not return polling identifiers.',
        })
      }

      let poll: ToolRunResponse
      try {
        poll = await runDeepResearchToolWithRetry({
          tool: pollRequest.tool,
          authHeaders: args.authHeaders,
          retryConfig,
          onRetry: emitRetryProgress('Deep research poll', progress),
          arguments: pollRequest.arguments,
        })
      } catch (error) {
        if (isRecoverableDeepResearchError(error)) {
          args.onProgress?.(
            'Deep research poll failed; retrying via sync fallback...',
            Number(progress.toFixed(3)),
          )
          return attemptSyncFallback('sync_after_recoverable_poll_error', progress)
        }
        throw error
      }

      parsed = parseDeepResearchState(poll.payload)
      if (parsed.runId) runId = parsed.runId
      if (parsed.interactionId) interactionId = parsed.interactionId
      if (parsed.idempotencyKey) idempotencyKey = parsed.idempotencyKey
      if (TERMINAL_DEEP_RESEARCH_FAILURE_STATES.has(parsed.state)) {
        args.onProgress?.(
          `Deep research entered terminal state "${parsed.state}"; retrying via sync fallback...`,
          Number(progress.toFixed(3)),
        )
        return await attemptSyncFallback('sync_after_terminal_failure', progress)
      }
      throwIfDeepResearchResponseError(parsed)
      appendSearchTrail(searchTrails, {
        stage: 'poll',
        tool: pollRequest.tool,
        status: parsed.state || 'running',
        detail: null,
      })

      if (TERMINAL_DEEP_RESEARCH_STATES.has(parsed.state) && parsed.resultPayload) {
        const normalized = await normalizeDeepResearchEvidence({
          query,
          resultPayload: parsed.resultPayload,
          authHeaders: args.authHeaders,
        })
        const payloadTrails = extractSearchTrailsFromPayload(parsed.resultPayload)
        const mergedTrails = mergeSearchTrails(payloadTrails, searchTrails)
        const historicalTrailsAvailable = parsed.state !== 'cached' || payloadTrails.length > 0
        if (!historicalTrailsAvailable && parsed.state === 'cached') {
          appendSearchTrail(mergedTrails, {
            stage: 'poll',
            tool: pollRequest.tool,
            status: 'cached',
            detail: 'Cache hit; historical trails unavailable for this artifact version.',
          })
        }
        const currentResult = await finalizeFromNormalized({
          parsedState: parsed.state,
          sourceRunId: runId,
          interactionId,
          idempotencyKey,
          normalized,
          mergedTrails,
          historicalTrailsAvailable,
        })
        if (!currentResult.qualityGate.pass) {
          args.onProgress?.(
            'Deep research completed but evidence gate was not met; retrying via sync fallback...',
            Number(progress.toFixed(3)),
          )
          try {
            const fallbackResult = await attemptSyncFallback('sync_after_quality_gate', progress)
            return selectPreferredDeepResearchResult(
              withFallbackPath(currentResult, 'sync_after_quality_gate'),
              fallbackResult,
            )
          } catch {
            return withFallbackPath(currentResult, 'sync_after_quality_gate')
          }
        }
        return currentResult
      }
    }
  } catch (error) {
    throw toDeepResearchError(error)
  }
}

function buildKgQuestion(term: string, contextTerms?: string[]): string {
  const base = [term, ...(contextTerms ?? [])]
  const normalized = base
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter(Boolean)
  const seen = new Set<string>()
  const deduped: string[] = []
  for (const piece of normalized) {
    const key = piece.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(piece)
  }
  return deduped.length ? deduped.join(' | ') : term
}

function normalizeConcepts(payload: JsonRecord | null): string[] {
  if (!payload) return []
  const conceptsRaw = Array.isArray(payload.concepts) ? payload.concepts : []
  const concepts = conceptsRaw
    .map((concept) => {
      if (typeof concept === 'string') return concept.trim()
      const objectConcept = asRecord(concept)
      return (
        asString(objectConcept?.name) ||
        asString(objectConcept?.label) ||
        asString(objectConcept?.concept) ||
        null
      )
    })
    .filter((item): item is string => Boolean(item))

  return Array.from(new Set(concepts))
}

function normalizeSynonyms(payload: JsonRecord | null): string[] {
  if (!payload) return []
  const raw = Array.isArray(payload.synonyms) ? payload.synonyms : []
  const terms = raw
    .map((value) => {
      if (typeof value === 'string') return value.trim()
      const record = asRecord(value)
      return asString(record?.label) || asString(record?.name) || null
    })
    .filter((item): item is string => Boolean(item))

  return Array.from(new Set(terms))
}

function parseMultihopSummary(payload: JsonRecord | null): {
  answer: string | null
  nPaths: number
  warnings: string[]
  hopsUsed: number | null
} {
  if (!payload) {
    return {
      answer: null,
      nPaths: 0,
      warnings: [],
      hopsUsed: null,
    }
  }

  const summary = asRecord(readNestedDataField(payload, 'summary'))
  const pathsRaw = readNestedDataField(payload, 'paths')
  const paths = Array.isArray(pathsRaw) ? pathsRaw : []

  return {
    answer: asString(readNestedDataField(payload, 'answer')),
    nPaths: asNumber(summary?.n_paths) ?? paths.length,
    warnings: asStringArray(readNestedDataField(payload, 'warnings')),
    hopsUsed: asNumber(summary?.hops_used ?? summary?.max_hops),
  }
}

function unwrapMcpToolEnvelope(payload: JsonRecord | null): {
  ok: boolean
  result: unknown
  error: string | null
  warnings: string[]
} {
  if (!payload) {
    return { ok: true, result: null, error: null, warnings: [] }
  }
  const ok =
    typeof payload.ok === 'boolean'
      ? payload.ok
      : typeof payload.success === 'boolean'
        ? Boolean(payload.success)
        : true
  const result = Object.prototype.hasOwnProperty.call(payload, 'result')
    ? payload.result
    : payload
  const resultRecord = asRecord(result)
  const warnings = [
    ...asStringArray(payload.warnings),
    ...asStringArray(resultRecord?.warnings),
  ]
  return {
    ok,
    result,
    error: asString(payload.error) || asString(resultRecord?.error),
    warnings,
  }
}

export async function runKgHypothesisCandidateCards(args: {
  query: string
  authHeaders?: Headers
  topN?: number
  topK?: number
  tasteMode?: string
  controllerMode?: string
  candidateLaneMode?: string
  withDeepResearch?: boolean
  deepResearchInteractionId?: string | null
  recencyDays?: number | null
  excludeDomains?: string[]
  timeoutMs?: number | null
}): Promise<HypothesisCandidateCardsRuntimeResult> {
  const query = asString(args.query)
  if (!query) {
    throw new Error('Candidate-card query is empty.')
  }

  const response = await runAgentTool({
    tool: 'kg_hypothesis_candidate_cards',
    authHeaders: args.authHeaders,
    timeoutMs: args.timeoutMs,
    arguments: {
      query,
      top_n: Math.max(1, Math.trunc(args.topN ?? 6)),
      top_k: Math.max(1, Math.trunc(args.topK ?? 20)),
      taste_mode: asString(args.tasteMode) || 'balanced',
      controller_mode: asString(args.controllerMode) || 'principle_v0',
      candidate_lane_mode: asString(args.candidateLaneMode) || 'broad',
      with_deep_research: args.withDeepResearch ?? false,
      deep_research_interaction_id: asString(args.deepResearchInteractionId) || undefined,
      recency_days:
        args.recencyDays === undefined || args.recencyDays === null
          ? undefined
          : Math.max(0, Math.trunc(args.recencyDays)),
      exclude_domains: args.excludeDomains || [],
    },
  })

  const parsed = unwrapMcpToolEnvelope(response.payload)
  if (!parsed.ok) {
    throw new Error(parsed.error || 'kg_hypothesis_candidate_cards returned an error')
  }

  const result = asRecord(parsed.result)
  const summary = asRecord(result?.summary)
  const resolvedAnchorBundle = asRecordArray(result?.resolved_anchor_bundle).map((item) => {
    const row = asRecord(item)
    return {
      kg_id: asString(row?.kg_id),
      label: asString(row?.label),
      node_type: asString(row?.node_type),
      matched_queries: asStringArray(row?.matched_queries),
      score: asNumber(row?.score),
      rank: asNumber(row?.rank),
      raw: row || {},
    }
  })
  const candidateCards = asRecordArray(result?.candidate_cards).map((card) => ({
    card_id: asString(card.card_id ?? card.id) || 'cand_unknown',
    title: asString(card.title) || 'Candidate',
    hypothesis: asString(card.hypothesis ?? card.summary) || '',
    taste_axis: asString(card.taste_axis),
    minimal_discriminating_test: asString(card.minimal_discriminating_test),
    falsifier_hint: asString(card.falsifier_hint),
    contradiction_probe: asString(card.contradiction_probe),
    topology_shift_probe: asString(card.topology_shift_probe),
    grounding_status: asString(card.grounding_status),
    evidence_summary: asString(card.evidence_summary),
    deep_research_status: asString(card.deep_research_status),
    deep_research_error: asString(card.deep_research_error),
    kg_verification: asRecord(card.kg_verification),
    novelty_signals: asRecord(card.novelty_signals),
    topology_subgraph: asRecord(card.topology_subgraph),
    provenance: asRecord(card.provenance),
    raw: card,
  }))

  return {
    query: asString(result?.query) || query,
    candidateCards,
    resolvedAnchorBundle,
    summary: {
      nCandidateCards: asNumber(summary?.n_candidate_cards) ?? candidateCards.length,
      nGroundedCards: asNumber(summary?.n_grounded_cards) ?? 0,
      nDegradedCards: asNumber(summary?.n_degraded_cards) ?? 0,
      candidateLaneMode: asString(summary?.candidate_lane_mode),
      deepResearchRequested: Boolean(summary?.deep_research_requested),
    },
    workflow: asRecord(result?.workflow),
    deepResearch: asRecord(result?.deep_research),
    ephemeralWeightedSubgraph: asRecord(result?.ephemeral_weighted_subgraph),
    warnings: Array.from(
      new Set([...parsed.warnings, ...asStringArray(result?.warnings)]),
    ),
  }
}

async function runKgNoveltyTasteTools(args: {
  term: string
  seedKgIds: string[]
  authHeaders?: Headers
  timeoutMs?: number | null
}): Promise<{ signals: KgNoveltyTasteSignals; warnings: string[] }> {
  const signals: KgNoveltyTasteSignals = {
    structuralLeverage: [],
    contradictionMotifs: [],
    oodHypotheses: [],
    topologyShifts: [],
  }
  const warnings: string[] = []
  const seedKgIds = Array.from(new Set(args.seedKgIds.map((v) => (v || '').trim()).filter(Boolean)))
  const timeoutMs = args.timeoutMs

  const appendWarnings = (prefix: string, list: string[]) => {
    list
      .map((item) => clampText(asString(item), 220))
      .filter((item): item is string => Boolean(item))
      .forEach((item) => warnings.push(`${prefix}: ${item}`))
  }

  if (seedKgIds.length) {
    try {
      const response = await runAgentTool({
        tool: 'kg_probe',
        authHeaders: args.authHeaders,
        timeoutMs,
        arguments: {
          probe_type: 'structural_leverage',
          start_kg_ids: seedKgIds.slice(0, 6),
          top_k: 6,
          max_hops: 2,
        },
      })
      const parsed = unwrapMcpToolEnvelope(response.payload)
      appendWarnings('kg_probe(structural_leverage)', parsed.warnings)
      if (!parsed.ok) {
        if (parsed.error) warnings.push(`kg_probe(structural_leverage): ${parsed.error}`)
      } else {
        const result = asRecord(parsed.result)
        const items = asRecordArray(result?.items ?? result?.ranked_nodes)
        const labels = items
          .slice(0, 3)
          .map((item) => asString(item.label ?? item.name ?? item.kg_id))
          .filter((item): item is string => Boolean(item))
        if (labels.length) {
          signals.structuralLeverage.push(
            `Structural leverage bridge candidates: ${labels.join(', ')}.`,
          )
        }
      }
    } catch (error) {
      warnings.push(`kg_probe(structural_leverage) failed: ${extractErrorMessage(error)}`)
    }

    try {
      const response = await runAgentTool({
        tool: 'kg_hypothesis_workflow',
        authHeaders: args.authHeaders,
        timeoutMs,
        arguments: {
          operation: 'sample',
          seed_kg_ids: seedKgIds.slice(0, 6),
          n_samples: 4,
          strategy: 'balanced',
          max_hops: 2,
        },
      })
      const parsed = unwrapMcpToolEnvelope(response.payload)
      appendWarnings('kg_hypothesis_workflow(sample)', parsed.warnings)
      if (!parsed.ok) {
        if (parsed.error) warnings.push(`kg_hypothesis_workflow(sample): ${parsed.error}`)
      } else {
        const result = asRecord(parsed.result)
        const hypotheses = asRecordArray(result?.hypotheses ?? result?.samples)
        hypotheses
          .slice(0, 2)
          .forEach((item, index) => {
            const statement =
              asString(item.statement ?? item.hypothesis ?? item.text) ||
              asString(item.relation_hint)
            if (statement) {
              signals.oodHypotheses.push(
                `OOD hypothesis ${index + 1}: ${clampText(statement, 220)}`,
              )
            }
          })
      }
    } catch (error) {
      warnings.push(`kg_hypothesis_workflow(sample) failed: ${extractErrorMessage(error)}`)
    }
  } else {
    warnings.push('Novelty tools skipped: no seed KG IDs available from task mapping.')
  }

  try {
    const response = await runAgentTool({
      tool: 'kg_probe',
      authHeaders: args.authHeaders,
      timeoutMs,
      arguments: {
        probe_type: 'contradiction_motifs',
        hypothesis: `${args.term} claims are invariant across tasks.`,
        entity_hints: seedKgIds.slice(0, 4),
        max_results: 20,
      },
    })
    const parsed = unwrapMcpToolEnvelope(response.payload)
    appendWarnings('kg_probe(contradiction_motifs)', parsed.warnings)
    if (!parsed.ok) {
      if (parsed.error) warnings.push(`kg_probe(contradiction_motifs): ${parsed.error}`)
    } else {
      const result = asRecord(parsed.result)
      const motifs = asRecordArray(result?.motifs)
      if (motifs.length) {
        const top = motifs[0]
        const motifLabel =
          asString(top.publication_label ?? top.publication_id ?? top.motif_type) ||
          'top motif'
        const supportCount = asNumber(top.support_count) ?? 0
        const conflictCount = asNumber(top.conflict_count) ?? 0
        signals.contradictionMotifs.push(
          `Contradiction motifs detected (${motifs.length}); top motif ${motifLabel} with support/conflict=${supportCount}/${conflictCount}.`,
        )
      }
    }
  } catch (error) {
    warnings.push(`kg_probe(contradiction_motifs) failed: ${extractErrorMessage(error)}`)
  }

  try {
    const response = await runAgentTool({
      tool: 'kg_detect_topology_shifts',
      authHeaders: args.authHeaders,
      timeoutMs,
      arguments: {
        mode: 'detect',
        scope: args.term,
      },
    })
    const parsed = unwrapMcpToolEnvelope(response.payload)
    appendWarnings('kg_detect_topology_shifts', parsed.warnings)
    if (!parsed.ok) {
      if (parsed.error) warnings.push(`kg_detect_topology_shifts: ${parsed.error}`)
    } else {
      const result = asRecord(parsed.result)
      const proposals = asRecordArray(result?.proposals)
      if (proposals.length) {
        const highlights = proposals.slice(0, 2).map((proposal) => {
          const edge = asRecord(proposal.edge)
          const source = asString(edge?.source_id) || '?'
          const rel = asString(edge?.rel_type) || 'RELATED_TO'
          const target = asString(edge?.target_id) || '?'
          const delta = asNumber(proposal.delta)
          const deltaText = delta === null ? '' : ` (delta=${delta.toFixed(3)})`
          return `${source} -[${rel}]-> ${target}${deltaText}`
        })
        if (highlights.length) {
          signals.topologyShifts.push(`Topology-shift candidates: ${highlights.join(' | ')}`)
        }
      }
    }
  } catch (error) {
    warnings.push(`kg_detect_topology_shifts failed: ${extractErrorMessage(error)}`)
  }

  return { signals, warnings }
}

export type KgCompareRuntimeOptions = {
  softenNoSeedError?: boolean
  maxSeedRetries?: number
  timeoutMs?: number | null
  enableNoveltyTools?: boolean
}

export type KgNoveltyTasteSignals = {
  structuralLeverage: string[]
  contradictionMotifs: string[]
  oodHypotheses: string[]
  topologyShifts: string[]
}

export type KgCompareRuntimeResult = {
  priorArtMatch: string[]
  noveltyGap: string[]
  feasibilityConstraints: string[]
  concepts: string[]
  warnings: string[]
  multihopAttempts: number
  noveltyTaste: KgNoveltyTasteSignals
}

export type HypothesisCandidateCardPayload = {
  card_id: string
  title: string
  hypothesis: string
  taste_axis: string | null
  minimal_discriminating_test: string | null
  falsifier_hint: string | null
  contradiction_probe: string | null
  topology_shift_probe: string | null
  grounding_status: string | null
  evidence_summary: string | null
  deep_research_status: string | null
  deep_research_error: string | null
  kg_verification: JsonRecord | null
  novelty_signals: JsonRecord | null
  topology_subgraph: JsonRecord | null
  provenance: JsonRecord | null
  raw: JsonRecord
}

export type HypothesisResolvedAnchorBundleItem = {
  kg_id: string
  label: string | null
  node_type: string | null
  matched_queries: string[]
  score: number | null
  rank: number | null
  raw: JsonRecord
}

export type HypothesisCandidateCardsRuntimeResult = {
  query: string
  candidateCards: HypothesisCandidateCardPayload[]
  resolvedAnchorBundle: HypothesisResolvedAnchorBundleItem[]
  summary: {
    nCandidateCards: number
    nGroundedCards: number
    nDegradedCards: number
    candidateLaneMode: string | null
    deepResearchRequested: boolean
  }
  workflow: JsonRecord | null
  deepResearch: JsonRecord | null
  ephemeralWeightedSubgraph: JsonRecord | null
  warnings: string[]
}

export async function runKgCompare(args: {
  term: string
  authHeaders?: Headers
  options?: KgCompareRuntimeOptions
}): Promise<KgCompareRuntimeResult> {
  const term = asString(args.term)
  if (!term) {
    throw new Error('KG compare term is empty.')
  }

  const softenNoSeedError = args.options?.softenNoSeedError ?? true
  const maxSeedRetries = Math.max(0, Math.trunc(args.options?.maxSeedRetries ?? 1))
  const enableNoveltyTools =
    args.options?.enableNoveltyTools ??
    process.env.HYPOTHESIS_KG_NOVELTY_TOOLS_ENABLED !== '0'
  const kgMultihopTimeoutMs =
    args.options?.timeoutMs === undefined
      ? resolveKgMultihopToolTimeoutMs()
      : args.options.timeoutMs === null
        ? null
        : Number.isFinite(args.options.timeoutMs)
          ? Math.trunc(args.options.timeoutMs) > 0
            ? Math.trunc(args.options.timeoutMs)
            : null
          : resolveKgMultihopToolTimeoutMs()

  const mappingResult = await runAgentTool({
    tool: 'task_to_concept_mapping',
    authHeaders: args.authHeaders,
    arguments: {
      task_name: term,
      include_synonyms: true,
    },
  })

  const mappingPayload = mappingResult.payload
  const mappedTask = asString(mappingPayload?.matched_task)
  const concepts = normalizeConcepts(mappingPayload)
  const synonyms = normalizeSynonyms(mappingPayload)

  const kgQuestion = buildKgQuestion(term, [
    mappedTask || '',
    ...concepts.slice(0, 6),
    ...synonyms.slice(0, 6),
  ])
  const seedKgIds = Array.from(
    new Set([mappedTask || '', ...concepts].map((value) => (value || '').trim()).filter(Boolean)),
  )

  let multihopSummary = {
    answer: null,
    nPaths: 0,
    warnings: [] as string[],
    hopsUsed: null as number | null,
  }
  const warnings: string[] = []
  const noveltyTaste: KgNoveltyTasteSignals = {
    structuralLeverage: [],
    contradictionMotifs: [],
    oodHypotheses: [],
    topologyShifts: [],
  }
  let multihopAttempts = 0

  for (let attempt = 0; attempt <= maxSeedRetries; attempt += 1) {
    multihopAttempts += 1
    try {
      const multihopResult = await runAgentTool({
        tool: 'kg_multihop_qa',
        authHeaders: args.authHeaders,
        timeoutMs: kgMultihopTimeoutMs,
        arguments: {
          question: kgQuestion,
          max_hops: 2,
          max_results: 12,
          mode: 'breadth_first',
          return_subgraph: false,
        },
      })

      multihopSummary = parseMultihopSummary(multihopResult.payload)
      break
    } catch (error) {
      const noSeed = isNoSeedEntitiesError(error)
      const retriesRemaining = attempt < maxSeedRetries

      if (noSeed && retriesRemaining) {
        continue
      }

      if (noSeed && softenNoSeedError) {
        warnings.push(
          'KG multihop skipped due to sparse seed anchors for this broad query. Local comparison was used instead.',
        )
        break
      }

      throw error
    }
  }

  if (enableNoveltyTools) {
    const noveltySignals = await runKgNoveltyTasteTools({
      term,
      seedKgIds,
      authHeaders: args.authHeaders,
      timeoutMs: kgMultihopTimeoutMs,
    })
    noveltyTaste.structuralLeverage = noveltySignals.signals.structuralLeverage
    noveltyTaste.contradictionMotifs = noveltySignals.signals.contradictionMotifs
    noveltyTaste.oodHypotheses = noveltySignals.signals.oodHypotheses
    noveltyTaste.topologyShifts = noveltySignals.signals.topologyShifts
    if (noveltySignals.warnings.length) {
      warnings.push(...noveltySignals.warnings.slice(0, 6))
    }
  }

  const priorArtMatch: string[] = []
  if (mappedTask && mappedTask.toLowerCase() !== term.toLowerCase()) {
    priorArtMatch.push(`Closest mapped task in KG: ${mappedTask}.`)
  }
  if (synonyms.length) {
    priorArtMatch.push(`Mapped aliases: ${synonyms.slice(0, 6).join(', ')}.`)
  }
  if (concepts.length) {
    priorArtMatch.push(`Mapped concepts: ${concepts.slice(0, 6).join(', ')}.`)
  }
  if (multihopSummary.nPaths > 0) {
    priorArtMatch.push(`KG multihop returned ${multihopSummary.nPaths} path(s) for this query.`)
  }
  priorArtMatch.push(...noveltyTaste.structuralLeverage.slice(0, 2))

  const noveltyGap: string[] = []
  if (multihopSummary.answer) {
    noveltyGap.push(clampText(multihopSummary.answer))
  }
  if (multihopSummary.warnings.length) {
    noveltyGap.push(`KG warnings: ${multihopSummary.warnings.slice(0, 2).join('; ')}`)
  }
  noveltyGap.push(...noveltyTaste.contradictionMotifs.slice(0, 2))
  noveltyGap.push(...noveltyTaste.oodHypotheses.slice(0, 2))
  if (warnings.length) {
    noveltyGap.push(...warnings)
  }
  if (!noveltyGap.length) {
    noveltyGap.push(`Cross-paradigm bridge opportunities around ${term} remain under-specified.`)
  }

  const feasibilityConstraints: string[] = []
  if (multihopSummary.hopsUsed !== null) {
    feasibilityConstraints.push(
      `Current evidence graph resolves within ~${multihopSummary.hopsUsed} hop(s).`,
    )
  }
  if (!concepts.length) {
    feasibilityConstraints.push(
      'Task-to-concept mapping is sparse; expect higher uncertainty in plan validation.',
    )
  } else {
    feasibilityConstraints.push(
      'Use mapped concepts as anchors for minimal discriminating tests before full pipelines.',
    )
  }
  feasibilityConstraints.push(...noveltyTaste.topologyShifts.slice(0, 2))

  return {
    priorArtMatch: priorArtMatch.length
      ? priorArtMatch
      : [`Prior-art mapping is limited for ${term}; deeper KG expansion is recommended.`],
    noveltyGap,
    feasibilityConstraints,
    concepts,
    warnings,
    multihopAttempts,
    noveltyTaste,
  }
}
