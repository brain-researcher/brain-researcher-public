import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'

const DEFAULT_TIMEOUT_MS = 20_000
const DEFAULT_PREFIX = '/api/hypothesis'
const HYPOTHESIS_TRANSIENT_STATUSES = new Set([404, 502, 503, 504])

const stripTrailingSlash = (value: string) => value.replace(/\/+$/, '')

const ensureLeadingSlash = (value: string) => (value.startsWith('/') ? value : `/${value}`)

const ensureNoLeadingSlash = (value: string) => value.replace(/^\/+/, '')

function resolveHypothesisPrefix(): string {
  const raw =
    process.env.BR_HYPOTHESIS_API_PREFIX ||
    process.env.HYPOTHESIS_API_PREFIX ||
    process.env.NEXT_PUBLIC_HYPOTHESIS_API_PREFIX ||
    DEFAULT_PREFIX
  return ensureLeadingSlash(raw)
}

export function resolveHypothesisBaseUrl(): string {
  const explicit =
    process.env.BR_HYPOTHESIS_API_BASE ||
    process.env.HYPOTHESIS_API_BASE ||
    process.env.HYPOTHESIS_BASE_URL ||
    process.env.NEXT_PUBLIC_HYPOTHESIS_API_BASE

  if (explicit && /^https?:\/\//i.test(explicit)) {
    return stripTrailingSlash(explicit)
  }

  const orchestratorBase = stripTrailingSlash(resolveOrchestratorBaseUrl())

  if (explicit) {
    const normalized = ensureLeadingSlash(explicit)
    return stripTrailingSlash(`${orchestratorBase}${normalized}`)
  }

  return stripTrailingSlash(`${orchestratorBase}${resolveHypothesisPrefix()}`)
}

export function shouldFallbackToLocalHypothesis(status: number): boolean {
  return HYPOTHESIS_TRANSIENT_STATUSES.has(status)
}

function buildUpstreamUrl(pathname: string, searchParams?: URLSearchParams): string {
  const base = resolveHypothesisBaseUrl()
  const pathPart = ensureNoLeadingSlash(pathname)
  const endpoint = `${base}/${pathPart}`
  const query = searchParams?.toString()
  return query ? `${endpoint}?${query}` : endpoint
}

export type ProxyHypothesisOptions = {
  method: 'GET' | 'POST'
  pathname: string
  searchParams?: URLSearchParams
  body?: unknown
  timeoutMs?: number
}

export async function proxyHypothesis(
  req: NextRequest,
  options: ProxyHypothesisOptions,
): Promise<NextResponse> {
  const url = buildUpstreamUrl(options.pathname, options.searchParams)
  const headers = forwardAuthHeaders(req)

  if (options.body !== undefined) {
    headers.set('content-type', 'application/json')
  }

  const controller = new AbortController()
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const upstream = await fetch(url, {
      method: options.method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
      signal: controller.signal,
    })

    const contentType = upstream.headers.get('content-type') || 'application/json'
    const raw = await upstream.text().catch(() => '')

    if (!upstream.ok) {
      let detail: unknown = null
      if (raw) {
        try {
          detail = JSON.parse(raw)
        } catch {
          detail = raw
        }
      }
      return NextResponse.json(
        {
          error: 'hypothesis_upstream_error',
          message: 'Hypothesis service request failed',
          upstream_status: upstream.status,
          detail,
        },
        { status: upstream.status },
      )
    }

    return new NextResponse(raw, {
      status: upstream.status,
      headers: {
        'content-type': contentType,
      },
    })
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json(
        {
          error: 'hypothesis_timeout',
          message: `Hypothesis service timed out after ${timeoutMs}ms`,
        },
        { status: 504 },
      )
    }

    return NextResponse.json(
      {
        error: 'hypothesis_proxy_failed',
        message: error instanceof Error ? error.message : 'Unknown hypothesis proxy error',
      },
      { status: 502 },
    )
  } finally {
    clearTimeout(timeoutId)
  }
}
