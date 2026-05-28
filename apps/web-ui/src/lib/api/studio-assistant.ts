import { serviceEndpoints } from '@/lib/service-endpoints'
import type { StudioNotebookDocument, StudioNotebookOperation } from '@/lib/api/studio-notebook'

export interface StudioAssistantThread {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  context: Record<string, unknown>
  metadata: Record<string, unknown>
  scenario_id?: string | null
}

export interface StudioAssistantMessage {
  id: string
  thread_id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  timestamp: string
  metadata: Record<string, unknown>
}

export interface StudioAssistantPlan {
  assistant_message: string
  ops: StudioNotebookOperation[]
  source: string
  planner_source?: string | null
  planner_status?: string | null
  fallback_reason?: string | null
  planner_error?: {
    code: string
    message?: string | null
    status_code?: number | null
  } | null
}

export interface StudioAssistantStateResponse {
  assistant_session_id: string
  thread: StudioAssistantThread
  messages: StudioAssistantMessage[]
}

export interface StudioAssistantTurnPayload {
  content: string
  notebook: Pick<
    StudioNotebookDocument,
    'path' | 'title' | 'kernel_name' | 'metadata' | 'revision'
  > & {
    cells: Array<{
      id: string
      cell_type: 'code' | 'markdown'
      source: string
      status: string
    }>
  }
}

export interface StudioAssistantTurnResponse extends StudioAssistantStateResponse {
  user_message: StudioAssistantMessage
  assistant_message: StudioAssistantMessage
  plan: StudioAssistantPlan
  notebook: StudioNotebookDocument
  planner_source?: string | null
  planner_status?: string | null
  fallback_reason?: string | null
}

type RequestOptions = {
  accessToken?: string | null
  signal?: AbortSignal
}

function buildHeaders(accessToken?: string | null): HeadersInit {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  return headers
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  options?: RequestOptions,
): Promise<T> {
  const response = await fetch(serviceEndpoints.orchestrator(path), {
    ...init,
    credentials: 'include',
    signal: options?.signal,
    headers: {
      ...buildHeaders(options?.accessToken),
      ...(init.headers ?? {}),
    },
  })

  const data = (await response.json().catch(() => ({}))) as T & { detail?: string }
  if (!response.ok) {
    throw new Error(data?.detail || 'Studio assistant request failed')
  }
  return data
}

function assistantBasePath(sessionId: string) {
  return `/api/studio/sessions/${encodeURIComponent(sessionId)}/assistant`
}

export async function getStudioAssistantState(
  sessionId: string,
  options?: RequestOptions,
): Promise<StudioAssistantStateResponse> {
  return requestJson<StudioAssistantStateResponse>(
    assistantBasePath(sessionId),
    { method: 'GET' },
    options,
  )
}

export async function submitStudioAssistantTurn(
  sessionId: string,
  payload: StudioAssistantTurnPayload,
  options?: RequestOptions,
): Promise<StudioAssistantTurnResponse> {
  return requestJson<StudioAssistantTurnResponse>(
    `${assistantBasePath(sessionId)}/turns`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}
