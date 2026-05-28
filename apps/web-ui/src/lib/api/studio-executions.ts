import { serviceEndpoints } from '@/lib/service-endpoints'
import type { StudioRuntimeProfile } from '@/lib/api/studio-sessions'

export type StudioExecutionKind = 'code' | 'command'

export type StudioExecutionBackend =
  | 'stub'
  | 'jupyter_kernel'
  | 'neurodesk_module'
  | 'container'

export type StudioExecutionStatus =
  | 'accepted'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'canceled'

export interface StudioExecutionResult {
  stubbed: boolean
  exit_code: number | null
  stdout: string
  stderr: string
  artifacts: Array<Record<string, unknown>>
  summary: string | null
}

export interface StudioExecution {
  id: string
  session_id: string
  runtime_session_id: string
  project_id: string
  owner_user_id: string
  kind: StudioExecutionKind
  runtime_backend: StudioExecutionBackend
  runtime_profile_id: StudioRuntimeProfile
  status: StudioExecutionStatus
  language: string | null
  code: string | null
  command: string[]
  working_directory: string | null
  env: Record<string, string>
  timeout_seconds: number | null
  metadata: Record<string, unknown>
  request_summary: string
  result: StudioExecutionResult | null
  created_at: string
  updated_at: string
  accepted_at: string | null
  completed_at: string | null
}

export interface CreateStudioExecutionRequest {
  kind: StudioExecutionKind
  language?: string
  code?: string
  command?: string[]
  runtime_backend?: StudioExecutionBackend
  runtime_profile_id?: StudioRuntimeProfile
  working_directory?: string | null
  env?: Record<string, string>
  timeout_seconds?: number
  dry_run?: boolean
  metadata?: Record<string, unknown>
}

export interface StudioExecutionActionRequest {
  reason?: string
}

type RequestOptions = {
  accessToken?: string | null
  signal?: AbortSignal
}

const buildHeaders = (accessToken?: string | null) => {
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

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload?.detail) {
        detail = payload.detail
      }
    } catch {
      // Ignore non-JSON failures and surface HTTP status text instead.
    }
    throw new Error(`Studio execution gateway request failed: ${detail}`)
  }

  return (await response.json()) as T
}

const executionsBasePath = (sessionId: string) =>
  `/api/studio/sessions/${encodeURIComponent(sessionId)}/executions`

export async function createStudioExecution(
  sessionId: string,
  payload: CreateStudioExecutionRequest,
  options?: RequestOptions,
): Promise<StudioExecution> {
  const response = await requestJson<{ execution: StudioExecution }>(
    executionsBasePath(sessionId),
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.execution
}

export async function getStudioExecution(
  sessionId: string,
  executionId: string,
  options?: RequestOptions,
): Promise<StudioExecution> {
  const response = await requestJson<{ execution: StudioExecution }>(
    `${executionsBasePath(sessionId)}/${encodeURIComponent(executionId)}`,
    {
      method: 'GET',
    },
    options,
  )
  return response.execution
}

export async function cancelStudioExecution(
  sessionId: string,
  executionId: string,
  payload: StudioExecutionActionRequest = {},
  options?: RequestOptions,
): Promise<StudioExecution> {
  const response = await requestJson<{ execution: StudioExecution }>(
    `${executionsBasePath(sessionId)}/${encodeURIComponent(executionId)}/actions/cancel`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.execution
}
