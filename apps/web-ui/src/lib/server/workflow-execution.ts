import type { NextRequest } from 'next/server'

import {
  forwardAuthHeaders,
  resolveAgentBaseUrl,
  resolveOrchestratorBaseUrl,
} from '@/lib/server/downstream'

export type RuntimeToolCheck = {
  tool_id?: string
  status?: string
  available?: boolean
  exists?: boolean
  detail?: string | null
}

export type RuntimeSetupAction = {
  id?: string
  label?: string
  href?: string
  external?: boolean
}

export type RuntimeSetupGuidance = {
  kind?: string
  access_mode?: string
  runtime_target?: string
  install_path?: string
  summary?: string
  detail?: string | null
  next_action_url?: string | null
  docs_urls?: string[]
  actions?: RuntimeSetupAction[]
  required_modules?: string[]
  required_env_vars?: string[]
  container_images?: Record<string, string>
  supported_recipe_targets?: string[]
  workflow_id?: string | null
}

export type RuntimePreflightPayload = {
  executable?: boolean
  checks?: RuntimeToolCheck[]
  warnings?: string[]
  guidance?: RuntimeSetupGuidance | null
}

type RuntimePreflightResult =
  | {
      ok: true
      payload: RuntimePreflightPayload
      status: number
    }
  | {
      ok: false
      status: number
      detail: string
    }

export async function fetchWorkflowRuntimePreflight(
  req: NextRequest,
  workflowId: string,
): Promise<RuntimePreflightResult> {
  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  try {
    const upstream = await fetch(`${resolveOrchestratorBaseUrl()}/api/preflight/check`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ workflow_id: workflowId }),
      cache: 'no-store',
    })

    const raw = await upstream.text()
    if (!upstream.ok) {
      return {
        ok: false,
        status: upstream.status,
        detail: raw || upstream.statusText,
      }
    }

    let payload: RuntimePreflightPayload
    try {
      payload = JSON.parse(raw) as RuntimePreflightPayload
    } catch {
      return {
        ok: false,
        status: 502,
        detail: 'Runtime preflight returned invalid JSON.',
      }
    }

    return { ok: true, payload, status: upstream.status }
  } catch (error) {
    return {
      ok: false,
      status: 503,
      detail: error instanceof Error ? error.message : 'Runtime preflight unavailable.',
    }
  }
}

type ToolRunResult =
  | {
      ok: true
      status: number
      payload: unknown
    }
  | {
      ok: false
      status: number
      detail: string
      payload?: unknown
    }

export async function runWorkflowTool(
  req: NextRequest,
  workflowId: string,
  params: Record<string, unknown>,
): Promise<ToolRunResult> {
  const headers = forwardAuthHeaders(req)
  headers.set('content-type', 'application/json')

  try {
    const upstream = await fetch(`${resolveAgentBaseUrl()}/api/tools/run`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        tool: workflowId,
        arguments: params,
      }),
      cache: 'no-store',
    })

    const raw = await upstream.text()
    let payload: unknown = null
    if (raw) {
      try {
        payload = JSON.parse(raw)
      } catch {
        payload = raw
      }
    }

    if (!upstream.ok) {
      return {
        ok: false,
        status: upstream.status,
        detail:
          (typeof payload === 'object' && payload && 'detail' in (payload as Record<string, unknown>)
            ? String((payload as Record<string, unknown>).detail)
            : '') || String(raw || upstream.statusText || 'Workflow execution failed.'),
        payload,
      }
    }

    return {
      ok: true,
      status: upstream.status,
      payload,
    }
  } catch (error) {
    return {
      ok: false,
      status: 503,
      detail: error instanceof Error ? error.message : 'Workflow execution service unavailable.',
    }
  }
}
