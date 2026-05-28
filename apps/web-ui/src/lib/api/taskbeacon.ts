import { serviceEndpoints } from '@/lib/service-endpoints'

export interface TaskBeaconTask {
  repo: string
  readme_snippet?: string
  branches?: string[]
  [key: string]: unknown
}

export interface TaskBeaconListResponse {
  tasks: TaskBeaconTask[]
  count: number
  source: string
}

export interface TaskBeaconDownloadRequest {
  repo: string
  project_id?: string
  target_path?: string | null
  ref?: string | null
  prefer_mcp?: boolean
}

export interface TaskBeaconActionResponse {
  result: Record<string, unknown>
}

export interface TaskBeaconLocalizeRequest {
  task_path: string
  target_language: string
  voice?: string | null
}

export interface TaskBeaconRunRequest {
  task_path: string
  mode?: 'qa' | 'sim'
  config_path?: string | null
  timeout_seconds?: number
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
      // Surface the HTTP status if the orchestrator did not return JSON.
    }
    throw new Error(`TaskBeacon request failed: ${detail}`)
  }

  return (await response.json()) as T
}

export async function listTaskBeaconTasks(
  params?: { query?: string | null; limit?: number },
  options?: RequestOptions,
): Promise<TaskBeaconListResponse> {
  const search = new URLSearchParams()
  if (params?.query) {
    search.set('query', params.query)
  }
  if (params?.limit) {
    search.set('limit', String(params.limit))
  }
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return requestJson<TaskBeaconListResponse>(
    `/api/taskbeacon/tasks${suffix}`,
    { method: 'GET' },
    options,
  )
}

export async function downloadTaskBeaconTask(
  payload: TaskBeaconDownloadRequest,
  options?: RequestOptions,
): Promise<TaskBeaconActionResponse> {
  return requestJson<TaskBeaconActionResponse>(
    '/api/taskbeacon/download',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}

export async function localizeTaskBeaconTask(
  payload: TaskBeaconLocalizeRequest,
  options?: RequestOptions,
): Promise<TaskBeaconActionResponse> {
  return requestJson<TaskBeaconActionResponse>(
    '/api/taskbeacon/localize',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}

export async function runTaskBeaconTask(
  payload: TaskBeaconRunRequest,
  options?: RequestOptions,
): Promise<TaskBeaconActionResponse> {
  return requestJson<TaskBeaconActionResponse>(
    '/api/taskbeacon/run',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}
