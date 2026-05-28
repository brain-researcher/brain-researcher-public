import { serviceEndpoints } from '@/lib/service-endpoints'

export type StudioNotebookMode = 'preview' | 'edit'

export type StudioNotebookCellType = 'code' | 'markdown'

export type StudioNotebookOutputType =
  | 'stream'
  | 'display_data'
  | 'execute_result'
  | 'error'

export interface StudioNotebookOutput {
  output_type: StudioNotebookOutputType
  name?: 'stdout' | 'stderr'
  text?: string | string[]
  data?: Record<string, unknown>
  metadata?: Record<string, unknown>
  ename?: string
  evalue?: string
  traceback?: string[]
}

export type StudioNotebookCellStatus = 'idle' | 'running' | 'finished' | 'error'

export interface StudioNotebookCell {
  id: string
  cell_type: StudioNotebookCellType
  source: string
  metadata: Record<string, unknown>
  outputs: StudioNotebookOutput[]
  execution_count: number | null
  status: StudioNotebookCellStatus
}

export interface StudioNotebookDocument {
  id: string
  project_id: string
  session_id: string | null
  path: string
  title: string
  kernel_name: string
  format: 'ipynb'
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  last_saved_at: string | null
  revision: number
  cells: StudioNotebookCell[]
}

export interface StudioNotebookOperation {
  type:
    | 'append'
    | 'edit'
    | 'ai_edit'
    | 'edit_and_move'
    | 'delete_cell'
    | 'move_cell'
    | 'replace_cell'
    | 'apply_outputs'
  cell_id?: string
  cell_type?: StudioNotebookCellType
  source?: string
  after_cell_id?: string | null
  target_index?: number
  outputs?: StudioNotebookOutput[]
  execution_count?: number | null
  status?: StudioNotebookCellStatus
  metadata?: Record<string, unknown>
  reason?: string
}

export interface StudioNotebookRequest {
  notebook_path?: string | null
  title?: string | null
  kernel_name?: string | null
  metadata?: Record<string, unknown>
}

export interface StudioNotebookExecutionRequest {
  cell_id: string
  notebook_path?: string | null
  runtime_profile_id?: string | null
  working_directory?: string | null
  timeout_seconds?: number | null
  metadata?: Record<string, unknown>
}

type RequestOptions = {
  accessToken?: string | null
  signal?: AbortSignal
}

function toBackendCellStatus(status: StudioNotebookCellStatus): string {
  if (status === 'finished') return 'succeeded'
  if (status === 'error') return 'failed'
  return status
}

function toBackendNotebookPayload(payload: StudioNotebookDocument) {
  return {
    title: payload.title,
    metadata: payload.metadata,
    expected_revision: payload.revision,
    cells: payload.cells.map((cell) => ({
      id: cell.id,
      cell_type: cell.cell_type,
      source: cell.source,
      metadata: cell.metadata,
      outputs: cell.outputs,
      execution_count: cell.execution_count,
      status: toBackendCellStatus(cell.status),
    })),
  }
}

const STUDIO_NOTEBOOKS_BASE = '/api/studio/sessions'

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
    throw new Error(`Studio notebook gateway request failed: ${detail}`)
  }

  return (await response.json()) as T
}

const notebookBasePath = (sessionId: string) =>
  `${STUDIO_NOTEBOOKS_BASE}/${encodeURIComponent(sessionId)}/notebook`

export async function getStudioNotebook(
  sessionId: string,
  options?: RequestOptions,
): Promise<StudioNotebookDocument> {
  const response = await requestJson<{ notebook: StudioNotebookDocument }>(
    notebookBasePath(sessionId),
    { method: 'GET' },
    options,
  )
  return response.notebook
}

export async function openOrCreateStudioNotebook(
  sessionId: string,
  payload: StudioNotebookRequest = {},
  options?: RequestOptions,
): Promise<StudioNotebookDocument> {
  const response = await requestJson<{ notebook: StudioNotebookDocument }>(
    `${notebookBasePath(sessionId)}/open-or-create`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
  return response.notebook
}

export async function saveStudioNotebook(
  sessionId: string,
  payload: StudioNotebookDocument,
  options?: RequestOptions,
): Promise<StudioNotebookDocument> {
  const response = await requestJson<{ notebook: StudioNotebookDocument }>(
    notebookBasePath(sessionId),
    {
      method: 'PATCH',
      body: JSON.stringify(toBackendNotebookPayload(payload)),
    },
    options,
  )
  return response.notebook
}

export async function applyStudioNotebookOps(
  sessionId: string,
  ops: StudioNotebookOperation[],
  options?: RequestOptions,
): Promise<StudioNotebookDocument> {
  const response = await requestJson<{ notebook: StudioNotebookDocument }>(
    `${notebookBasePath(sessionId)}/ops`,
    {
      method: 'POST',
      body: JSON.stringify({ ops }),
    },
    options,
  )
  return response.notebook
}

export async function executeStudioNotebookCell(
  sessionId: string,
  payload: StudioNotebookExecutionRequest,
  options?: RequestOptions,
): Promise<unknown> {
  return requestJson<unknown>(
    `${notebookBasePath(sessionId)}/cells/${encodeURIComponent(payload.cell_id)}/execute`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    options,
  )
}
