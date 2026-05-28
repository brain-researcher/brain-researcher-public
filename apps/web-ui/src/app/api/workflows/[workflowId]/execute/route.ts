import { NextRequest, NextResponse } from 'next/server'

import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { estimateCreditsFromRuntime } from '@/lib/server/credits'
import { fetchWorkflowRuntimePreflight, runWorkflowTool } from '@/lib/server/workflow-execution'
import { deriveRecipeLaunchStatus } from '@/lib/server/launch-decision'
import {
  mergeWorkflowParams,
  resolveWorkflowParamContract,
  validateWorkflowParams,
} from '@/lib/server/workflow-params'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const CREDITS_ENFORCEMENT_ENABLED =
  process.env.BR_CREDITS_ENFORCEMENT === '0' ||
  process.env.NEXT_PUBLIC_CREDITS_ENFORCEMENT === '0'
    ? false
    : process.env.NODE_ENV !== 'test'

function safeObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function hasDeclarativeRuntimeSteps(workflow: {
  runtime?: { kind?: string; steps?: unknown[] }
}): boolean {
  const runtimeKind = String(workflow.runtime?.kind || '')
    .trim()
    .toLowerCase()
  const isDeclarative =
    runtimeKind === 'declarative_workflow' ||
    runtimeKind === 'declarative' ||
    runtimeKind === ''
  if (!isDeclarative) return false
  return Array.isArray(workflow.runtime?.steps) && workflow.runtime.steps.length > 0
}

function isWorkflowDirectRunEnabled(workflow: {
  lifecycle?: string
  runtime?: { kind?: string; steps?: unknown[] }
}): boolean {
  const lifecycle = String(workflow.lifecycle || '')
    .trim()
    .toLowerCase()
  return lifecycle !== 'deprecated' && hasDeclarativeRuntimeSteps(workflow)
}

function isExecutionSuccess(payload: unknown): boolean {
  const objectPayload = safeObject(payload)
  const resultPayload = safeObject(objectPayload.result)
  const status = String(resultPayload.status || '').trim().toLowerCase()
  if (!status) return true
  return status === 'success'
}

export async function POST(
  req: NextRequest,
  { params }: { params: { workflowId: string } },
) {
  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json(
      { error: 'E-UNAUTHORIZED', detail: 'Authentication required.' },
      { status: 401 },
    )
  }

  const workflowId = String(params.workflowId || '').trim()
  const { workflow } = getWorkflowById(workflowId)
  if (!workflow) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_NOT_FOUND',
          message: `Workflow "${workflowId}" was not found.`,
        },
      },
      { status: 404 },
    )
  }
  if (!isWorkflowDirectRunEnabled(workflow)) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_NOT_ENABLED',
          message:
            `Workflow "${workflowId}" is not eligible for direct Library execution. ` +
            'Direct Run requires declarative runtime steps and lifecycle other than deprecated.',
        },
      },
      { status: 400 },
    )
  }
  const recipeLaunchStatus = deriveRecipeLaunchStatus(workflow)
  if (recipeLaunchStatus !== 'launchable') {
    const manualAdminOnly = recipeLaunchStatus === 'manual_admin_only'
    return NextResponse.json(
      {
        error: {
          code: manualAdminOnly ? 'WF_MANUAL_ADMIN_ONLY' : 'WF_HANDOFF_ONLY',
          message: manualAdminOnly
            ? `Workflow "${workflowId}" is marked manual/admin only and cannot be executed directly.`
            : `Workflow "${workflowId}" does not advertise a launchable recipe in the current environment.`,
        },
        launch_status: recipeLaunchStatus,
      },
      { status: 409 },
    )
  }

  let bodyRaw: unknown = {}
  try {
    bodyRaw = await req.json()
  } catch {
    bodyRaw = {}
  }
  const body = safeObject(bodyRaw)

  const contract = resolveWorkflowParamContract(workflow)
  const resolvedParams = mergeWorkflowParams(contract, body.params)
  const issues = validateWorkflowParams(contract, resolvedParams)

  if (issues.length > 0) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_PARAMS_INVALID',
          message: 'Parameter validation failed. Update the highlighted fields and validate again.',
          details: { issues },
        },
      },
      { status: 422 },
    )
  }

  if (
    CREDITS_ENFORCEMENT_ENABLED &&
    estimateCreditsFromRuntime(workflow.est_runtime) == null
  ) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_CREDIT_ESTIMATE_UNAVAILABLE',
          message:
            'Credit estimate unavailable for this launchable workflow. Add a runtime estimate or use a handoff-only route.',
        },
        resolved_params: resolvedParams,
      },
      { status: 409 },
    )
  }

  const runtimePreflight = await fetchWorkflowRuntimePreflight(req, workflow.id)
  if (!runtimePreflight.ok) {
    const failure = runtimePreflight as { ok: false; status: number; detail: string }
    return NextResponse.json(
      {
        error: {
          code: 'WF_UPSTREAM_UNAVAILABLE',
          message: 'Runtime preflight service is unavailable. Please retry in a moment.',
          details: { status: failure.status, detail: failure.detail },
        },
      },
      { status: 503 },
    )
  }

  if (runtimePreflight.payload.executable !== true) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_PREFLIGHT_FAILED',
          message:
            'This workflow cannot run in the current environment. Review runtime checks and resolve missing tools.',
          details: {
            checks: runtimePreflight.payload.checks ?? [],
            warnings: runtimePreflight.payload.warnings ?? [],
            guidance: runtimePreflight.payload.guidance ?? null,
          },
        },
        resolved_params: resolvedParams,
        guidance: runtimePreflight.payload.guidance ?? null,
      },
      { status: 409 },
    )
  }

  const execution = await runWorkflowTool(req, workflow.id, resolvedParams)
  if (!execution.ok) {
    const failure = execution as {
      ok: false
      status: number
      detail: string
      payload?: unknown
    }
    return NextResponse.json(
      {
        error: {
          code: 'WF_EXECUTION_FAILED',
          message: 'Workflow execution failed. Please review the error details and retry.',
          details: { status: failure.status, detail: failure.detail, payload: failure.payload },
        },
        resolved_params: resolvedParams,
      },
      { status: failure.status >= 400 ? failure.status : 500 },
    )
  }

  if (!isExecutionSuccess(execution.payload)) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_EXECUTION_FAILED',
          message: 'Workflow execution failed. Please review the error details and retry.',
          details: { payload: execution.payload },
        },
        resolved_params: resolvedParams,
      },
      { status: 500 },
    )
  }

  return NextResponse.json({
    status: 'success',
    workflow_id: workflow.id,
    resolved_params: resolvedParams,
    result: execution.payload,
  })
}
