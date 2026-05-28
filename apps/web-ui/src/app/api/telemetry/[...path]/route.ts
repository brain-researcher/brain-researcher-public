import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'

const TELEMETRY_UPSTREAM =
  process.env.NEXT_PUBLIC_TELEMETRY_UPSTREAM ||
  process.env.TELEMETRY_API_URL ||
  'http://localhost:8003'

const REQUEST_TIMEOUT_MS = 8_000

async function fetchWithTimeout(url: string, init: RequestInit = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

async function proxy(request: NextRequest, { params }: { params: { path?: string[] } }) {
  const path = (params.path || []).join('/')
  const target = `${TELEMETRY_UPSTREAM.replace(/\/$/, '')}/telemetry/${path}`

  const init: RequestInit = {
    method: request.method,
    headers: Object.fromEntries(request.headers.entries()),
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    const body = await request.arrayBuffer()
    init.body = body
  }

  const response = await fetchWithTimeout(target, init)
  const buffer = await response.arrayBuffer()

  const headers = new Headers(response.headers)
  // Ensure CORS/same-origin expectations
  headers.delete('content-encoding')

  return new NextResponse(new Uint8Array(buffer), {
    status: response.status,
    headers,
  })
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
