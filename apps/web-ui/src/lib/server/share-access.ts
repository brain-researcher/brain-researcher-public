import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'

export type ResolvedShareAccess = {
  analysisId: string
  shareLevel: 'summary' | 'full'
  expiresAt?: string
}

export type ShareAccessResult =
  | ({ ok: true } & ResolvedShareAccess)
  | { ok: false; status: number; body: Record<string, unknown> }

async function parseUpstreamError(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text().catch(() => '')
  let json: Record<string, unknown> | null = null
  try {
    json = text ? (JSON.parse(text) as Record<string, unknown>) : null
  } catch {
    json = null
  }
  return json ?? { detail: text || res.statusText }
}

export async function resolveSharedAnalysisAccess(token: string): Promise<ShareAccessResult> {
  const trimmed = typeof token === 'string' ? token.trim() : ''
  if (!trimmed) {
    return { ok: false, status: 400, body: { detail: 'token is required.' } }
  }

  const orchBase = resolveOrchestratorBaseUrl()
  let res: Response
  try {
    res = await fetch(`${orchBase}/api/share/${encodeURIComponent(trimmed)}`, {
      method: 'GET',
      cache: 'no-store',
    })
  } catch {
    return { ok: false, status: 502, body: { detail: 'Upstream unavailable.' } }
  }

  if (!res.ok) {
    return { ok: false, status: res.status, body: await parseUpstreamError(res) }
  }

  const share = (await res.json().catch(() => null)) as any
  const analysisId = String(share?.analysis_id ?? share?.analysisId ?? '').trim()
  if (!analysisId) {
    return { ok: false, status: 502, body: { detail: 'Share token could not be resolved.' } }
  }

  const shareLevelRaw = String(share?.share_level ?? share?.shareLevel ?? 'summary')
    .trim()
    .toLowerCase()
  const shareLevel: 'summary' | 'full' = shareLevelRaw === 'full' ? 'full' : 'summary'
  const expiresAt = String(share?.expires_at ?? share?.expiresAt ?? '').trim() || undefined

  return {
    ok: true,
    analysisId,
    shareLevel,
    expiresAt,
  }
}

export function normalizeArtifactUrlPath(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const [pathOnly] = trimmed.split(/[?#]/, 1)
  if (!pathOnly.startsWith('/')) return null
  return pathOnly
}

export function shouldAllowSummaryArtifactPath(path: string): boolean {
  const pathname = path.split('?', 1)[0]
  const filename = pathname.split('/').pop()?.toLowerCase() ?? ''

  if (!filename) return false
  if (filename.includes('stdout') || filename.includes('stderr')) return false
  if (filename.endsWith('.log')) return false
  if (filename.endsWith('.nii') || filename.endsWith('.nii.gz')) return false

  return true
}

export function isCanonicalJobArtifactPath(path: string): boolean {
  return /^\/api\/jobs\/[^/]+\/artifacts\/files(?:\/|$|\?)/.test(path)
}

export function mustMatchAnalysisId(path: string, analysisId: string): boolean {
  const decoded = decodeURIComponent(analysisId)
  const jobMatch = /^\/api\/jobs\/([^/]+)\//.exec(path)
  if (jobMatch) return decodeURIComponent(jobMatch[1]) === decoded
  return true
}
