import { serviceEndpoints } from '@/lib/service-endpoints'

import type {
  StudioRuntimeProfile,
  StudioSession,
  StudioSessionStatus,
  WorkspaceLaunchMode,
} from './studio-sessions'

export type HubRuntimeKind = 'marimo'

export interface HubRuntimeSession {
  id: string
  project_id: string
  owner_user_id: string
  runtime_profile_id: StudioRuntimeProfile
  kind: HubRuntimeKind
  status: StudioSessionStatus
  marimo_base_url: string | null
  marimo_port: number
  working_directory: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  last_activity_at: string
}

export interface HubWorkspaceHandoff {
  session_id: string
  project_id: string
  runtime_session_id: string | null
  runtime_profile_id: StudioRuntimeProfile
  runtime_kind: HubRuntimeKind
  runtime_status: StudioSessionStatus
  hub_base_url: string
  launch_mode: WorkspaceLaunchMode
  workspace_url: string
  runtime_target_url: string | null
  runtime_websocket_url: string | null
  runtime_connection_mode: string | null
  runtime_target_ready: boolean | null
  runtime_target_reason: string | null
  target_path: string | null
  notebook_path: string | null
  open_artifact_id: string | null
  initial_focus: string | null
  materialize_notebook_if_needed: boolean
}

export interface CreateHubSessionRequest {
  project_id: string
  display_name: string
  runtime_profile_id?: StudioRuntimeProfile
  attach_if_exists?: boolean
  metadata?: Record<string, unknown>
  target_path?: string | null
  notebook_path?: string | null
  open_artifact_id?: string | null
  initial_focus?: string | null
  materialize_notebook_if_needed?: boolean
  open_clean_workspace?: boolean
  taskbeacon_repo?: string | null
  taskbeacon_ref?: string | null
}

export interface HubWorkspaceHandoffRequest {
  runtime_profile_id?: StudioRuntimeProfile
  target_path?: string | null
  notebook_path?: string | null
  open_artifact_id?: string | null
  initial_focus?: string | null
  materialize_notebook_if_needed?: boolean
  open_clean_workspace?: boolean
}

export interface HubSessionEnvelope {
  session: StudioSession
  runtime: HubRuntimeSession
  handoff: HubWorkspaceHandoff
}

type RequestOptions = {
  accessToken?: string | null
  signal?: AbortSignal
}

const HUB_SESSIONS_BASE = '/api/hub/sessions'

const buildHeaders = (accessToken?: string | null) => {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  return headers
}

/**
 * Error thrown by requestJson() for hub-session gateway failures. Carries the
 * HTTP status so callers can distinguish retryable failures (network = 0, or
 * HTTP 5xx) from terminal ones (4xx). Mirrors AppendHubSessionCellError below.
 *
 * The message prefix `Hub session gateway request failed:` is load-bearing:
 * isMissingHubSessionError() substring-matches the backend 'Hub session not
 * found' detail that follows it, so keep the template intact.
 */
export class HubSessionGatewayError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'HubSessionGatewayError'
    this.status = status
  }
}

/**
 * Classify a hub-session gateway error as retryable. Only network failures
 * (status 0, fetch rejected => orchestrator unreachable) and HTTP 5xx are
 * transient; 4xx (auth/validation/missing) and any non-gateway error are
 * terminal.
 */
export function isRetryableHubGatewayError(err: unknown): boolean {
  return err instanceof HubSessionGatewayError && (err.status === 0 || err.status >= 500)
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  options?: RequestOptions,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(serviceEndpoints.orchestrator(path), {
      ...init,
      credentials: 'include',
      signal: options?.signal,
      headers: {
        ...buildHeaders(options?.accessToken),
        ...(init.headers ?? {}),
      },
    })
  } catch (err) {
    // Network rejection (e.g. orchestrator unreachable during a Recreate-strategy
    // redeploy). Surface as status 0 so callers treat it as retryable.
    const msg = err instanceof Error ? err.message : String(err)
    throw new HubSessionGatewayError(`Hub session gateway request failed: ${msg}`, 0)
  }

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
    throw new HubSessionGatewayError(
      `Hub session gateway request failed: ${detail}`,
      response.status,
    )
  }

  return (await response.json()) as T
}

export async function createOrAttachHubSession(
  payload: CreateHubSessionRequest,
  options?: RequestOptions,
): Promise<HubSessionEnvelope> {
  return requestJson<HubSessionEnvelope>(
    HUB_SESSIONS_BASE,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}

export async function getHubSession(
  sessionId: string,
  options?: RequestOptions,
): Promise<HubSessionEnvelope> {
  return requestJson<HubSessionEnvelope>(
    `${HUB_SESSIONS_BASE}/${encodeURIComponent(sessionId)}`,
    { method: 'GET' },
    options,
  )
}

export async function buildHubWorkspaceHandoff(
  sessionId: string,
  payload: HubWorkspaceHandoffRequest = {},
  options?: RequestOptions,
): Promise<HubWorkspaceHandoff> {
  const response = await requestJson<{ handoff: HubWorkspaceHandoff }>(
    `${HUB_SESSIONS_BASE}/${encodeURIComponent(sessionId)}/handoff`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.handoff
}

export interface AppendHubSessionCellResponse {
  cell_id: string
  runtime_session_id: string
}

export type AppendHubSessionCellErrorCode =
  | 'marimo-runtime-not-ready'
  | 'marimo-session-not-found'
  | 'marimo-auth-failed'
  | 'marimo-upstream-rejected'
  | 'network-error'
  | 'unknown-error'

export class AppendHubSessionCellError extends Error {
  code: AppendHubSessionCellErrorCode
  status: number
  reason: string | null
  constructor(
    code: AppendHubSessionCellErrorCode,
    status: number,
    reason: string | null,
  ) {
    super(`Append cell failed: ${code} (${status})`)
    this.code = code
    this.status = status
    this.reason = reason
  }
}

export async function appendHubSessionCell(
  sessionId: string,
  code: string,
  options?: RequestOptions,
): Promise<AppendHubSessionCellResponse> {
  let response: Response
  try {
    response = await fetch(
      serviceEndpoints.orchestrator(
        `${HUB_SESSIONS_BASE}/${encodeURIComponent(sessionId)}/cells`,
      ),
      {
        method: 'POST',
        credentials: 'include',
        signal: options?.signal,
        body: JSON.stringify({ code }),
        headers: buildHeaders(options?.accessToken),
      },
    )
  } catch (err) {
    throw new AppendHubSessionCellError(
      'network-error',
      0,
      err instanceof Error ? err.message : String(err),
    )
  }

  if (response.ok) {
    return (await response.json()) as AppendHubSessionCellResponse
  }

  let detailCode: AppendHubSessionCellErrorCode = 'unknown-error'
  let reason: string | null = null
  try {
    const payload = (await response.json()) as {
      detail?: { error?: string; reason?: string } | string
    }
    if (payload && typeof payload.detail === 'object' && payload.detail) {
      const rawCode = String(payload.detail.error || '').trim()
      if (
        rawCode === 'marimo-runtime-not-ready' ||
        rawCode === 'marimo-session-not-found' ||
        rawCode === 'marimo-auth-failed' ||
        rawCode === 'marimo-upstream-rejected' ||
        rawCode === 'network-error'
      ) {
        detailCode = rawCode
      }
      reason = payload.detail.reason ?? null
    }
  } catch {
    // ignore parse failure; surface generic error
  }
  throw new AppendHubSessionCellError(detailCode, response.status, reason)
}

export async function deleteHubSession(
  sessionId: string,
  options?: RequestOptions,
): Promise<{ action: string; session: StudioSession; runtime: HubRuntimeSession | null }> {
  return requestJson<{
    action: string
    session: StudioSession
    runtime: HubRuntimeSession | null
  }>(`${HUB_SESSIONS_BASE}/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }, options)
}
