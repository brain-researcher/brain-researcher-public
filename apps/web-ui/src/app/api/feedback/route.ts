import { NextRequest, NextResponse } from 'next/server'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

const REQUEST_TIMEOUT_MS = 5_000

async function fetchWithTimeout(url: string, init: RequestInit = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()

    const response = await fetchWithTimeout(
      `${resolveOrchestratorBaseUrl()}/api/feedback`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      }
    )

    const text = await response.text()
    const data = text ? JSON.parse(text) : null

    return NextResponse.json(data ?? {}, { status: response.status })
  } catch (error) {
    console.error('Feedback proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to submit feedback' },
      { status: 502 }
    )
  }
}

export async function GET() {
  // Simple passthrough for listing recent feedback (admin-only upstream)
  try {
    const response = await fetchWithTimeout(
      `${resolveOrchestratorBaseUrl()}/api/feedback`
    )
    const text = await response.text()
    const data = text ? JSON.parse(text) : null
    return NextResponse.json(data ?? {}, { status: response.status })
  } catch (error) {
    console.error('Feedback list proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to load feedback' },
      { status: 502 }
    )
  }
}
