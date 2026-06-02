'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'

type Confidence = 'high' | 'medium' | 'low' | 'unknown'

type SuggestionSource = {
  analysisId?: string
  createdAt?: number | string | null
}

type KgSuggestion = {
  id: string
  type: string
  target: string
  change: string
  confidence: Confidence
  source: SuggestionSource
  evidence: unknown
  raw: unknown
}

type SuggestionsResponse = {
  items: unknown[]
  count: number
  unavailable?: boolean
}

type SuggestionsPanelProps = {
  onCountChange?: (count: number) => void
}

type EvidenceSummary = {
  hasArtifact: boolean
  hasPaper: boolean
}

type EvidenceGate = {
  status: 'ok' | 'missing_evidence' | 'needs_verification'
  badge?: string
  message?: string
  blockAccept: boolean
}

type ProposedValue = {
  key: string
  value: string
}

type EvidenceLinks = {
  artifacts: { label: string; href?: string }[]
  papers: { label: string; href?: string }[]
}

function summarizeEvidence(evidence: unknown, depth = 0): EvidenceSummary {
  const summary: EvidenceSummary = { hasArtifact: false, hasPaper: false }
  if (!evidence) return summary
  if (depth > 3) return summary

  if (typeof evidence === 'string') {
    const text = evidence.toLowerCase()
    if (
      text.includes('doi') ||
      text.includes('pmid') ||
      text.includes('arxiv') ||
      text.includes('citation') ||
      text.includes('paper')
    ) {
      summary.hasPaper = true
    }
    if (
      text.includes('artifact') ||
      text.includes('download') ||
      text.includes('file') ||
      text.endsWith('.csv') ||
      text.endsWith('.tsv') ||
      text.endsWith('.json') ||
      text.endsWith('.html') ||
      text.endsWith('.pdf') ||
      text.endsWith('.nii') ||
      text.endsWith('.nii.gz') ||
      text.startsWith('http')
    ) {
      summary.hasArtifact = true
    }
    return summary
  }

  if (Array.isArray(evidence)) {
    for (const item of evidence) {
      const next = summarizeEvidence(item, depth + 1)
      summary.hasArtifact ||= next.hasArtifact
      summary.hasPaper ||= next.hasPaper
      if (summary.hasArtifact && summary.hasPaper) return summary
    }
    return summary
  }

  if (typeof evidence === 'object') {
    const record = evidence as Record<string, unknown>
    const keys = Object.keys(record).map((key) => key.toLowerCase())
    if (keys.some((key) => key.includes('artifact') || key.includes('file') || key.includes('path') || key === 'url')) {
      summary.hasArtifact = true
    }
    if (keys.some((key) => key === 'doi' || key === 'pmid' || key.includes('citation') || key.includes('paper'))) {
      summary.hasPaper = true
    }
    if (Array.isArray((record as any).artifacts) && (record as any).artifacts.length) {
      summary.hasArtifact = true
    }
    if (
      (Array.isArray((record as any).citations) && (record as any).citations.length) ||
      (Array.isArray((record as any).references) && (record as any).references.length) ||
      (Array.isArray((record as any).papers) && (record as any).papers.length)
    ) {
      summary.hasPaper = true
    }

    for (const value of Object.values(record)) {
      if (summary.hasArtifact && summary.hasPaper) return summary
      const next = summarizeEvidence(value, depth + 1)
      summary.hasArtifact ||= next.hasArtifact
      summary.hasPaper ||= next.hasPaper
    }
  }

  return summary
}

function gateSuggestion(confidence: Confidence, evidence: EvidenceSummary): EvidenceGate {
  if (confidence === 'low' || confidence === 'unknown') {
    return {
      status: 'needs_verification',
      badge: 'Needs verification',
      message: 'Low-confidence suggestions may be model inference and should be verified before accepting.',
      blockAccept: false,
    }
  }

  if (confidence === 'medium') {
    if (evidence.hasArtifact) return { status: 'ok', blockAccept: false }
    return {
      status: 'missing_evidence',
      badge: 'Missing artifact',
      message: 'Medium-confidence suggestions should include at least one artifact as evidence.',
      blockAccept: true,
    }
  }

  if (confidence === 'high') {
    if (evidence.hasArtifact || evidence.hasPaper) return { status: 'ok', blockAccept: false }
    return {
      status: 'missing_evidence',
      badge: 'Missing evidence',
      message: 'High-confidence suggestions must include an artifact or paper as evidence.',
      blockAccept: true,
    }
  }

  return { status: 'needs_verification', badge: 'Needs verification', blockAccept: false }
}

const normalizeConfidence = (value: unknown): Confidence => {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'high') return 'high'
  if (normalized === 'medium') return 'medium'
  if (normalized === 'low') return 'low'
  return 'unknown'
}

const humanizeType = (value: string) =>
  value
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')

const normalizeCreatedAt = (value: unknown): number | string | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) return value
  return null
}

function safeJsonStringify(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function toDisplayValue(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value instanceof Date) return value.toISOString()
  const json = safeJsonStringify(value)
  if (json.length <= 140) return json
  return `${json.slice(0, 140)}…`
}

const PROPOSED_VALUE_KEYS = [
  'proposed_values',
  'proposed',
  'values',
  'payload',
  'update',
  'updates',
  'change',
  'changes',
  'diff',
  'delta',
  'attributes',
  'relation',
  'weight',
  'p_value',
  'pvalue',
  'context',
] as const

function humanizeKey(key: string): string {
  return key
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
}

function extractProposedValues(suggestion: KgSuggestion): ProposedValue[] {
  const raw = suggestion.raw
  const candidates: ProposedValue[] = []

  const flatten = (value: unknown, prefix: string, depth: number) => {
    if (candidates.length >= 8) return
    if (depth > 2) return
    if (value == null) return

    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      const rendered = toDisplayValue(value)
      if (!rendered) return
      candidates.push({ key: prefix, value: rendered })
      return
    }

    if (Array.isArray(value)) {
      if (value.length === 0) return
      const rendered = value
        .slice(0, 3)
        .map((item) => toDisplayValue(item))
        .filter(Boolean)
        .join(', ')
      if (rendered) candidates.push({ key: prefix, value: rendered })
      return
    }

    if (typeof value === 'object') {
      const record = value as Record<string, unknown>
      const entries = Object.entries(record).filter(([k]) => k && !k.startsWith('_'))
      if (entries.length === 0) return
      for (const [childKey, childValue] of entries) {
        if (candidates.length >= 8) break
        const nextPrefix = prefix ? `${prefix}.${childKey}` : childKey
        if (typeof childValue === 'object' && childValue !== null && !Array.isArray(childValue)) {
          flatten(childValue, nextPrefix, depth + 1)
        } else {
          const rendered = toDisplayValue(childValue)
          if (rendered) candidates.push({ key: nextPrefix, value: rendered })
        }
      }
    }
  }

  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>
    for (const key of PROPOSED_VALUE_KEYS) {
      if (key in record && record[key] != null) {
        flatten(record[key], key, 0)
      }
    }
  }

  if (candidates.length === 0 && suggestion.change) {
    try {
      const parsed = JSON.parse(suggestion.change)
      flatten(parsed, 'change', 0)
    } catch {
      // ignore
    }
  }

  return candidates.slice(0, 8)
}

function extractEvidenceLinks(evidence: unknown): EvidenceLinks {
  const links: EvidenceLinks = { artifacts: [], papers: [] }
  const seen = new Set<string>()

  const push = (bucket: 'artifacts' | 'papers', label: string, href?: string) => {
    const normalized = `${bucket}:${label}:${href ?? ''}`
    if (seen.has(normalized)) return
    seen.add(normalized)
    links[bucket].push({ label, href })
  }

  const walk = (value: unknown, depth: number) => {
    if (depth > 4) return
    if (links.artifacts.length >= 6 && links.papers.length >= 6) return
    if (value == null) return

    if (typeof value === 'string') {
      const text = value.trim()
      if (!text) return
      const lower = text.toLowerCase()
      if (lower.startsWith('http')) {
        push('artifacts', text, text)
        return
      }
      if (lower.includes('doi') || lower.includes('pmid') || lower.includes('arxiv')) {
        push('papers', text)
        return
      }
      if (/\.(csv|tsv|json|html|pdf|nii|nii\.gz|png|jpg|jpeg)$/i.test(text)) {
        push('artifacts', text)
      }
      return
    }

    if (Array.isArray(value)) {
      for (const item of value) walk(item, depth + 1)
      return
    }

    if (typeof value === 'object') {
      const record = value as Record<string, unknown>
      const doi = record.doi
      if (typeof doi === 'string' && doi.trim()) {
        push('papers', `DOI: ${doi.trim()}`, doi.startsWith('http') ? doi : undefined)
      }
      const pmid = record.pmid
      if (typeof pmid === 'string' && pmid.trim()) {
        push('papers', `PMID: ${pmid.trim()}`)
      }

      const urlCandidates = [
        record.url,
        record.href,
        record.link,
        (record as any).download_url,
        (record as any).downloadUrl,
      ]
      for (const candidate of urlCandidates) {
        if (typeof candidate === 'string' && candidate.trim()) {
          push('artifacts', candidate.trim(), candidate.trim())
        }
      }

      const name = record.name
      if (typeof name === 'string' && name.trim()) {
        const maybeUrl =
          typeof record.url === 'string' && record.url.trim() ? record.url.trim() : undefined
        if (maybeUrl || /\.[a-z0-9]{2,5}(\.gz)?$/i.test(name.trim())) {
          push('artifacts', name.trim(), maybeUrl)
        }
      }

      for (const child of Object.values(record)) {
        walk(child, depth + 1)
      }
    }
  }

  walk(evidence, 0)
  return links
}

function normalizeSuggestion(item: unknown, index: number): KgSuggestion | null {
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return null
  }
  const record = item as Record<string, unknown>

  const idRaw =
    record.id ?? record.suggestion_id ?? record.suggestionId ?? record.uid ?? record.key
  const id = typeof idRaw === 'string' && idRaw.trim() ? idRaw.trim() : `suggestion-${index + 1}`

  const typeRaw = record.type ?? record.kind ?? record.action ?? 'suggestion'
  const type = typeof typeRaw === 'string' && typeRaw.trim() ? typeRaw.trim() : 'suggestion'

  const targetRaw = record.target ?? record.subject ?? record.edge ?? record.node ?? record.entity
  const target =
    typeof targetRaw === 'string' && targetRaw.trim()
      ? targetRaw.trim()
      : typeof record.title === 'string' && record.title.trim()
        ? record.title.trim()
        : 'Unknown target'

  const changeRaw =
    record.change ??
    record.summary ??
    record.description ??
    record.diff ??
    record.message ??
    record.details
  const change =
    typeof changeRaw === 'string'
      ? changeRaw.trim()
      : changeRaw
        ? JSON.stringify(changeRaw)
        : ''

  const confidence = normalizeConfidence(record.confidence)

  const source = (() => {
    const src = record.source
    if (src && typeof src === 'object' && !Array.isArray(src)) {
      const srcRec = src as Record<string, unknown>
      const analysisId = typeof srcRec.analysis_id === 'string' ? srcRec.analysis_id : undefined
      const createdAt = normalizeCreatedAt(srcRec.created_at)
      return { analysisId, createdAt }
    }
    const analysisId = typeof record.analysis_id === 'string' ? record.analysis_id : undefined
    const createdAt = normalizeCreatedAt(record.created_at)
    return { analysisId, createdAt }
  })()

  const evidence =
    record.evidence ??
    record.evidences ??
    record.references ??
    record.citations ??
    record.artifacts ??
    null

  return { id, type, target, change, confidence, source, evidence, raw: item }
}

const confidenceVariant = (confidence: Confidence) => {
  switch (confidence) {
    case 'high':
      return 'default'
    case 'medium':
      return 'secondary'
    case 'low':
      return 'outline'
    default:
      return 'outline'
  }
}

const formatCreatedAt = (value: number | string | null | undefined) => {
  if (!value) return null
  if (typeof value === 'number') {
    const ms = value > 1e11 ? value : value * 1000
    const dt = new Date(ms)
    return Number.isNaN(dt.getTime()) ? null : dt.toLocaleString()
  }
  if (typeof value === 'string') {
    const dt = new Date(value)
    return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString()
  }
  return null
}

export function SuggestionsPanel({ onCountChange }: SuggestionsPanelProps) {
  const { toast } = useToast()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [authRequired, setAuthRequired] = useState(false)
  const [items, setItems] = useState<KgSuggestion[]>([])
  const [reviewing, setReviewing] = useState<KgSuggestion | null>(null)
  const [mutatingId, setMutatingId] = useState<string | null>(null)
  const [confidenceFilter, setConfidenceFilter] = useState<Confidence | 'all'>('all')

  const fetchSuggestions = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    setUnavailable(false)
    setAuthRequired(false)

    try {
      const res = await fetch('/api/br-kg/suggestions', { cache: 'no-store' })
      if (res.status === 401) {
        setItems([])
        setAuthRequired(true)
        setError('Authentication required.')
        setUnavailable(false)
        return
      }
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `Failed to load suggestions (${res.status})`)
      }
      const data = (await res.json()) as SuggestionsResponse
      const normalized = (Array.isArray(data.items) ? data.items : [])
        .map(normalizeSuggestion)
        .filter(Boolean) as KgSuggestion[]
      setItems(normalized)
      setUnavailable(Boolean(data.unavailable))
    } catch (err) {
      setItems([])
      setUnavailable(true)
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchSuggestions()
  }, [fetchSuggestions])

  useEffect(() => {
    onCountChange?.(items.length)
  }, [items.length, onCountChange])

  const sorted = useMemo(() => {
    return [...items]
  }, [items])

  const filtered = useMemo(() => {
    if (confidenceFilter === 'all') return sorted
    return sorted.filter((item) => item.confidence === confidenceFilter)
  }, [confidenceFilter, sorted])

  const mutate = useCallback(
    async (id: string, action: 'accept' | 'reject') => {
      if (!id) return
      setMutatingId(id)
      try {
        const res = await fetch(
          `/api/br-kg/suggestions/${encodeURIComponent(id)}/${action}`,
          { method: 'POST' },
        )
        if (res.status === 401) {
          throw new Error('Authentication required.')
        }
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          let detail = text
          if (text) {
            try {
              const parsed = JSON.parse(text) as any
              detail = parsed?.detail || parsed?.error || text
            } catch {
              // ignore
            }
          }
          if (res.status === 501) {
            toast({
              title: 'Not implemented yet',
              description: detail || 'Suggestions endpoint not available.',
            })
            return
          }
          throw new Error(detail || `${action} failed (${res.status})`)
        }
        setItems((prev) => prev.filter((item) => item.id !== id))
        toast({
          title: action === 'accept' ? 'Suggestion accepted' : 'Suggestion rejected',
        })
      } catch (err) {
        toast({
          title: 'Action failed',
          description: err instanceof Error ? err.message : String(err),
          variant: 'destructive',
        })
      } finally {
        setMutatingId(null)
      }
    },
    [toast],
  )

  if (isLoading && items.length === 0) {
    return (
      <div className="rounded-2xl border bg-card p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading suggestions…
        </div>
      </div>
    )
  }

  if (!isLoading && sorted.length === 0) {
    return (
      <div className="space-y-4">
        {authRequired ? (
          <div className="rounded-2xl border bg-card p-6 space-y-3">
            <div className="text-sm font-medium">Sign in to review suggestions</div>
            <div className="text-sm text-muted-foreground">
              Knowledge Graph suggestions are tied to your analyses and require authentication.
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild size="sm">
                <Link href={`/auth/login?callbackUrl=${encodeURIComponent('/kg?tab=suggestions')}`}>
                  Sign in
                </Link>
              </Button>
              <Button size="sm" variant="outline" onClick={fetchSuggestions}>
                Retry
              </Button>
            </div>
          </div>
        ) : error ? (
          <Alert variant="destructive">
            <AlertTitle>Suggestions unavailable</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="rounded-2xl border bg-card p-6">
          <div className="text-sm font-medium">No pending suggestions</div>
          <div className="mt-1 text-sm text-muted-foreground">
            When you complete analyses, findings that can enhance the Knowledge Graph will appear here for your review.
            {unavailable ? (
              <span className="ml-2">
                (Suggestions backend not available yet.)
              </span>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button asChild size="sm">
              <Link href="/studio">Go to Studio</Link>
            </Button>
            <Button size="sm" variant="outline" onClick={fetchSuggestions}>
              Refresh
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          {sorted.length} pending suggestion{sorted.length === 1 ? '' : 's'}
          {confidenceFilter !== 'all' ? (
            <span className="ml-2 text-xs text-muted-foreground">
              • Showing {filtered.length}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={confidenceFilter}
            onValueChange={(value) => setConfidenceFilter(value as Confidence | 'all')}
          >
            <SelectTrigger className="h-8 w-[150px]">
              <SelectValue placeholder="Filters" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="low">Low</SelectItem>
              <SelectItem value="unknown">Unknown</SelectItem>
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" onClick={fetchSuggestions} disabled={isLoading}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Refresh'}
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {sorted.length > 0 && filtered.length === 0 ? (
          <div className="rounded-2xl border bg-card p-6">
            <div className="text-sm font-medium">No suggestions match your filters</div>
            <div className="mt-1 text-sm text-muted-foreground">
              Clear the filter to view all pending suggestions.
            </div>
            <div className="mt-4">
              <Button size="sm" variant="outline" onClick={() => setConfidenceFilter('all')}>
                Clear filters
              </Button>
            </div>
          </div>
        ) : null}
        {filtered.map((suggestion) => (
          <Card key={suggestion.id}>
            <CardContent className="p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  {(() => {
                    const evidenceSummary = summarizeEvidence(suggestion.evidence)
                    const gate = gateSuggestion(suggestion.confidence, evidenceSummary)
                    const gateBadgeVariant =
                      gate.status === 'missing_evidence'
                        ? 'destructive'
                        : gate.status === 'needs_verification'
                          ? 'outline'
                          : 'outline'

                    return (
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="text-xs">
                      {humanizeType(suggestion.type)}
                    </Badge>
                    {suggestion.confidence !== 'unknown' ? (
                      <Badge variant={confidenceVariant(suggestion.confidence)} className="text-xs">
                        {suggestion.confidence}
                      </Badge>
                    ) : null}
                    {gate.badge ? (
                      <Badge variant={gateBadgeVariant} className="text-xs">
                        {gate.badge}
                      </Badge>
                    ) : null}
                  </div>
                    )
                  })()}

                  <div className="mt-2 text-sm font-medium">
                    {suggestion.target}
                  </div>

                  {suggestion.change ? (
                    <div className="mt-1 text-sm text-muted-foreground">
                      {suggestion.change}
                    </div>
                  ) : null}

                  {suggestion.source.analysisId ? (
                    <div className="mt-2 text-xs text-muted-foreground">
                      Source: Analysis{' '}
                      <Link
                        className="text-primary underline"
                        href={`/analyses/${encodeURIComponent(suggestion.source.analysisId)}`}
                      >
                        {suggestion.source.analysisId.slice(0, 8)}
                      </Link>
                      {formatCreatedAt(suggestion.source.createdAt) ? (
                        <span className="ml-2">
                          • {formatCreatedAt(suggestion.source.createdAt)}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
	                  {(() => {
	                    const evidenceSummary = summarizeEvidence(suggestion.evidence)
	                    const gate = gateSuggestion(suggestion.confidence, evidenceSummary)
	                    return (
	                      <>
	                        <Button
	                          size="sm"
	                          variant="outline"
	                          onClick={() => setReviewing(suggestion)}
	                        >
	                          Review
	                        </Button>
	                        <Button
	                          size="sm"
	                          onClick={() => void mutate(suggestion.id, 'accept')}
	                          disabled={mutatingId === suggestion.id || gate.blockAccept}
	                          title={gate.blockAccept ? gate.message : undefined}
	                        >
	                          Accept
	                        </Button>
	                        <Button
	                          size="sm"
	                          variant="ghost"
	                          onClick={() => void mutate(suggestion.id, 'reject')}
	                          disabled={mutatingId === suggestion.id}
	                        >
	                          Reject
	                        </Button>
	                      </>
	                    )
	                  })()}
	                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={Boolean(reviewing)} onOpenChange={(open) => !open && setReviewing(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Review Suggestion</DialogTitle>
            <DialogDescription>
              Review the proposed Knowledge Graph update before accepting or rejecting it.
            </DialogDescription>
          </DialogHeader>

          {reviewing ? (
            <div className="space-y-4">
              {(() => {
                const evidenceSummary = summarizeEvidence(reviewing.evidence)
                const gate = gateSuggestion(reviewing.confidence, evidenceSummary)
                if (gate.status === 'ok') return null
                const variant = gate.status === 'missing_evidence' ? 'warning' : 'warning'
                return (
                  <Alert variant={variant}>
                    <AlertTitle>
                      {gate.status === 'missing_evidence' ? 'Evidence required' : 'Needs verification'}
                    </AlertTitle>
                    <AlertDescription>{gate.message}</AlertDescription>
                  </Alert>
                )
              })()}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">Type</div>
                  <div className="text-sm font-medium">{humanizeType(reviewing.type)}</div>
                </div>
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">Confidence</div>
                  <div className="text-sm font-medium">{reviewing.confidence}</div>
                </div>
              </div>

              <div className="rounded-lg border bg-muted/20 p-3">
                <div className="text-xs text-muted-foreground">Target</div>
                <div className="text-sm font-medium">{reviewing.target}</div>
                {reviewing.change ? (
                  <div className="mt-1 text-sm text-muted-foreground">{reviewing.change}</div>
                ) : null}
              </div>

              {(() => {
                const proposed = extractProposedValues(reviewing)
                if (proposed.length === 0) return null
                return (
                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="text-xs text-muted-foreground">Proposed values</div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {proposed.map((item) => (
                        <li key={item.key} className="flex flex-wrap items-baseline gap-2">
                          <span className="text-muted-foreground">{humanizeKey(item.key)}:</span>
                          <span className="font-medium break-all">{item.value}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })()}

              {reviewing.source.analysisId ? (
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">Source</div>
                  <div className="mt-1 text-sm">
                    <Link
                      className="text-primary underline"
                      href={`/analyses/${encodeURIComponent(reviewing.source.analysisId)}`}
                    >
                      {reviewing.source.analysisId}
                    </Link>
                    {formatCreatedAt(reviewing.source.createdAt) ? (
                      <span className="ml-2 text-sm text-muted-foreground">
                        ({formatCreatedAt(reviewing.source.createdAt)})
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {reviewing.evidence ? (
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">Evidence</div>
                  {(() => {
                    const extracted = extractEvidenceLinks(reviewing.evidence)
                    const hasLists = extracted.artifacts.length > 0 || extracted.papers.length > 0
                    return (
                      <>
                        {hasLists ? (
                          <div className="mt-2 space-y-3 text-sm">
                            {extracted.artifacts.length ? (
                              <div>
                                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                                  Artifacts
                                </div>
                                <ul className="mt-1 space-y-1">
                                  {extracted.artifacts.slice(0, 5).map((item) => (
                                    <li key={`${item.label}:${item.href ?? ''}`} className="break-all">
                                      {item.href ? (
                                        <a
                                          className="text-primary underline"
                                          href={item.href}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          {item.label}
                                        </a>
                                      ) : (
                                        item.label
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {extracted.papers.length ? (
                              <div>
                                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                                  Supporting
                                </div>
                                <ul className="mt-1 space-y-1">
                                  {extracted.papers.slice(0, 5).map((item) => (
                                    <li key={`${item.label}:${item.href ?? ''}`} className="break-all">
                                      {item.href ? (
                                        <a
                                          className="text-primary underline"
                                          href={item.href}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          {item.label}
                                        </a>
                                      ) : (
                                        item.label
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-background p-3 text-xs">
                          {JSON.stringify(reviewing.evidence, null, 2)}
                        </pre>
                      </>
                    )
                  })()}
                </div>
              ) : (
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">Evidence</div>
                  <div className="mt-1 text-sm text-muted-foreground">No evidence provided.</div>
                </div>
              )}

              <div className="rounded-lg border bg-muted/20 p-3">
                <div className="text-xs text-muted-foreground">Raw payload</div>
                <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-background p-3 text-xs">
                  {JSON.stringify(reviewing.raw, null, 2)}
                </pre>
              </div>

              <div className="sticky bottom-0 -mx-6 mt-4 border-t bg-background px-6 py-4">
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button asChild variant="secondary">
                    <Link
                      href={`/studio?prompt=${encodeURIComponent(
                        [
                          'I have a BR-KG suggestion I want to review and refine.',
                          `Type: ${reviewing.type}`,
                          `Target: ${reviewing.target}`,
                          reviewing.change ? `Change: ${reviewing.change}` : '',
                          '',
                          'Please propose improvements, required evidence, and a safe apply plan.',
                        ]
                          .filter(Boolean)
                          .join('\n'),
                      )}`}
                    >
                      Ask Agent
                    </Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link
                      href={`/studio?prompt=${encodeURIComponent(
                        [
                          'I want to accept this BR-KG suggestion, but with edits.',
                          `Suggestion ID: ${reviewing.id}`,
                          `Type: ${reviewing.type}`,
                          `Target: ${reviewing.target}`,
                          reviewing.change ? `Change summary: ${reviewing.change}` : '',
                          '',
                          'Please propose edited fields (as a JSON snippet) and explain what evidence is required.',
                        ]
                          .filter(Boolean)
                          .join('\n'),
                      )}`}
                    >
                      Accept with edits
                    </Link>
                  </Button>
                  <Button variant="ghost" onClick={() => setReviewing(null)}>
                    Close
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      if (!reviewing) return
                      void mutate(reviewing.id, 'reject')
                      setReviewing(null)
                    }}
                    disabled={mutatingId === reviewing.id}
                  >
                    Reject
                  </Button>
                  <Button
                    onClick={() => {
                      if (!reviewing) return
                      void mutate(reviewing.id, 'accept')
                      setReviewing(null)
                    }}
                    disabled={
                      mutatingId === reviewing.id ||
                      gateSuggestion(reviewing.confidence, summarizeEvidence(reviewing.evidence)).blockAccept
                    }
                  >
                    Accept
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
