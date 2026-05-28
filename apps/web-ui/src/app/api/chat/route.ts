import { NextRequest, NextResponse } from 'next/server'
import {
  extractCheckpointIdFromBoundary,
  withResumeCheckpointInContext,
} from '@/lib/chat-checkpoints'
import { forwardAuthHeaders, resolveAgentBaseUrl } from '@/lib/server/downstream'

export const dynamic = 'force-dynamic'

const DEFAULT_TIMEOUT_MS = 20_000
const COPILOT_CHAT_SYSTEM_PROMPT =
  'You are Brain Researcher Copilot. Provide concise, user-facing assistance only. Do not reveal internal reasoning, hidden deliberation, tool-selection rationale, or planning traces. Never use phrases like "the user said" or "I should".'

function getTimeoutMs(): number {
  const raw =
    process.env.BR_CHAT_PROXY_TIMEOUT_MS ||
    process.env.CHAT_PROXY_TIMEOUT_MS ||
    process.env.AGENT_CHAT_TIMEOUT_MS
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN
  if (Number.isFinite(parsed) && parsed > 0) return parsed
  return DEFAULT_TIMEOUT_MS
}

type ChatMessage = {
  role: string
  content: string
}

function normalizeMessages(messages: unknown): ChatMessage[] {
  if (!Array.isArray(messages)) return []
  return messages
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return null
      const role = String((entry as any).role || '').trim()
      const content = String((entry as any).content || '').trim()
      if (!role || !content) return null
      return { role, content }
    })
    .filter((entry): entry is ChatMessage => Boolean(entry))
}

function applyCopilotSystemPrompt(
  messages: ChatMessage[],
  prompt: string | undefined,
): ChatMessage[] {
  const normalized = [...messages]
  if (!normalized.some((msg) => msg.role === 'user') && prompt?.trim()) {
    normalized.push({ role: 'user', content: String(prompt).trim() })
  }

  const hasCopilotSystemPrompt = normalized.some(
    (msg) =>
      msg.role === 'system' &&
      msg.content.toLowerCase().includes('brain researcher copilot'),
  )
  if (!hasCopilotSystemPrompt) {
    normalized.unshift({ role: 'system', content: COPILOT_CHAT_SYSTEM_PROMPT })
  }
  return normalized
}

function buildAgentPayload(body: any) {
  const prompt = body?.message ?? body?.prompt
  const messages = normalizeMessages(body?.messages)
  const codingMode = body?.codingMode ?? body?.coding_mode
  // Support both legacy tool_mode and new tools.mode format
  const toolsConfig = body?.tools
  const tool_mode = body?.tool_mode ?? (codingMode === false ? 'none' : 'auto')
  const tools_whitelist =
    body?.tools_whitelist ??
    toolsConfig?.whitelist ??
    toolsConfig?.allowlist
  const scenarioField = body?.scenario
  const scenario_id = body?.scenario_id ?? body?.scenarioId ?? (typeof scenarioField === 'string' ? scenarioField : undefined)
  const thread_id = body?.thread_id ?? body?.thread ?? body?.session_id
  const ctxInput = body?.ctx
  const planContext: Record<string, unknown> = {}
  const datasetId = body?.dataset_id ?? body?.datasetId
  const pipelineId = body?.pipeline_id ?? body?.pipelineId
  const planParams = body?.parameters ?? body?.inputs
  if (datasetId) planContext.dataset_id = datasetId
  if (pipelineId) planContext.pipeline_id = pipelineId
  if (planParams && typeof planParams === 'object' && !Array.isArray(planParams)) {
    planContext.parameters = planParams
  }
  const ingressResumeCheckpointId = extractCheckpointIdFromBoundary({
    ...(ctxInput && typeof ctxInput === 'object' ? ctxInput : {}),
    resume_checkpoint_id: body?.resume_checkpoint_id ?? body?.resumeCheckpointId,
    checkpoint_id: body?.checkpoint_id ?? body?.checkpointId,
  })
  const baseCtx =
    Object.keys(planContext).length > 0
      ? {
          ...(ctxInput && typeof ctxInput === 'object' ? ctxInput : {}),
          plan_context: {
            ...((ctxInput?.plan_context && typeof ctxInput.plan_context === 'object')
              ? ctxInput.plan_context
              : {}),
            ...planContext,
          },
        }
      : ctxInput
  const ctx = withResumeCheckpointInContext(
    baseCtx && typeof baseCtx === 'object'
      ? (baseCtx as Record<string, any>)
      : undefined,
    ingressResumeCheckpointId ?? null,
  )
  const model = body?.model
  const user_id = body?.user_id
  const budget_ms = body?.budget_ms ?? body?.budgetMs
  const tool_params = body?.tool_params ?? body?.toolParams
  const metadata = body?.metadata
  const parameters = body?.parameters
  const inputs = body?.inputs ?? parameters
  const copilotRequested = body?.copilot === true || body?.metadata?.copilot === true

  const finalMessages = messages.length
    ? messages
    : prompt
      ? [{ role: 'user', content: String(prompt).trim() }]
      : []
  const constrainedMessages = copilotRequested
    ? applyCopilotSystemPrompt(finalMessages, prompt)
    : finalMessages

  return {
    thread_id,
    tool_mode,
    ...(toolsConfig && { tools: toolsConfig }),  // Pass through tools config
    ...(tools_whitelist && { tools_whitelist }),
    ...(ctx && { ctx }),
    ...(model && { model }),
    ...(user_id && { user_id }),
    ...(budget_ms !== undefined && { budget_ms }),
    ...(tool_params !== undefined && { tool_params }),
    ...(parameters && { parameters }),
    ...(inputs && { inputs }),
    messages: constrainedMessages,
    metadata: scenario_id
      ? { ...(metadata || {}), scenario_id }
      : (metadata || {}),
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  const agentPayload = buildAgentPayload(body)

  if (!agentPayload.messages.length) {
    return NextResponse.json({ error: 'Missing chat message' }, { status: 400 })
  }

  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  const controller = new AbortController()
  const timeoutMs = getTimeoutMs()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
  const res = await fetch(`${resolveAgentBaseUrl()}/api/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(agentPayload),
      cache: 'no-store',
      signal: controller.signal,
    })

    if (res.status === 401 || res.status === 403) {
      const detail = await res.text().catch(() => '')
      return NextResponse.json(
        {
          code: 'E-AUTH',
          detail: detail || `HTTP ${res.status}`,
          message: {
            role: 'assistant',
            content: 'No response (login required).',
          },
          error: {
            code: 'auth_required',
            detail: detail || `HTTP ${res.status}`,
          },
        },
        { status: res.status }
      )
    }

    const text = await res.text()

    // Guarantee a structured, non-empty payload on errors so smoke tests and UI
    // have something user-friendly to display even when the agent fails early
    // (e.g., missing LLM credentials or upstream timeouts).
    if (res.status >= 400 && !text.trim()) {
      const code = res.status >= 500 ? 'E-SERVICE-UNAVAILABLE' : 'E-UNKNOWN'
      return NextResponse.json(
        {
          code,
          detail: `Agent error HTTP ${res.status}`,
          message: {
            role: 'assistant',
            content: 'No response (agent returned an error).',
          },
          error: {
            code: 'agent_error',
            detail: `Agent error HTTP ${res.status}`,
          },
        },
        { status: res.status }
      )
    }

    return new Response(text, {
      status: res.status,
      headers: {
        'content-type': res.headers.get('content-type') || 'application/json',
      },
    })
  } catch (error) {
    // Keep the UI responsive even if the agent is slow/unreachable.
    const reason =
      error instanceof Error && error.name === 'AbortError'
        ? `Agent timed out after ${timeoutMs}ms`
        : error instanceof Error
          ? error.message
          : 'Unknown error'

    return NextResponse.json(
      {
        code: 'E-SERVICE-UNAVAILABLE',
        detail: reason,
        message: {
          role: 'assistant',
          content: `No response (agent unavailable).`,
        },
        error: {
          code: 'agent_unavailable',
          detail: reason,
        },
      },
      { status: 503 }
    )
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function GET(req: NextRequest) {
  // Health check: proxy to Agent /api/health
  const res = await fetch(`${resolveAgentBaseUrl()}/api/health`, { cache: 'no-store' })
  const text = await res.text()
  return new Response(text, {
    status: res.status,
    headers: {
      'content-type': res.headers.get('content-type') || 'application/json',
    },
  })
}
