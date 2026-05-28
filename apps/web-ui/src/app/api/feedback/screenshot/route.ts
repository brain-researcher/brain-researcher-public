import { NextRequest, NextResponse } from 'next/server'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
export const dynamic = 'force-dynamic'

const REQUEST_TIMEOUT_MS = 10_000

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
    const formData = await request.formData()

    const response = await fetchWithTimeout(
      `${resolveOrchestratorBaseUrl()}/api/feedback/screenshot`,
      {
        method: 'POST',
        body: formData,
      }
    )

    const text = await response.text()
    const data = text ? JSON.parse(text) : null
    return NextResponse.json(data ?? {}, { status: response.status })
  } catch (error) {
    console.error('Feedback screenshot proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to upload screenshot' },
      { status: 502 }
    )
  }
}
