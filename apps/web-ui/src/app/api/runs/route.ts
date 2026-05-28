import { NextRequest } from 'next/server'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
const COMPAT_HEADER_KEY = 'x-br-compat-surface'
const COMPAT_HEADER_VALUE = 'agent-runs'

const compatibilityHeaders = (contentType: string | null): HeadersInit => ({
  'content-type': contentType || 'application/json',
  [COMPAT_HEADER_KEY]: COMPAT_HEADER_VALUE,
})

function normalizePipeline(value: unknown): string {
  if (typeof value !== 'string') return 'custom'
  const normalized = value.trim().toLowerCase()
  const allowed = new Set([
    'glm',
    'connectivity',
    'decoding',
    'preprocessing',
    'custom',
    'demo',
    'pipeline_builder',
    'chat',
    'copilot',
  ])
  return allowed.has(normalized) ? normalized : 'custom'
}

function safeRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function buildRunPayload(body: Record<string, unknown>): Record<string, unknown> {
  const plan = safeRecord(body.plan)
  if (plan) return body

  // Legacy compatibility path: older callers may still post flattened fields.
  const payload: Record<string, unknown> = {
    prompt: typeof body.prompt === 'string' ? body.prompt : '',
    pipeline: normalizePipeline(body.pipeline),
    parameters: safeRecord(body.parameters) ?? {},
  }

  if (typeof body.dataset_id === 'string' && body.dataset_id.trim()) {
    payload.dataset_id = body.dataset_id
  }
  if (typeof body.intent === 'string' && body.intent.trim()) {
    payload.intent = body.intent
  }

  if (typeof body.thread_id === 'string' && body.thread_id.trim()) {
    payload.thread_id = body.thread_id
  }

  const checkpointIdCandidates = [
    body.checkpoint_id,
    body.checkpointId,
    body.resume_checkpoint_id,
    body.resumeCheckpointId,
  ]
  const checkpointId = checkpointIdCandidates.find(
    (value): value is string => typeof value === 'string' && value.trim().length > 0,
  )
  if (checkpointId) {
    payload.checkpoint_id = checkpointId
  }

  return payload
}

export async function POST(req: NextRequest) {
  try {
    const rawBody = await req.json().catch(() => ({}))
    const body = safeRecord(rawBody) ?? {}
    const upstreamPayload = buildRunPayload(body)

    const headers = forwardAuthHeaders(req)
    headers.set('content-type', 'application/json')

    // Compatibility-only public facade. New analysis flows should prefer
    // `/api/analyses` and Orchestrator-owned job resources; keep this only for
    // direct legacy consumers.
    const res = await fetch(`${resolveAgentBaseUrl()}/api/runs`, {
      method: 'POST',
      headers,
      body: JSON.stringify(upstreamPayload),
      cache: 'no-store',
    })

    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: compatibilityHeaders(res.headers.get('content-type')),
    })
  } catch (error) {
    return new Response(JSON.stringify({ error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to create run' }), {
      status: 503,
      headers: compatibilityHeaders('application/json'),
    })
  }
}

export async function GET(req: NextRequest) {
  try {
    const headers = forwardAuthHeaders(req)
    const incomingQuery = req.nextUrl.search || ''

    const res = await fetch(`${resolveAgentBaseUrl()}/api/runs${incomingQuery}`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    })

    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: compatibilityHeaders(res.headers.get('content-type')),
    })
  } catch (error) {
    return new Response(JSON.stringify({ error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to list runs' }), {
      status: 503,
      headers: compatibilityHeaders('application/json'),
    })
  }
}
