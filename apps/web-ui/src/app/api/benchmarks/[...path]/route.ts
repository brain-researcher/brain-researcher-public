import { NextRequest, NextResponse } from 'next/server'
import { resolveOrchestratorBaseUrl, forwardAuthHeaders } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

async function proxyToOrchestrator(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  const subPath = params.path.join('/')
  const orchestratorBase = resolveOrchestratorBaseUrl()
  const url = new URL(request.url)
  const qs = url.search || ''
  const upstreamUrl = `${orchestratorBase}/api/benchmarks/${subPath}${qs}`

  const headers = forwardAuthHeaders(request)
  headers.set('content-type', 'application/json')
  headers.set('accept', 'application/json')

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: 'no-store',
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    const body = await request.text()
    if (body) init.body = body
  }

  try {
    const upstream = await fetch(upstreamUrl, init)
    const raw = await upstream.text()
    const contentType = upstream.headers.get('content-type') || ''
    const isJson = contentType.includes('application/json')
    const responseBody = isJson
      ? (JSON.parse(raw || '{}') as Record<string, unknown>)
      : { detail: raw || `Upstream request failed (${upstream.status})` }

    return NextResponse.json(responseBody, { status: upstream.status })
  } catch (error) {
    console.error(`[api/benchmarks/${subPath}] upstream request failed`, error)
    return NextResponse.json(
      { detail: 'Benchmark service temporarily unavailable' },
      { status: 502 }
    )
  }
}

export async function GET(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return proxyToOrchestrator(request, context)
}

export async function POST(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return proxyToOrchestrator(request, context)
}

export async function PATCH(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return proxyToOrchestrator(request, context)
}

export async function PUT(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return proxyToOrchestrator(request, context)
}

export async function DELETE(
  request: NextRequest,
  context: { params: { path: string[] } }
) {
  return proxyToOrchestrator(request, context)
}
