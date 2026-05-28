import { NextRequest, NextResponse } from 'next/server'
import { randomUUID } from 'crypto'
import {
  extractCheckpointIdFromBoundary,
  withResumeCheckpointInContext,
} from '@/lib/chat-checkpoints'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

/**
 * Streaming chat endpoint - proxies to Agent /api/chat/stream
 * Returns SSE stream of tokens for real-time chat responses
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))

  const prompt = body?.message ?? body?.prompt
  const messages = Array.isArray(body?.messages) ? body.messages : undefined
  const rawThreadId = body?.thread_id ?? body?.thread ?? body?.session_id
  const thread_id =
    typeof rawThreadId === 'string' && rawThreadId.trim()
      ? rawThreadId.trim()
      : randomUUID()
  const model = body?.model
  const tools = body?.tools
  const ingressResumeCheckpointId = extractCheckpointIdFromBoundary({
    ...((body?.ctx && typeof body.ctx === 'object') ? body.ctx : {}),
    resume_checkpoint_id: body?.resume_checkpoint_id ?? body?.resumeCheckpointId,
    checkpoint_id: body?.checkpoint_id ?? body?.checkpointId,
  })
  const ctx = withResumeCheckpointInContext(
    body?.ctx && typeof body.ctx === 'object'
      ? (body.ctx as Record<string, any>)
      : undefined,
    ingressResumeCheckpointId ?? null,
  )
  const user_id = body?.user_id
  const metadata = body?.metadata
  const scenario_id = body?.scenario_id ?? body?.scenarioId
  const parameters = body?.parameters
  const inputs = body?.inputs ?? parameters
  const finalMessages = messages && messages.length
    ? messages
    : prompt
      ? [{ role: 'user', content: String(prompt) }]
      : []

  if (!finalMessages.length) {
    return NextResponse.json({ error: 'Missing chat message' }, { status: 400 })
  }

  const agentPayload = {
    thread_id,
    model,
    messages: finalMessages,
    ...(tools && { tools }),
    ...(ctx && { ctx }),
    ...(user_id && { user_id }),
    ...(metadata && { metadata }),
    ...(scenario_id && { scenario_id }),
    ...(parameters && { parameters }),
    ...(inputs && { inputs }),
  }

  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  const res = await fetch(`${resolveAgentBaseUrl()}/api/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(agentPayload),
    cache: 'no-store',
  })

  // Check for error before streaming
  if (!res.ok) {
    const text = await res.text()
    return new Response(text, {
      status: res.status,
      headers: { 'content-type': 'application/json' },
    })
  }

  // Pipe SSE stream directly
  return new Response(res.body, {
    status: 200,
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      'connection': 'keep-alive',
    },
  })
}
