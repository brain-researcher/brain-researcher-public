import { NextRequest, NextResponse } from 'next/server'

import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import {
  isCanonicalJobArtifactPath,
  mustMatchAnalysisId,
  normalizeArtifactUrlPath,
  resolveSharedAnalysisAccess,
  shouldAllowSummaryArtifactPath,
} from '@/lib/server/share-access'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const PASSTHROUGH_HEADERS = [
  'content-type',
  'content-length',
  'content-disposition',
  'content-range',
  'accept-ranges',
  'etag',
  'last-modified',
] as const

function proxyResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers()
  for (const key of PASSTHROUGH_HEADERS) {
    const value = upstream.get(key)
    if (value) headers.set(key, value)
  }
  headers.set('cache-control', 'private, no-store, max-age=0')
  return headers
}

function isValidArtifactPath(path: string): boolean {
  const normalized = path.replace(/\\/g, '/')
  if (!normalized) return false
  if (normalized.includes('..')) return false
  if (normalized.startsWith('/')) return false
  if (normalized.includes('//')) return false
  if (normalized.includes('%')) return false
  if (normalized.includes('\0')) return false
  return true
}

function matchArtifactByRequest(
  artifact: Record<string, unknown>,
  requestPath: string,
  analysisId: string,
): boolean {
  const name = typeof artifact.name === 'string' ? artifact.name.trim() : ''
  if (name && requestPath === name) return true

  const artifactPath = typeof artifact.path === 'string' ? artifact.path.trim() : ''
  if (artifactPath && !artifactPath.startsWith('/')) {
    const normalizedPath = artifactPath.replace(/\\/g, '/')
    if (normalizedPath && requestPath === normalizedPath) return true
  }

  const jobPrefix = `/api/jobs/${analysisId}/artifacts/files/`
  const urlPath = normalizeArtifactUrlPath(artifact.url)
  if (urlPath?.startsWith(jobPrefix)) {
    const relativePath = urlPath.slice(jobPrefix.length)
    if (relativePath && requestPath === relativePath) return true
  }

  const downloadPath = normalizeArtifactUrlPath(artifact.download_url)
  if (downloadPath?.startsWith(jobPrefix)) {
    const relativePath = downloadPath.slice(jobPrefix.length)
    if (relativePath && requestPath === relativePath) return true
  }

  return false
}

function resolveCanonicalArtifactPath(
  artifact: Record<string, unknown>,
  analysisId: string,
): string | null {
  for (const candidate of [artifact.download_url, artifact.url]) {
    const normalized = normalizeArtifactUrlPath(candidate)
    if (!normalized) continue
    if (!isCanonicalJobArtifactPath(normalized)) continue
    if (!mustMatchAnalysisId(normalized, analysisId)) continue
    return normalized
  }
  return null
}

export async function GET(
  req: NextRequest,
  { params }: { params: { token: string; path: string[] } },
) {
  const token = typeof params.token === 'string' ? params.token.trim() : ''
  const resolved = await resolveSharedAnalysisAccess(token)
  if (resolved.ok === false) {
    return NextResponse.json(resolved.body, { status: resolved.status })
  }

  const artifactPath = params.path.join('/')
  const normalizedArtifactPath = artifactPath.replace(/\\/g, '/')
  if (!isValidArtifactPath(normalizedArtifactPath)) {
    return NextResponse.json({ detail: 'invalid artifact path.' }, { status: 400 })
  }

  const orchBase = resolveOrchestratorBaseUrl()
  const metadataHeaders = new Headers()
  if (process.env.NODE_ENV !== 'production') {
    const fallbackUser = process.env.DEMO_DEBUG_USER || process.env.DEV_CREDENTIALS_EMAIL
    if (fallbackUser) {
      metadataHeaders.set('x-debug-user', fallbackUser)
    }
  }

  let jobResponse: Response
  try {
    jobResponse = await fetch(`${orchBase}/api/jobs/${encodeURIComponent(resolved.analysisId)}`, {
      method: 'GET',
      headers: metadataHeaders,
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json({ detail: 'Upstream unavailable.' }, { status: 502 })
  }

  if (!jobResponse.ok) {
    const text = await jobResponse.text().catch(() => '')
    let json: Record<string, unknown> | null = null
    try {
      json = text ? (JSON.parse(text) as Record<string, unknown>) : null
    } catch {
      json = null
    }
    return NextResponse.json(json ?? { detail: text || jobResponse.statusText }, { status: jobResponse.status })
  }

  const jobData = (await jobResponse.json().catch(() => ({}))) as any
  const artifacts = Array.isArray(jobData?.artifacts)
    ? jobData.artifacts
    : Array.isArray(jobData?.job?.artifacts)
      ? jobData.job.artifacts
      : []

  const matches = artifacts.filter((artifact: Record<string, unknown>) =>
    matchArtifactByRequest(artifact, normalizedArtifactPath, resolved.analysisId),
  )
  if (!matches.length) {
    return NextResponse.json(
      { detail: `artifact "${normalizedArtifactPath}" not found in this analysis` },
      { status: 404 },
    )
  }
  if (matches.length > 1) {
    return NextResponse.json(
      { detail: `artifact "${normalizedArtifactPath}" is ambiguous` },
      { status: 409 },
    )
  }

  const upstreamPath = resolveCanonicalArtifactPath(matches[0], resolved.analysisId)
  if (!upstreamPath) {
    return NextResponse.json(
      { detail: 'Artifact is missing a canonical Orchestrator download URL.' },
      { status: 502 },
    )
  }

  if (resolved.shareLevel === 'summary' && !shouldAllowSummaryArtifactPath(upstreamPath)) {
    return NextResponse.json(
      { detail: 'This shared link is summary-only; this artifact is not available.' },
      { status: 403 },
    )
  }

  const downloadHeaders = new Headers(metadataHeaders)
  const range = req.headers.get('range')
  if (range) downloadHeaders.set('range', range)

  let upstream: Response
  try {
    upstream = await fetch(`${orchBase}${upstreamPath}`, {
      method: 'GET',
      headers: downloadHeaders,
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json({ detail: 'Failed to download artifact.' }, { status: 503 })
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: proxyResponseHeaders(upstream.headers),
  })
}
