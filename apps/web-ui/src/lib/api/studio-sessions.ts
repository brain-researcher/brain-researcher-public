import { serviceEndpoints } from '@/lib/service-endpoints'

export type StudioSessionStatus =
  | 'provisioning'
  | 'ready'
  | 'busy'
  | 'idle'
  | 'degraded'
  | 'stopping'
  | 'stopped'
  | 'failed'
  | 'expired'

export type StudioRuntimeProfile = 'standard' | 'high_mem' | 'gpu'

export type WorkspaceLaunchMode = 'reuse_active_runtime' | 'provision_new_runtime'

export interface StudioSession {
  id: string
  project_id: string
  owner_user_id: string
  display_name: string
  runtime_profile_id: StudioRuntimeProfile
  runtime_session_id: string
  assistant_session_id: string
  status: StudioSessionStatus
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  last_activity_at: string
}

export interface WorkspaceHandoff {
  project_id: string
  runtime_session_id: string | null
  runtime_profile_id: StudioRuntimeProfile
  launch_mode: WorkspaceLaunchMode
  workspace_url: string
  target_path: string | null
  notebook_path: string | null
  open_artifact_id: string | null
  initial_focus: string | null
  materialize_notebook_if_needed: boolean
}

export interface CreateStudioSessionRequest {
  project_id: string
  display_name: string
  runtime_profile_id?: StudioRuntimeProfile
  attach_if_exists?: boolean
  metadata?: Record<string, unknown>
}

export interface ListStudioSessionsOptions {
  project_id?: string
  runtime_profile_id?: StudioRuntimeProfile
  status?: StudioSessionStatus
  limit?: number
  offset?: number
}

export interface StudioSessionActionRequest {
  reason?: string
}

export interface WorkspaceHandoffRequest {
  runtime_profile_id?: StudioRuntimeProfile
  target_path?: string | null
  notebook_path?: string | null
  open_artifact_id?: string | null
  initial_focus?: string | null
  materialize_notebook_if_needed?: boolean
  open_clean_workspace?: boolean
}

type RequestOptions = {
  accessToken?: string | null
  signal?: AbortSignal
}

const STUDIO_SESSIONS_BASE = '/api/studio/sessions'

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
      // Ignore non-JSON failures and surface the HTTP status text instead.
    }
    throw new Error(`Studio session gateway request failed: ${detail}`)
  }

  return (await response.json()) as T
}

export async function createOrAttachStudioSession(
  payload: CreateStudioSessionRequest,
  options?: RequestOptions,
): Promise<StudioSession> {
  const response = await requestJson<{ session: StudioSession }>(
    STUDIO_SESSIONS_BASE,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.session
}

export async function listStudioSessions(
  params: ListStudioSessionsOptions = {},
  options?: RequestOptions,
): Promise<StudioSession[]> {
  const query = new URLSearchParams()
  if (params.project_id) query.set('project_id', params.project_id)
  if (params.runtime_profile_id) query.set('runtime_profile_id', params.runtime_profile_id)
  if (params.status) query.set('status', params.status)
  if (typeof params.limit === 'number') query.set('limit', String(params.limit))
  if (typeof params.offset === 'number') query.set('offset', String(params.offset))
  const path = query.size > 0 ? `${STUDIO_SESSIONS_BASE}?${query.toString()}` : STUDIO_SESSIONS_BASE

  const response = await requestJson<{ items: StudioSession[] }>(
    path,
    { method: 'GET' },
    options,
  )
  return response.items
}

export async function getStudioSession(
  sessionId: string,
  options?: RequestOptions,
): Promise<StudioSession> {
  const response = await requestJson<{ session: StudioSession }>(
    `${STUDIO_SESSIONS_BASE}/${encodeURIComponent(sessionId)}`,
    { method: 'GET' },
    options,
  )
  return response.session
}

export async function performStudioSessionAction(
  sessionId: string,
  action: 'touch' | 'close',
  payload: StudioSessionActionRequest = {},
  options?: RequestOptions,
): Promise<StudioSession> {
  const response = await requestJson<{ action: string; session: StudioSession }>(
    `${STUDIO_SESSIONS_BASE}/${encodeURIComponent(sessionId)}/actions/${action}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.session
}

export async function buildWorkspaceHandoff(
  sessionId: string,
  payload: WorkspaceHandoffRequest = {},
  options?: RequestOptions,
): Promise<WorkspaceHandoff> {
  const response = await requestJson<{ handoff: WorkspaceHandoff }>(
    `${STUDIO_SESSIONS_BASE}/${encodeURIComponent(sessionId)}/workspace-handoff`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.handoff
}
