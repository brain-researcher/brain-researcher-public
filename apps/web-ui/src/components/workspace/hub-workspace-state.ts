import type {
  CreateHubSessionRequest,
  HubWorkspaceHandoff,
  HubWorkspaceHandoffRequest,
} from '@/lib/api/hub-sessions'

export interface ParsedHubLaunchRequest {
  sessionId: string | null
  createPayload: CreateHubSessionRequest
  handoffPayload: HubWorkspaceHandoffRequest
}

const DEFAULT_PROJECT_ID = 'proj_workspace'
const DEFAULT_DISPLAY_NAME = 'Hosted Workspace'

function clean(value: string | null): string | null {
  const trimmed = (value || '').trim()
  return trimmed || null
}

function parseBooleanFlag(value: string | null): boolean {
  return value === '1' || value === 'true' || value === 'yes' || value === 'on'
}

function extractTaskBeaconRepoName(value: string | null): string | null {
  const trimmed = clean(value)
  if (!trimmed) {
    return null
  }
  const withoutGithub = trimmed
    .replace(/^https?:\/\/github\.com\//i, '')
    .replace(/\/+$/, '')
    .replace(/\.git$/i, '')
  const parts = withoutGithub.split('/').filter(Boolean)
  return parts.length ? parts[parts.length - 1] || null : null
}

function pathPayload(path: string | null): Pick<
  HubWorkspaceHandoffRequest,
  'target_path' | 'notebook_path'
> {
  if (!path) {
    return { target_path: null, notebook_path: null }
  }
  if (path.endsWith('.py')) {
    return { notebook_path: path, target_path: null }
  }
  return { target_path: path, notebook_path: null }
}

export function parseHubLaunchRequest(searchParams: URLSearchParams): ParsedHubLaunchRequest {
  const sessionId = clean(searchParams.get('session_id'))
  const projectId = clean(searchParams.get('project_id')) || DEFAULT_PROJECT_ID
  const taskbeaconRepo = clean(searchParams.get('taskbeacon_repo'))
  const taskbeaconRef = clean(searchParams.get('taskbeacon_ref'))
  const taskbeaconRepoName = extractTaskBeaconRepoName(taskbeaconRepo)
  const displayName =
    clean(searchParams.get('display_name')) ||
    (taskbeaconRepoName ? `TaskBeacon · ${taskbeaconRepoName}` : DEFAULT_DISPLAY_NAME)
  const path =
    clean(searchParams.get('path')) ||
    (taskbeaconRepoName ? `projects/${projectId}/taskbeacon/${taskbeaconRepoName}` : null)
  const artifactId = clean(searchParams.get('artifact_id'))
  const focus = clean(searchParams.get('focus'))
  const materializeNotebook = parseBooleanFlag(
    searchParams.get('materialize_notebook_if_needed'),
  )
  const openCleanWorkspace = parseBooleanFlag(searchParams.get('open_clean_workspace'))
  const sharedPathPayload = pathPayload(path)

  const handoffPayload: HubWorkspaceHandoffRequest = {
    ...sharedPathPayload,
    open_artifact_id: artifactId,
    initial_focus: focus,
    materialize_notebook_if_needed: materializeNotebook,
    open_clean_workspace: openCleanWorkspace,
  }

  const createPayload: CreateHubSessionRequest = {
    project_id: projectId,
    display_name: displayName,
    attach_if_exists: taskbeaconRepo ? false : true,
    taskbeacon_repo: taskbeaconRepo,
    taskbeacon_ref: taskbeaconRef,
    ...handoffPayload,
  }

  return {
    sessionId,
    createPayload,
    handoffPayload,
  }
}

export function handoffHasRuntimeTarget(handoff: HubWorkspaceHandoff | null | undefined): boolean {
  return Boolean(handoff?.runtime_target_url)
}

export function handoffNeedsRuntimePolling(
  handoff: HubWorkspaceHandoff | null | undefined,
): boolean {
  return handoff?.runtime_target_ready !== true
}

export function handoffAllowsDirectRuntimeOpen(
  handoff: HubWorkspaceHandoff | null | undefined,
): boolean {
  return Boolean(handoff?.runtime_target_url) && handoff?.runtime_target_ready === true
}

export function buildHubRuntimeTargetUrl(
  targetUrl: string | null | undefined,
  sessionId: string | null | undefined,
): string | null {
  const normalizedTargetUrl = clean(targetUrl ?? null)
  if (!normalizedTargetUrl) {
    return null
  }
  const normalizedSessionId = clean(sessionId ?? null)
  if (!normalizedSessionId) {
    return normalizedTargetUrl
  }
  try {
    const url = new URL(normalizedTargetUrl)
    url.searchParams.set('session_id', normalizedSessionId)
    return url.toString()
  } catch {
    return normalizedTargetUrl
  }
}
