import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function normalizeId(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

async function passthrough(upstream: Response): Promise<Response> {
  const raw = await upstream.text()
  return new NextResponse(raw, {
    status: upstream.status,
    headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' },
  })
}

async function proxyProjectRequest(
  req: NextRequest,
  method: 'GET' | 'PATCH' | 'DELETE',
  projectId: string,
) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  const normalizedProjectId = normalizeId(projectId)
  if (!normalizedProjectId) {
    return NextResponse.json({ detail: 'projectId is required.' }, { status: 400 })
  }

  const headers = forwardAuthHeaders(req)
  let body: string | undefined
  if (method === 'PATCH') {
    let payload: unknown
    try {
      payload = await req.json()
    } catch {
      return NextResponse.json({ detail: 'Invalid JSON payload.' }, { status: 400 })
    }
    headers.set('content-type', 'application/json')
    body = JSON.stringify(payload)
  }

  let upstream: Response
  try {
    upstream = await fetch(
      `${resolveAgentBaseUrl()}/api/projects/${encodeURIComponent(normalizedProjectId)}`,
      {
        method,
        headers,
        ...(body ? { body } : {}),
        cache: 'no-store',
      },
    )
  } catch {
    return NextResponse.json(
      { error: 'E-SERVICE-UNAVAILABLE', detail: `Failed to ${method.toLowerCase()} project` },
      { status: 503 },
    )
  }

  return passthrough(upstream)
}

export async function GET(
  req: NextRequest,
  context: { params: { projectId: string } },
) {
  return proxyProjectRequest(req, 'GET', context.params.projectId)
}

export async function PATCH(
  req: NextRequest,
  context: { params: { projectId: string } },
) {
  return proxyProjectRequest(req, 'PATCH', context.params.projectId)
}

export async function DELETE(
  req: NextRequest,
  context: { params: { projectId: string } },
) {
  return proxyProjectRequest(req, 'DELETE', context.params.projectId)
}
