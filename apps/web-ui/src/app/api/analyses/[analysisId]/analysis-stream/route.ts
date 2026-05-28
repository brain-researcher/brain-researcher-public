import { NextRequest, NextResponse } from 'next/server'

import {
  forwardAuthHeaders,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'
import { loadDemoIndex } from '@/lib/server/demo-index'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const SENSITIVE_KEY_RE = /(token|authorization|auth|cookie|secret|password|api[_-]?key|jwt|session)/i
const PATH_KEY_RE = /(path|file|dir|root|cwd|home|mount|workspace)/i
const URL_KEY_RE = /(url|uri|href|endpoint|download)/i
const ABS_PATH_RE = /\/(?:home|root|app|tmp|srv|var|etc|opt|workspace)[^"' \n\t]*/g

function isDemoAnalysisId(analysisId: string): boolean {
  const demos = loadDemoIndex().demos || []
  return demos.some((demo) => demo.analysis_id === analysisId)
}

function redactPlainText(input: string): string {
  let output = input
  output = output.replace(/\bBearer\s+[A-Za-z0-9\-._~+/]+=*/gi, 'Bearer [REDACTED]')
  output = output.replace(
    /([?&](?:access_token|token|jwt|authorization|auth|signature|sig)=)[^&\s]+/gi,
    '$1[REDACTED]',
  )
  output = output.replace(ABS_PATH_RE, '[REDACTED_PATH]')
  return output
}

function redactPath(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return value
  if (!trimmed.startsWith('/') && !trimmed.includes('\\')) return redactPlainText(value)
  const normalized = trimmed.replace(/\\/g, '/')
  const segments = normalized.split('/').filter(Boolean)
  const tail = segments.slice(-2).join('/')
  return tail ? `[REDACTED_PATH]/${tail}` : '[REDACTED_PATH]'
}

function redactUrl(value: string): string {
  const raw = value.trim()
  if (!raw) return value
  try {
    const isAbsolute = /^https?:\/\//i.test(raw)
    const parsed = new URL(raw, 'http://localhost')
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (SENSITIVE_KEY_RE.test(key)) parsed.searchParams.set(key, '[REDACTED]')
    }
    parsed.pathname = parsed.pathname.replace(ABS_PATH_RE, '/[REDACTED_PATH]')
    return isAbsolute ? parsed.toString() : `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return redactPlainText(value)
  }
}

function sanitizeValue(value: unknown, parentKey = ''): unknown {
  if (value == null) return value
  if (typeof value === 'string') {
    if (SENSITIVE_KEY_RE.test(parentKey)) return '[REDACTED]'
    if (URL_KEY_RE.test(parentKey)) return redactUrl(value)
    if (PATH_KEY_RE.test(parentKey)) return redactPath(value)
    return redactPlainText(value)
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeValue(item, parentKey))
  }
  if (typeof value === 'object') {
    const result: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEY_RE.test(key)) {
        result[key] = '[REDACTED]'
        continue
      }
      result[key] = sanitizeValue(item, key)
    }
    return result
  }
  return value
}

function sanitizeSseDataPayload(raw: string): string {
  const text = raw.trim()
  if (!text) return text
  try {
    const parsed = JSON.parse(text)
    return JSON.stringify(sanitizeValue(parsed))
  } catch {
    return redactPlainText(raw)
  }
}

function redactSseBlock(block: string): string {
  const lines = block.split('\n')
  const redactedLines = lines.map((line) => {
    if (line.startsWith('data:')) {
      return `data: ${sanitizeSseDataPayload(line.slice('data:'.length).trimStart())}`
    }
    return redactPlainText(line)
  })
  return redactedLines.join('\n')
}

function createRedactedSseStream(upstream: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = upstream.getReader()
  const encoder = new TextEncoder()
  const decoder = new TextDecoder()
  let buffer = ''

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read()
      if (done) {
        if (buffer) {
          controller.enqueue(encoder.encode(`${redactSseBlock(buffer)}\n\n`))
          buffer = ''
        }
        controller.close()
        return
      }

      buffer += decoder.decode(value, { stream: true })
      let separatorIndex = buffer.indexOf('\n\n')
      while (separatorIndex >= 0) {
        const block = buffer.slice(0, separatorIndex)
        buffer = buffer.slice(separatorIndex + 2)
        controller.enqueue(encoder.encode(`${redactSseBlock(block)}\n\n`))
        separatorIndex = buffer.indexOf('\n\n')
      }
    },
    cancel() {
      reader.cancel().catch(() => undefined)
    },
  })
}

async function buildAuthHeadersForRequest(
  req: NextRequest,
  analysisId: string,
): Promise<{ headers: Headers; redactForClient: boolean } | NextResponse> {
  const authed = await isRequestAuthenticated(req)
  if (authed) {
    return { headers: forwardAuthHeaders(req), redactForClient: false }
  }

  if (!isDemoAnalysisId(analysisId)) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  const bearer = issueInternalJwt({
    subject: 'demo-stream',
    email: 'demo-stream@local',
    name: 'demo-stream',
    role: 'demo',
    provider: 'demo-stream',
    ttlSeconds: 10 * 60,
  })
  if (!bearer) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Demo auth is not configured.' },
      { status: 500 },
    )
  }

  const headers = new Headers()
  headers.set('authorization', `Bearer ${bearer}`)
  const workspaceId = req.headers.get('x-workspace-id')
  if (workspaceId) headers.set('x-workspace-id', workspaceId)
  return { headers, redactForClient: true }
}

async function proxyUpstreamStream(
  targetUrl: string,
  headers: Headers,
  redactForClient: boolean,
): Promise<NextResponse> {
  const upstream = await fetch(targetUrl, {
    method: 'GET',
    headers,
    cache: 'no-store',
  })

  if (!upstream.ok || !upstream.body) {
    const body = await upstream.text().catch(() => '')
    return new NextResponse(body || upstream.statusText, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') || 'application/json',
      },
    })
  }

  const responseHeaders = new Headers()
  const contentType = upstream.headers.get('content-type') || 'text/event-stream'
  responseHeaders.set('content-type', contentType)
  responseHeaders.set('cache-control', 'no-cache, no-transform')
  responseHeaders.set('x-accel-buffering', 'no')

  const isSse = contentType.toLowerCase().includes('text/event-stream')
  const body = redactForClient && isSse ? createRedactedSseStream(upstream.body) : upstream.body

  return new NextResponse(body, {
    status: upstream.status,
    headers: responseHeaders,
  })
}

export async function GET(
  req: NextRequest,
  { params }: { params: { analysisId: string } },
) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authResult = await buildAuthHeadersForRequest(req, analysisId)
  if (!('redactForClient' in authResult)) return authResult

  const orchBase = resolveOrchestratorBaseUrl()
  const search = req.nextUrl.search
  const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/analysis-stream${search}`
  return proxyUpstreamStream(
    targetUrl,
    authResult.headers,
    authResult.redactForClient,
  )
}
