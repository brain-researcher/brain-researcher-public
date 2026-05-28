const TRACKING_QUERY_KEYS = new Set([
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_term',
  'utm_content',
  'utm_id',
  'gclid',
  'fbclid',
  'msclkid',
  'mc_cid',
  'mc_eid',
  '_hsenc',
  '_hsmi',
  'igshid',
])

const REDIRECT_QUERY_KEYS = [
  'url',
  'uri',
  'u',
  'q',
  'target',
  'redirect',
  'dest',
  'destination',
  'link',
]

const GROUNDING_REDIRECT_PATH = /grounding-api-redirect/i
const GROUNDING_REDIRECT_HOSTS = [/vertexaisearch\.cloud\.google\.com$/i]

type SourceType = 'paper' | 'dataset' | 'other'
export type EvidenceQualityTier = 'primary' | 'secondary' | 'tertiary'

const DOI_PATTERN = /\b10\.\d{4,9}\/[-._;()/:a-z0-9]+\b/i
const PMID_PATTERN = /\bpmid[:\s]*\d{4,}\b/i
const ARXIV_ID_PATTERN = /\barxiv\.org\/(abs|pdf)\/\d{4}\.\d{4,5}\b/i
const DATASET_ID_PATTERN =
  /\b(openneuro\.org\/datasets\/[a-z0-9_-]+|dandiarchive\.org\/dandiset\/\d{6}|zenodo\.org\/record\/\d+)\b/i

const PRIMARY_HOST_PATTERNS = [
  /(?:^|\.)doi\.org$/i,
  /(?:^|\.)pubmed\.ncbi\.nlm\.nih\.gov$/i,
  /(?:^|\.)ncbi\.nlm\.nih\.gov$/i,
  /(?:^|\.)arxiv\.org$/i,
  /(?:^|\.)biorxiv\.org$/i,
  /(?:^|\.)medrxiv\.org$/i,
  /(?:^|\.)nature\.com$/i,
  /(?:^|\.)science\.org$/i,
  /(?:^|\.)cell\.com$/i,
  /(?:^|\.)openneuro\.org$/i,
  /(?:^|\.)dandiarchive\.org$/i,
  /(?:^|\.)zenodo\.org$/i,
  /(?:^|\.)figshare\.com$/i,
]

export type NormalizedEvidenceUrl = {
  rawUrl: string | null
  url: string | null
  finalUrl: string | null
  displayUrl: string | null
  sourceHost: string | null
  resolution: {
    attempted: boolean
    resolvedVia: 'none' | 'query_param' | 'head' | 'get'
    httpStatus: number | null
    error: string | null
    skippedByBudget: boolean
    isGroundingRedirect: boolean
  }
}

function toUrl(value: string | null | undefined): URL | null {
  if (!value || typeof value !== 'string') return null
  const normalized = value.trim()
  if (!normalized) return null
  try {
    const url = new URL(normalized)
    if (!/^https?:$/i.test(url.protocol)) return null
    return url
  } catch {
    return null
  }
}

function canonicalizeUrlObject(url: URL): string {
  const protocol = url.protocol.toLowerCase()
  const hostname = url.hostname.toLowerCase().replace(/^www\./i, '')
  const port = url.port
  const keepPort =
    port && !((protocol === 'http:' && port === '80') || (protocol === 'https:' && port === '443'))
  const path = url.pathname === '/' ? '' : url.pathname || ''
  const searchParams = new URLSearchParams(url.search)
  const keysToDelete: string[] = []
  searchParams.forEach((_, key) => {
    if (TRACKING_QUERY_KEYS.has(key.toLowerCase())) {
      keysToDelete.push(key)
    }
  })
  for (const key of keysToDelete) {
    searchParams.delete(key)
  }

  const sortedParams = Array.from(searchParams.entries()).sort(([a], [b]) => a.localeCompare(b))
  const query = new URLSearchParams(sortedParams)

  const authority = keepPort ? `${hostname}:${port}` : hostname
  const queryText = query.toString()
  return `${protocol}//${authority}${path}${queryText ? `?${queryText}` : ''}`
}

export function canonicalizeUrl(url: string | null | undefined): string | null {
  const parsed = toUrl(url)
  if (!parsed) return null
  return canonicalizeUrlObject(parsed)
}

function decodeCandidateUrl(value: string | null): string | null {
  if (!value) return null
  let candidate = value.trim()
  if (!candidate) return null
  for (let i = 0; i < 2; i += 1) {
    try {
      const decoded = decodeURIComponent(candidate)
      if (decoded === candidate) break
      candidate = decoded
    } catch {
      break
    }
  }
  return canonicalizeUrl(candidate)
}

function extractRedirectTarget(url: URL): string | null {
  for (const key of REDIRECT_QUERY_KEYS) {
    const raw = url.searchParams.get(key)
    const decoded = decodeCandidateUrl(raw)
    if (decoded) return decoded
  }
  return null
}

function isGroundingRedirectUrl(url: URL): boolean {
  if (GROUNDING_REDIRECT_PATH.test(url.pathname)) return true
  return GROUNDING_REDIRECT_HOSTS.some((pattern) => pattern.test(url.hostname))
}

async function fetchRedirectLocation(args: {
  url: string
  timeoutMs: number
}): Promise<{
  url: string | null
  resolvedVia: 'head' | 'get' | 'none'
  httpStatus: number | null
  error: string | null
}> {
  let lastError: string | null = null
  let lastStatus: number | null = null
  for (const method of ['HEAD', 'GET'] as const) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), args.timeoutMs)
    try {
      const response = await fetch(args.url, {
        method,
        redirect: 'manual',
        cache: 'no-store',
        signal: controller.signal,
      })
      const location = response.headers.get('location')
      lastStatus = response.status
      if (location) {
        const resolved = canonicalizeUrl(new URL(location, args.url).toString())
        if (resolved) {
          return {
            url: resolved,
            resolvedVia: method === 'HEAD' ? 'head' : 'get',
            httpStatus: response.status,
            error: null,
          }
        }
      }
      if (response.redirected && response.url) {
        const redirected = canonicalizeUrl(response.url)
        if (redirected) {
          return {
            url: redirected,
            resolvedVia: method === 'HEAD' ? 'head' : 'get',
            httpStatus: response.status,
            error: null,
          }
        }
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : 'network_error'
    } finally {
      clearTimeout(timeout)
    }
  }
  return {
    url: null,
    resolvedVia: 'none',
    httpStatus: lastStatus,
    error: lastError,
  }
}

export function isGroundingRedirectCandidate(url: string | null | undefined): boolean {
  const parsed = toUrl(url || null)
  if (!parsed) return false
  return isGroundingRedirectUrl(parsed)
}

export async function resolveGroundingRedirectWithMeta(args: {
  url: string | null | undefined
  timeoutMs?: number
  maxHops?: number
  allowNetworkResolve?: boolean
}): Promise<{
  url: string | null
  attempted: boolean
  resolvedVia: 'none' | 'query_param' | 'head' | 'get'
  httpStatus: number | null
  error: string | null
  isGroundingRedirect: boolean
}> {
  const timeoutMs = Math.max(250, Math.trunc(args.timeoutMs ?? 1_800))
  const maxHops = Math.max(1, Math.trunc(args.maxHops ?? 3))
  const allowNetworkResolve = args.allowNetworkResolve !== false
  let current = canonicalizeUrl(args.url)
  if (!current) {
    return {
      url: null,
      attempted: false,
      resolvedVia: 'none',
      httpStatus: null,
      error: null,
      isGroundingRedirect: false,
    }
  }

  const seen = new Set<string>()
  let attempted = false
  let resolvedVia: 'none' | 'query_param' | 'head' | 'get' = 'none'
  let httpStatus: number | null = null
  let error: string | null = null
  let isGroundingRedirect = false

  for (let hop = 0; hop < maxHops; hop += 1) {
    if (seen.has(current)) break
    seen.add(current)

    const parsed = toUrl(current)
    if (!parsed) break

    const target = extractRedirectTarget(parsed)
    if (target && target !== current) {
      current = target
      attempted = true
      resolvedVia = 'query_param'
      continue
    }

    if (!isGroundingRedirectUrl(parsed)) break
    isGroundingRedirect = true
    if (!allowNetworkResolve) {
      break
    }

    attempted = true
    const fetched = await fetchRedirectLocation({
      url: current,
      timeoutMs,
    })
    httpStatus = fetched.httpStatus
    if (fetched.error) error = fetched.error
    if (!fetched.url || fetched.url === current) break
    current = fetched.url
    if (fetched.resolvedVia === 'head' || fetched.resolvedVia === 'get') {
      resolvedVia = fetched.resolvedVia
    }
  }

  return {
    url: current,
    attempted,
    resolvedVia,
    httpStatus,
    error,
    isGroundingRedirect,
  }
}

export async function resolveGroundingRedirect(args: {
  url: string | null | undefined
  timeoutMs?: number
  maxHops?: number
}): Promise<string | null> {
  const resolved = await resolveGroundingRedirectWithMeta(args)
  return resolved.url
}

export function sourceHostFromUrl(url: string | null | undefined): string | null {
  const parsed = toUrl(url)
  if (!parsed) return null
  return parsed.hostname.replace(/^www\./i, '').toLowerCase()
}

export function displayUrlFromUrl(url: string | null | undefined, maxLength = 96): string | null {
  const parsed = toUrl(url)
  if (!parsed) return null
  const host = parsed.hostname.replace(/^www\./i, '')
  const suffix = parsed.search ? `${parsed.pathname}${parsed.search}` : parsed.pathname
  let text = `${host}${suffix}`
  if (text.endsWith('/')) text = text.slice(0, -1)
  if (!text) text = host
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 3)}...`
}

export function inferSourceType(url: string | null | undefined, title?: string | null): SourceType {
  const value = `${url || ''} ${title || ''}`.toLowerCase()
  if (
    value.includes('openneuro') ||
    value.includes('dandi') ||
    value.includes('figshare') ||
    value.includes('zenodo') ||
    value.includes('dataset')
  ) {
    return 'dataset'
  }
  if (
    value.includes('pubmed') ||
    value.includes('doi.org') ||
    value.includes('arxiv') ||
    value.includes('biorxiv') ||
    value.includes('paper') ||
    value.includes('journal')
  ) {
    return 'paper'
  }
  return 'other'
}

function hasStableIdentifier(url: string | null | undefined, title?: string | null): boolean {
  const combined = `${url || ''} ${title || ''}`.toLowerCase()
  return (
    DOI_PATTERN.test(combined) ||
    PMID_PATTERN.test(combined) ||
    ARXIV_ID_PATTERN.test(combined) ||
    DATASET_ID_PATTERN.test(combined)
  )
}

function hasPrimaryHost(url: string | null | undefined): boolean {
  const host = sourceHostFromUrl(url)
  if (!host) return false
  return PRIMARY_HOST_PATTERNS.some((pattern) => pattern.test(host))
}

function roundScore(value: number): number {
  return Math.max(0, Math.min(1, Number(value.toFixed(2))))
}

export function inferEvidenceQuality(args: {
  url?: string | null
  title?: string | null
  kind?: string | null
  sourceType?: SourceType | null
}): {
  tier: EvidenceQualityTier
  traceabilityScore: number
} {
  const normalizedUrl = canonicalizeUrl(args.url)
  const sourceType =
    args.sourceType ||
    inferSourceType(normalizedUrl, typeof args.title === 'string' ? args.title : null)
  const hasUrl = Boolean(normalizedUrl)
  const hasHost = Boolean(sourceHostFromUrl(normalizedUrl))
  const stableIdentifier = hasStableIdentifier(normalizedUrl, args.title)
  const primaryHost = hasPrimaryHost(normalizedUrl)
  const kind = (args.kind || '').toLowerCase()
  const looksStructuredKind = kind === 'paper' || kind === 'dataset'
  const tier: EvidenceQualityTier =
    hasUrl && (stableIdentifier || primaryHost)
      ? 'primary'
      : hasUrl && hasHost && (looksStructuredKind || sourceType !== 'other')
        ? 'secondary'
        : 'tertiary'

  const score =
    (hasUrl ? 0.25 : 0) +
    (hasHost ? 0.15 : 0) +
    (sourceType !== 'other' || looksStructuredKind ? 0.2 : 0) +
    (stableIdentifier ? 0.3 : 0) +
    (primaryHost ? 0.1 : 0)

  return {
    tier,
    traceabilityScore: roundScore(score),
  }
}

function looksGeneratedLabel(label: string): boolean {
  const value = label.trim().toLowerCase()
  return (
    /^nested-\d+$/.test(value) ||
    /^doc[_-]?\d+$/.test(value) ||
    /^source\s+\d+$/.test(value) ||
    /^untitled/.test(value)
  )
}

function pathToTitle(pathname: string): string | null {
  const cleaned = pathname
    .split('/')
    .map((part) => part.trim())
    .filter(Boolean)
    .pop()
  if (!cleaned) return null
  const plain = cleaned
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!plain) return null
  return plain[0].toUpperCase() + plain.slice(1)
}

export function buildReadableLabel(args: {
  title?: string | null
  url?: string | null
  fallbackId?: string | null
  index?: number
}): string {
  const title = typeof args.title === 'string' ? args.title.trim() : ''
  if (title && !looksGeneratedLabel(title)) return title

  const parsed = toUrl(args.url || null)
  if (parsed) {
    const host = parsed.hostname.replace(/^www\./i, '')
    const fromPath = pathToTitle(parsed.pathname)
    if (fromPath) return `${fromPath} (${host})`
    return host
  }

  const fallback = typeof args.fallbackId === 'string' ? args.fallbackId.trim() : ''
  if (fallback && !looksGeneratedLabel(fallback)) return fallback
  return `Source ${(args.index ?? 0) + 1}`
}

export async function normalizeEvidenceUrl(args: {
  url?: string | null
  resolveRedirects?: boolean
  allowNetworkResolve?: boolean
  skippedByBudget?: boolean
  timeoutMs?: number
  maxHops?: number
}): Promise<NormalizedEvidenceUrl> {
  const rawUrl = typeof args.url === 'string' ? args.url.trim() || null : null
  const canonical = canonicalizeUrl(rawUrl)
  const resolved = await resolveGroundingRedirectWithMeta({
    url: canonical,
    timeoutMs: args.timeoutMs,
    maxHops: args.maxHops,
    allowNetworkResolve:
      args.resolveRedirects === false ? false : args.allowNetworkResolve !== false,
  })
  const finalUrl = resolved.url || canonical
  return {
    rawUrl,
    url: finalUrl,
    finalUrl,
    displayUrl: displayUrlFromUrl(finalUrl),
    sourceHost: sourceHostFromUrl(finalUrl),
    resolution: {
      attempted: resolved.attempted,
      resolvedVia: resolved.resolvedVia,
      httpStatus: resolved.httpStatus,
      error: resolved.error,
      skippedByBudget: Boolean(args.skippedByBudget),
      isGroundingRedirect: resolved.isGroundingRedirect,
    },
  }
}

export function isUnresolvedGroundingRedirect(url: string | null | undefined): boolean {
  const parsed = toUrl(url || null)
  if (!parsed) return false
  if (!isGroundingRedirectUrl(parsed)) return false
  return !extractRedirectTarget(parsed)
}
