'use client'

import {
  type ComponentPropsWithoutRef,
  type HTMLAttributes,
  type ReactNode,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { useSearchParams } from 'next/navigation'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type JsonRecord = Record<string, unknown>
const OPAQUE_TOKEN_PATTERN = /^[A-Za-z0-9+/_=-]{32,}$/
const REDIRECT_AGGREGATE_THRESHOLD = 3
const MARKDOWN_LINE_GAP_CLASS = 'space-y-2.5 leading-7'

type DeepResearchReport = {
  query: string
  status: string
  source_run_id: string | null
  interaction_id: string | null
  idempotency_key: string | null
  summary: string
  synthesis_full_text: string
  raw_summary: string | null
  raw_synthesis_full_text: string | null
  claim_review: {
    source_run_id: string
    source_artifact: 'claim_report.json'
    summary: string | null
    overall_verdict: string | null
    caveats: string[]
    unresolved_questions: string[]
    claim_count: number
    rendered_markdown: string
  } | null
  synthesis_generated_by: 'upstream' | 'llm_fallback' | 'fallback_rule'
  synthesis_source_count: number
  search_trails: Array<{
    stage: 'start' | 'poll' | 'sync_fallback'
    tool: string
    status: string
    detail: string | null
  }>
  historical_trails_available: boolean
  source_inventory: Array<{
    id: string
    label: string
    display_title: string | null
    summary: string | null
    url: string | null
    raw_url: string | null
    final_url: string | null
    source_host: string | null
    kind: string
    source_type: string | null
    quality_tier: string | null
    traceability_score: number | null
  }>
  discarded_sources: Array<{
    id: string
    label: string
    display_title: string | null
    summary: string | null
    url: string | null
    raw_url: string | null
    final_url: string | null
    source_host: string | null
    kind: string
    source_type: string | null
    quality_tier: string | null
    traceability_score: number | null
    reason_code: string
    reason_detail: string | null
    reason_meta: {
      attempted: boolean
      resolver: 'none' | 'query_param' | 'head' | 'get'
      http_status: number | null
      error: string | null
      skipped_by_budget: boolean
    } | null
  }>
  discarded_aggregates: Array<{
    reason_code: string
    count: number
    detail: string
    stats: Record<string, number>
  }>
  search_stats: {
    scanned_count: number
    qualifying_count: number
    unique_after_dedupe_count: number
    final_citable_count: number
    discarded_count: number
  }
  generated_at: string
}

function safeParseUrl(value: string | null): URL | null {
  if (!value) return null
  try {
    return new URL(value)
  } catch {
    return null
  }
}

function toReadableSlug(value: string): string | null {
  const decoded = decodeURIComponent(value).trim()
  if (!decoded) return null
  const normalized = decoded
    .replace(/\.[a-z0-9]{2,6}$/i, '')
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!normalized) return null
  if (normalized.length > 90) return normalized.slice(0, 90).trim()
  return normalized
}

function inferTitleFromUrl(url: string | null): string | null {
  const parsed = safeParseUrl(url)
  if (!parsed) return null
  const host = parsed.hostname

  if (host.includes('pubmed.ncbi.nlm.nih.gov')) {
    const pmid = parsed.pathname.match(/\/(\d+)\//)?.[1] || parsed.pathname.match(/\/(\d+)$/)?.[1]
    return pmid ? `PubMed ${pmid}` : 'PubMed record'
  }
  if (host.includes('doi.org')) {
    const doi = parsed.pathname.replace(/^\/+/, '').trim()
    return doi ? `DOI ${doi}` : 'DOI record'
  }
  if (host.includes('vertexaisearch.cloud.google.com')) {
    return 'Unresolved grounding redirect'
  }

  const parts = parsed.pathname.split('/').filter(Boolean)
  const candidate = parts.length ? parts[parts.length - 1] : ''
  const readable = toReadableSlug(candidate)
  if (readable) return readable

  return host.replace(/^www\./, '')
}

function isOpaqueLabel(label: string | null | undefined): boolean {
  const text = (label || '').trim()
  if (!text) return true
  if (/^(source|discarded|doc)[-_]?\d+$/i.test(text)) return true
  if (/^AUZIYQ/i.test(text)) return true
  if (text.includes('vertexaisearch.cloud.google.com')) return true
  return false
}

function normalizeMarkdown(value: string): string {
  const normalized = value.replace(/\r\n?/g, '\n').trim()

  return normalized
    .replace(/\n{3,}/g, '\n\n')
    .replace(/([^\n])\n(#{1,6}\s)/g, '$1\n\n$2')
    .replace(/([^\n])\n([*-]\s)/g, '$1\n\n$2')
    .replace(/\n{2}(?=(?:\d+\.|\*)\s)/g, '\n')
    .trim()
}

const markdownComponents = {
  h1: ({ children }: ComponentPropsWithoutRef<'h1'>) => (
    <h2 className="mt-6 mb-2 text-xl font-semibold tracking-tight text-foreground">{children}</h2>
  ),
  h2: ({ children }: ComponentPropsWithoutRef<'h2'>) => (
    <h3 className="mt-5 mb-2 text-lg font-semibold tracking-tight text-foreground">{children}</h3>
  ),
  h3: ({ children }: ComponentPropsWithoutRef<'h3'>) => (
    <h4 className="mt-4 mb-2 text-base font-semibold tracking-tight text-foreground">{children}</h4>
  ),
  h4: ({ children }: ComponentPropsWithoutRef<'h4'>) => (
    <h5 className="mt-3 mb-2 text-sm font-semibold tracking-tight text-foreground">{children}</h5>
  ),
  h5: ({ children }: ComponentPropsWithoutRef<'h5'>) => (
    <h6 className="mt-3 mb-2 text-xs font-semibold tracking-tight text-muted-foreground">{children}</h6>
  ),
  p: ({ children }: ComponentPropsWithoutRef<'p'>) => (
    <p className="text-sm text-foreground">{children}</p>
  ),
  ul: ({ children }: ComponentPropsWithoutRef<'ul'>) => (
    <ul className="mt-1 space-y-1 list-disc pl-5 marker:text-foreground/80">{children}</ul>
  ),
  ol: ({ children }: ComponentPropsWithoutRef<'ol'>) => (
    <ol className="mt-1 space-y-1 list-decimal pl-5">{children}</ol>
  ),
  li: ({ children }: ComponentPropsWithoutRef<'li'>) => (
    <li className="text-sm leading-7 text-foreground">{children}</li>
  ),
  a: ({ href, children }: ComponentPropsWithoutRef<'a'>) => {
    if (!href) {
      return <span>{children}</span>
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-blue-600 hover:text-blue-500 underline underline-offset-2"
      >
        {children}
      </a>
    )
  },
  blockquote: ({ children }: ComponentPropsWithoutRef<'blockquote'>) => (
    <blockquote className="border-l-4 border-blue-400/80 pl-4 italic text-muted-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-muted" />,
  code: ({ inline, children }: HTMLAttributes<HTMLElement> & { inline?: boolean }) =>
    inline ? (
      <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-foreground">
        {children}
      </code>
    ) : (
      <code className="block rounded bg-muted p-3 text-xs leading-6">{children}</code>
    ),
  pre: ({ children }: ComponentPropsWithoutRef<'pre'>) => (
    <pre className="overflow-x-auto rounded-md border border-border/70 bg-muted p-3">{children}</pre>
  ),
}

function renderSynthesisMarkdown(value: string | null): ReactNode {
  const text = normalizeMarkdown(value || '')
  if (!text) return <p className="text-muted-foreground text-sm">(empty synthesis)</p>

  return (
    <div className={`prose prose-sm max-w-none text-foreground ${MARKDOWN_LINE_GAP_CLASS}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

function displaySourceTitle(source: {
  display_title?: string | null
  label: string
  url: string | null
  final_url?: string | null
  source_host: string | null
}): string {
  const preferred = (source.display_title || '').trim()
  if (preferred && !isOpaqueLabel(preferred)) return preferred
  const label = (source.label || '').trim()
  if (!isOpaqueLabel(label)) return label
  return (
    inferTitleFromUrl(source.final_url || source.url) ||
    (source.source_host ? `${source.source_host.replace(/^www\./, '')} source` : null) ||
    'Untitled source'
  )
}

function sourceMetadata(source: {
  kind: string
  source_type: string | null
  quality_tier: string | null
  source_host: string | null
  traceability_score: number | null
}): string {
  const kind = source.kind && source.kind !== 'other' ? source.kind : null
  const bits = [kind, source.source_type, source.quality_tier, source.source_host]
  if (source.traceability_score !== null) {
    bits.push(`traceability=${source.traceability_score.toFixed(2)}`)
  }
  return bits.filter(Boolean).join(' · ')
}

function sourceHref(source: { final_url: string | null; url: string | null }): string | null {
  return source.final_url || source.url || null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asNullableString(value: unknown): string | null {
  const normalized = asString(value).trim()
  return normalized || null
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function asResolver(value: unknown): 'none' | 'query_param' | 'head' | 'get' {
  const resolver = asString(value).trim()
  if (resolver === 'query_param' || resolver === 'head' || resolver === 'get') {
    return resolver
  }
  return 'none'
}

function isOpaqueTokenLike(value: string): boolean {
  const text = value.trim()
  if (!text) return false
  if (/^https?:\/\//i.test(text)) return false
  if (/\s/.test(text)) return false
  if (text.toUpperCase().startsWith('AUZIYQ') && text.length >= 24) return true
  if (text.length < 40 || !OPAQUE_TOKEN_PATTERN.test(text)) return false
  if (!text.includes('.') && !text.includes('/')) return true
  return (text.match(/[_-]/g) || []).length >= 2 && text.length >= 56
}

function parseReport(payload: unknown): DeepResearchReport | null {
  if (!payload || typeof payload !== 'object') return null
  const source = payload as JsonRecord
  const searchStats = (source.search_stats ?? source.searchStats) as JsonRecord | undefined
  const trailsRaw: unknown[] = Array.isArray(source.search_trails ?? source.searchTrails)
    ? ((source.search_trails ?? source.searchTrails) as unknown[])
    : []
  const sourceInventoryRaw: unknown[] = Array.isArray(
    source.source_inventory ?? source.sourceInventory,
  )
    ? ((source.source_inventory ?? source.sourceInventory) as unknown[])
    : []
  const discardedRaw: unknown[] = Array.isArray(
    source.discarded_sources ?? source.discardedSources,
  )
    ? ((source.discarded_sources ?? source.discardedSources) as unknown[])
    : []
  const discardedAggregatesRaw: unknown[] = Array.isArray(
    source.discarded_aggregates ?? source.discardedAggregates,
  )
    ? ((source.discarded_aggregates ?? source.discardedAggregates) as unknown[])
    : []

  const query = asString(source.query).trim()
  const summary = asString(source.summary).trim()
  const synthesisRaw = asString(source.synthesis_full_text ?? source.synthesisFullText).trim()
  const rawSummary = asNullableString(source.raw_summary ?? source.rawSummary)
  const rawSynthesis = asNullableString(
    source.raw_synthesis_full_text ?? source.rawSynthesisFullText,
  )
  const cleanedSummary = isOpaqueTokenLike(summary) ? '' : summary
  const synthesis = isOpaqueTokenLike(synthesisRaw) ? '' : synthesisRaw
  if (!query && !synthesis && !cleanedSummary) return null

  const claimReviewRaw = (source.claim_review ?? source.claimReview) as JsonRecord | undefined
  const claimReview =
    claimReviewRaw && typeof claimReviewRaw === 'object'
      ? {
          source_run_id:
            asNullableString(claimReviewRaw.source_run_id ?? claimReviewRaw.sourceRunId) || '',
          source_artifact:
            (asNullableString(
              claimReviewRaw.source_artifact ?? claimReviewRaw.sourceArtifact,
            ) as 'claim_report.json' | null) || 'claim_report.json',
          summary: asNullableString(claimReviewRaw.summary),
          overall_verdict: asNullableString(
            claimReviewRaw.overall_verdict ?? claimReviewRaw.overallVerdict,
          ),
          caveats: Array.isArray(claimReviewRaw.caveats)
            ? claimReviewRaw.caveats
                .map((item) => asNullableString(item))
                .filter((item): item is string => Boolean(item))
            : [],
          unresolved_questions: Array.isArray(
            claimReviewRaw.unresolved_questions ?? claimReviewRaw.unresolvedQuestions,
          )
            ? ((claimReviewRaw.unresolved_questions ??
                claimReviewRaw.unresolvedQuestions) as unknown[])
                .map((item) => asNullableString(item))
                .filter((item): item is string => Boolean(item))
            : [],
          claim_count: asNumber(claimReviewRaw.claim_count ?? claimReviewRaw.claimCount) ?? 0,
          rendered_markdown:
            asNullableString(
              claimReviewRaw.rendered_markdown ?? claimReviewRaw.renderedMarkdown,
            ) || '',
        }
      : null

  return {
    query,
    status: asString(source.status).trim() || 'unknown',
    source_run_id: asNullableString(source.source_run_id ?? source.sourceRunId),
    interaction_id: asNullableString(source.interaction_id ?? source.interactionId),
    idempotency_key: asNullableString(source.idempotency_key ?? source.idempotencyKey),
    summary: cleanedSummary,
    synthesis_full_text: synthesis || cleanedSummary,
    raw_summary: rawSummary,
    raw_synthesis_full_text: rawSynthesis,
    claim_review: claimReview,
    synthesis_generated_by: (() => {
      const mode = asString(source.synthesis_generated_by ?? source.synthesisGeneratedBy).trim()
      return mode === 'llm_fallback' || mode === 'fallback_rule' ? mode : 'upstream'
    })(),
    synthesis_source_count: asNumber(source.synthesis_source_count ?? source.synthesisSourceCount) ?? 0,
    search_trails: trailsRaw
      .map((raw) => {
        const trail = (raw ?? {}) as JsonRecord
        const stage = asString(trail.stage).trim()
        if (!stage) return null
        return {
          stage:
            stage === 'start' || stage === 'sync_fallback'
              ? stage
              : ('poll' as const),
          tool: asString(trail.tool).trim(),
          status: asString(trail.status).trim() || 'unknown',
          detail: asNullableString(trail.detail),
        }
      })
      .filter(
        (item): item is DeepResearchReport['search_trails'][number] =>
          Boolean(item && item.tool),
      ),
    historical_trails_available: (() => {
      const value = source.historical_trails_available ?? source.historicalTrailsAvailable
      if (typeof value === 'boolean') return value
      if (typeof value === 'string') return value.trim().toLowerCase() === 'true'
      return true
    })(),
    source_inventory: sourceInventoryRaw
      .map((raw, idx) => {
        const item = (raw ?? {}) as JsonRecord
        return {
          id: asString(item.id).trim() || `source-${idx + 1}`,
          label: asString(item.label).trim() || `Source ${idx + 1}`,
          display_title: asNullableString(item.display_title ?? item.displayTitle),
          summary: asNullableString(item.summary),
          url: asNullableString(item.url),
          raw_url: asNullableString(item.raw_url ?? item.rawUrl),
          final_url: asNullableString(item.final_url ?? item.finalUrl),
          source_host: asNullableString(item.source_host ?? item.sourceHost),
          kind: asString(item.kind).trim() || 'other',
          source_type: asNullableString(item.source_type ?? item.sourceType),
          quality_tier: asNullableString(item.quality_tier ?? item.qualityTier),
          traceability_score: asNumber(item.traceability_score ?? item.traceabilityScore),
        }
      })
      .filter((item) => Boolean(item.id)),
    discarded_sources: discardedRaw
      .map((raw, idx) => {
        const item = (raw ?? {}) as JsonRecord
        return {
          id: asString(item.id).trim() || `discarded-${idx + 1}`,
          label: asString(item.label).trim() || `Discarded ${idx + 1}`,
          display_title: asNullableString(item.display_title ?? item.displayTitle),
          summary: asNullableString(item.summary),
          url: asNullableString(item.url),
          raw_url: asNullableString(item.raw_url ?? item.rawUrl),
          final_url: asNullableString(item.final_url ?? item.finalUrl),
          source_host: asNullableString(item.source_host ?? item.sourceHost),
          kind: asString(item.kind).trim() || 'other',
          source_type: asNullableString(item.source_type ?? item.sourceType),
          quality_tier: asNullableString(item.quality_tier ?? item.qualityTier),
          traceability_score: asNumber(item.traceability_score ?? item.traceabilityScore),
          reason_code: asString(item.reason_code ?? item.reasonCode).trim() || 'unknown',
          reason_detail: asNullableString(item.reason_detail ?? item.reasonDetail),
          reason_meta: (() => {
            const meta = (item.reason_meta ?? item.reasonMeta) as JsonRecord | undefined
            if (!meta || typeof meta !== 'object') return null
            return {
              attempted: Boolean(meta.attempted),
              resolver: asResolver(meta.resolver),
              http_status: asNumber(meta.http_status ?? meta.httpStatus),
              error: asNullableString(meta.error),
              skipped_by_budget: Boolean(meta.skipped_by_budget ?? meta.skippedByBudget),
            }
          })(),
        }
      })
      .filter((item) => Boolean(item.id)),
    discarded_aggregates: discardedAggregatesRaw
      .map((raw) => {
        const item = (raw ?? {}) as JsonRecord
        const statsRaw = (item.stats ?? {}) as JsonRecord
        const stats: Record<string, number> = {}
        for (const [key, value] of Object.entries(statsRaw || {})) {
          const parsed = asNumber(value)
          if (parsed !== null) stats[key] = parsed
        }
        return {
          reason_code: asString(item.reason_code ?? item.reasonCode).trim() || 'unknown',
          count: asNumber(item.count) ?? 0,
          detail: asString(item.detail).trim(),
          stats,
        }
      })
      .filter((item) => item.count > 0),
    search_stats: {
      scanned_count: asNumber(searchStats?.scanned_count ?? searchStats?.scannedCount) ?? 0,
      qualifying_count:
        asNumber(searchStats?.qualifying_count ?? searchStats?.qualifyingCount) ?? 0,
      unique_after_dedupe_count:
        asNumber(
          searchStats?.unique_after_dedupe_count ?? searchStats?.uniqueAfterDedupeCount,
        ) ?? 0,
      final_citable_count:
        asNumber(searchStats?.final_citable_count ?? searchStats?.finalCitableCount) ?? 0,
      discarded_count:
        asNumber(searchStats?.discarded_count ?? searchStats?.discardedCount) ?? 0,
    },
    generated_at:
      asString(source.generated_at ?? source.generatedAt).trim() || new Date().toISOString(),
  }
}

export function HypothesisDeepResearchReportPage() {
  const searchParams = useSearchParams()
  const runId = searchParams.get('runId') || searchParams.get('run') || ''
  const sessionId = searchParams.get('sessionId') || searchParams.get('session') || ''
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<DeepResearchReport | null>(null)

  useEffect(() => {
    let cancelled = false

    const run = async () => {
      if (!runId) {
        setError('Missing runId query parameter.')
        setLoading(false)
        return
      }

      setLoading(true)
      setError(null)
      setReport(null)

      try {
        const response = await fetch(`/api/hypothesis/run/${encodeURIComponent(runId)}`, {
          cache: 'no-store',
        })
        if (!response.ok) {
          setError(`Unable to load run snapshot (${response.status}).`)
          return
        }
        const payload = (await response.json().catch(() => null)) as JsonRecord | null
        const runPayload = (payload?.run && typeof payload.run === 'object'
          ? (payload.run as JsonRecord)
          : payload) as JsonRecord | null
        const artifacts = Array.isArray(runPayload?.artifacts) ? runPayload?.artifacts : []
        const reportArtifact = artifacts.find((raw) => {
          const artifact = (raw ?? {}) as JsonRecord
          return asString(artifact.kind) === 'deep_research_report'
        }) as JsonRecord | undefined
        const parsed = parseReport(reportArtifact?.payload)
        if (!parsed) {
          setError('No deep research report artifact is available for this run.')
          return
        }
        if (!cancelled) {
          setReport(parsed)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error while loading report.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [runId])

  const backHref = useMemo(() => {
    const params = new URLSearchParams()
    if (sessionId) params.set('sessionId', sessionId)
    if (runId) params.set('runId', runId)
    const query = params.toString()
    return query ? `/hypothesis?${query}` : '/hypothesis'
  }, [runId, sessionId])

  const unresolvedAggregate = useMemo(() => {
    if (!report) return null
    return (
      report.discarded_aggregates.find((item) => item.reason_code === 'redirect_unresolved') || null
    )
  }, [report])

  const unresolvedDiscardedItems = useMemo(() => {
    if (!report) return []
    return report.discarded_sources.filter((item) => item.reason_code === 'redirect_unresolved')
  }, [report])

  const nonRedirectDiscardedItems = useMemo(() => {
    if (!report) return []
    return report.discarded_sources.filter((item) => item.reason_code !== 'redirect_unresolved')
  }, [report])

  const backgroundTrace = useMemo(() => {
    if (!report) return null
    const raw = (report.raw_synthesis_full_text || '').trim()
    if (!raw) return null
    if (raw === report.synthesis_full_text.trim()) return null
    return raw
  }, [report])

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Deep Research Report</h1>
            <p className="text-sm text-muted-foreground">
              Full synthesis and source audit trail for run {runId || 'n/a'}.
            </p>
          </div>
          <a href={backHref} className="text-sm text-blue-600 hover:underline">
            Back to hypothesis run
          </a>
        </div>

        {loading ? (
          <Card className="border-border/70">
            <CardContent className="p-4 text-sm text-muted-foreground">Loading report...</CardContent>
          </Card>
        ) : null}

        {!loading && error ? (
          <Card className="border-border/70">
            <CardContent className="p-4 text-sm text-red-600">{error}</CardContent>
          </Card>
        ) : null}

        {!loading && report ? (
          <>
            <Card className="border-border/70">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Overview</CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-2">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">status: {report.status}</Badge>
                  {report.claim_review?.overall_verdict ? (
                    <Badge variant="outline">
                      claim verdict: {report.claim_review.overall_verdict}
                    </Badge>
                  ) : null}
                  <Badge variant="outline">scanned: {report.search_stats.scanned_count}</Badge>
                  <Badge variant="outline">qualified: {report.search_stats.qualifying_count}</Badge>
                  <Badge variant="outline">unique: {report.search_stats.unique_after_dedupe_count}</Badge>
                  <Badge variant="outline">final: {report.search_stats.final_citable_count}</Badge>
                  <Badge variant="outline">discarded: {report.search_stats.discarded_count}</Badge>
                </div>
                <div>query: {report.query}</div>
                <div>generated_at: {report.generated_at}</div>
                {report.source_run_id ? <div>source_run_id: {report.source_run_id}</div> : null}
                {report.interaction_id ? <div>interaction_id: {report.interaction_id}</div> : null}
                {report.idempotency_key ? (
                  <div>idempotency_key: {report.idempotency_key}</div>
                ) : null}
                {report.summary ? <div>summary: {report.summary}</div> : null}
              </CardContent>
            </Card>

            <Card className="border-border/70">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Search Trails</CardTitle>
              </CardHeader>
                <CardContent className="space-y-1 text-xs">
                {!report.historical_trails_available && report.status === 'cached' ? (
                  <div className="text-muted-foreground">
                    Cache hit; historical trails unavailable for this artifact version.
                  </div>
                ) : null}
                {report.search_trails.length ? (
                  <div className="overflow-x-auto rounded-md border border-border/60 bg-white">
                    <div className="grid min-w-[500px] gap-x-4 gap-y-0 text-[11px] sm:text-xs">
                      <div className="grid grid-cols-[110px_160px_1fr] px-3 py-2 font-medium text-muted-foreground border-b border-border/60 bg-muted/40">
                        <span>stage</span>
                        <span>tool</span>
                        <span>status / detail</span>
                      </div>
                      {report.search_trails.map((trail, idx) => (
                        <div
                          key={`${trail.stage}-${trail.tool}-${idx}`}
                          className="grid grid-cols-[110px_160px_1fr] gap-x-4 px-3 py-2 border-b border-border/30 last:border-b-0"
                        >
                          <Badge variant="outline" className="w-fit text-[10px]">
                            {trail.stage}
                          </Badge>
                          <span className="font-medium text-foreground break-words">{trail.tool}</span>
                          <span className="text-muted-foreground">
                            {trail.status}
                            {trail.detail ? ` · ${trail.detail}` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-muted-foreground">No trail records.</div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Synthesis</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="mb-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                  <Badge variant="outline">generated: {report.synthesis_generated_by}</Badge>
                  <Badge variant="outline">sources: {report.synthesis_source_count}</Badge>
                </div>
                {renderSynthesisMarkdown(report.synthesis_full_text || report.summary)}
              </CardContent>
            </Card>

            {backgroundTrace ? (
              <Card className="border-border/70">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Background Synthesis Trace</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-xs text-muted-foreground">
                    This raw synthesis trace is retained for audit only. Final verdict and caveats
                    above are rendered from calibrated claim review data.
                  </p>
                  {renderSynthesisMarkdown(backgroundTrace)}
                </CardContent>
              </Card>
            ) : null}

            <Card className="border-border/70">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Source Inventory ({report.source_inventory.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-2">
                {report.source_inventory.length ? (
                  <div className="grid gap-2">
                    {report.source_inventory.map((source) => {
                      const displayTitle = displaySourceTitle(source)
                      const subtitle = sourceMetadata(source)
                      const sourceLink = sourceHref(source)

                      return (
                        <div key={source.id} className="rounded border border-border/60 p-2 space-y-1">
                          <div className="font-medium break-words">{displayTitle}</div>
                          {source.label && source.label !== displayTitle ? (
                            <div className="text-[11px] text-muted-foreground break-all">
                              raw label: {source.label}
                            </div>
                          ) : null}
                          {subtitle ? <div className="text-muted-foreground">{subtitle}</div> : null}
                          {source.summary ? <div className="text-sm">{source.summary}</div> : null}
                          {sourceLink ? (
                            <a
                              href={sourceLink}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-1 inline-block text-blue-600 hover:underline break-all"
                            >
                              {sourceLink}
                            </a>
                          ) : null}
                          {source.raw_url && source.raw_url !== source.final_url ? (
                            <div className="text-[11px] text-muted-foreground break-all">
                              raw url: {source.raw_url}
                            </div>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-muted-foreground">No sources captured.</div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Discarded Sources ({report.discarded_sources.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-2">
                {report.discarded_aggregates.length ? (
                  <div className="flex flex-wrap gap-2">
                    {report.discarded_aggregates.map((aggregate) => (
                      <Badge key={`${aggregate.reason_code}-${aggregate.count}`} variant="outline">
                        {aggregate.reason_code}: {aggregate.count}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {report.discarded_sources.length ? (
                  <>
                    {unresolvedAggregate && unresolvedAggregate.count >= REDIRECT_AGGREGATE_THRESHOLD ? (
                      <div className="rounded border border-border/60 p-2">
                        <div className="font-medium">
                          Unresolved grounding redirects ({unresolvedAggregate.count})
                        </div>
                        <div className="text-muted-foreground mt-1">{unresolvedAggregate.detail}</div>
                        {Object.keys(unresolvedAggregate.stats).length ? (
                          <div className="text-[11px] text-muted-foreground mt-1 break-all">
                            {Object.entries(unresolvedAggregate.stats)
                              .map(([key, value]) => `${key}=${value}`)
                              .join(' | ')}
                          </div>
                        ) : null}
                        <details className="mt-2">
                          <summary className="cursor-pointer text-[11px] text-blue-600">
                            Show unresolved source entries
                          </summary>
                          <div className="mt-2 space-y-2">
                            {unresolvedDiscardedItems.map((source) => (
                              <div
                                key={`${source.id}-${source.reason_code}`}
                                className="rounded border border-border/50 p-2"
                              >
                                <div className="font-medium">{displaySourceTitle(source)}</div>
                                {source.label && source.label !== displaySourceTitle(source) ? (
                                  <div className="text-[11px] text-muted-foreground break-all">
                                    raw label: {source.label}
                                  </div>
                                ) : null}
                                <div className="text-muted-foreground">
                                  reason: {source.reason_code}
                                  {source.reason_detail ? ` | ${source.reason_detail}` : ''}
                                </div>
                              </div>
                            ))}
                          </div>
                        </details>
                      </div>
                    ) : null}
                    {(unresolvedAggregate && unresolvedAggregate.count >= REDIRECT_AGGREGATE_THRESHOLD
                      ? nonRedirectDiscardedItems
                      : report.discarded_sources
                    ).map((source) => (
                        <div key={`${source.id}-${source.reason_code}`} className="rounded border border-border/60 p-2">
                        <div className="font-medium break-words">
                          {displaySourceTitle(source)}
                        </div>
                        {source.label && source.label !== displaySourceTitle(source) ? (
                          <div className="text-[11px] text-muted-foreground break-all">
                            raw label: {source.label}
                          </div>
                        ) : null}
                        <div className="text-muted-foreground">
                          reason: {source.reason_code}
                          {source.reason_detail ? ` | ${source.reason_detail}` : ''}
                        </div>
                        {source.reason_meta ? (
                          <div className="text-[11px] text-muted-foreground">
                            resolver={source.reason_meta.resolver} | attempted=
                            {source.reason_meta.attempted ? 'yes' : 'no'}
                            {source.reason_meta.skipped_by_budget ? ' | budget-skipped=yes' : ''}
                            {typeof source.reason_meta.http_status === 'number'
                              ? ` | http=${source.reason_meta.http_status}`
                              : ''}
                            {source.reason_meta.error ? ` | error=${source.reason_meta.error}` : ''}
                          </div>
                        ) : null}
                        {source.final_url || source.url ? (
                          <a
                            href={source.final_url || source.url || '#'}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-block text-blue-600 hover:underline"
                          >
                            {source.final_url || source.url}
                          </a>
                        ) : null}
                        {source.raw_url && source.raw_url !== source.final_url ? (
                          <div className="text-[11px] text-muted-foreground break-all">
                            raw url: {source.raw_url}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="text-muted-foreground">No discarded sources recorded.</div>
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </div>
  )
}
