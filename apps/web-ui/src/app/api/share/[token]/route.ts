import { NextRequest, NextResponse } from 'next/server'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
import { resolveSharedAnalysisAccess } from '@/lib/server/share-access'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function shouldIncludeArtifactInSummary(artifact: any): boolean {
  const name = String(artifact?.name || artifact?.file_name || artifact?.fileName || artifact?.id || '')
    .trim()
    .toLowerCase()
  const kind = String(artifact?.type || artifact?.mime_type || artifact?.mimeType || '')
    .trim()
    .toLowerCase()

  if (kind.includes('log')) return false
  if (name.includes('stdout') || name.includes('stderr')) return false
  if (name.endsWith('.log')) return false
  if (name.endsWith('.nii') || name.endsWith('.nii.gz')) return false

  return true
}

export async function GET(_req: NextRequest, { params }: { params: { token: string } }) {
  const token = typeof params.token === 'string' ? params.token.trim() : ''
  const resolved = await resolveSharedAnalysisAccess(token)
  if (resolved.ok === false) {
    return NextResponse.json(resolved.body, { status: resolved.status })
  }

  const headers = new Headers()
  const result = await buildAnalysisDetail({
    analysisId: resolved.analysisId,
    headers,
  })

  if (!result.ok) {
    const payload = 'body' in result ? result.body : { detail: 'Unknown error' }
    const status = 'status' in result ? result.status : 500
    return NextResponse.json(payload, { status })
  }

  const artifacts = Array.isArray(result.detail.artifacts) ? result.detail.artifacts : []
  const detail = {
    ...result.detail,
    artifacts:
      resolved.shareLevel === 'summary'
        ? artifacts.filter((a: any) => shouldIncludeArtifactInSummary(a))
        : artifacts,
  }

  const warnings = [
    ...(detail.warnings ?? []),
    `This is a shared link (${resolved.shareLevel === 'full' ? 'full artifacts' : 'summary only'}).`,
    resolved.expiresAt
      ? `Shared link expires at ${resolved.expiresAt}.`
      : 'Shared link expiration is unknown.',
  ]

  return NextResponse.json({
    ...detail,
    warnings,
    share_level: resolved.shareLevel,
  })
}

export async function DELETE(req: NextRequest, { params }: { params: { token: string } }) {
  const token = typeof params.token === 'string' ? params.token.trim() : ''
  if (!token) {
    return NextResponse.json({ detail: 'token is required.' }, { status: 400 })
  }

  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
  }

  const headers = forwardAuthHeaders(req)
  const orchBase = resolveOrchestratorBaseUrl()
  let upstream: Response
  try {
    upstream = await fetch(`${orchBase}/api/share/${encodeURIComponent(token)}`, {
      method: 'DELETE',
      headers,
      cache: 'no-store',
    })
  } catch {
    return NextResponse.json({ detail: 'Upstream unavailable.' }, { status: 502 })
  }

  const text = await upstream.text().catch(() => '')
  let json: any = null
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    json = null
  }

  if (!upstream.ok) {
    return NextResponse.json(json ?? { detail: text || upstream.statusText }, { status: upstream.status })
  }

  return NextResponse.json(json ?? { revoked: true }, { status: 200 })
}
