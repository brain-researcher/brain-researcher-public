import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const RETRY_ATTEMPTS = 2

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchThreadsWithRetry(url: string, headers: Headers): Promise<Response> {
  let lastError: unknown = null

  for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt += 1) {
    try {
      const upstream = await fetch(url, {
        method: 'GET',
        headers,
        cache: 'no-store',
      })
      if (upstream.status >= 500 && attempt + 1 < RETRY_ATTEMPTS) {
        await sleep(150 * (attempt + 1))
        continue
      }
      return upstream
    } catch (error) {
      lastError = error
      if (attempt + 1 < RETRY_ATTEMPTS) {
        await sleep(150 * (attempt + 1))
        continue
      }
      throw lastError
    }
  }

  throw lastError ?? new Error('Unknown upstream error')
}

export async function GET(req: NextRequest) {
  const upstreamUrl = new URL(`${resolveAgentBaseUrl()}/api/threads`)
  req.nextUrl.searchParams.forEach((value, key) => {
    upstreamUrl.searchParams.set(key, value)
  })

  let upstream: Response
  try {
    upstream = await fetchThreadsWithRetry(upstreamUrl.toString(), forwardAuthHeaders(req))
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: 'Failed to list threads' },
      { status: 503 },
    )
  }

  const raw = await upstream.text()
  return new NextResponse(raw, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/json',
    },
  })
}
