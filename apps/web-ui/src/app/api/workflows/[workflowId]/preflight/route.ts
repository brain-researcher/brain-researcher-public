import { NextRequest, NextResponse } from 'next/server'

import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { fetchWorkflowRuntimePreflight } from '@/lib/server/workflow-execution'
import {
  mergeWorkflowParams,
  resolveWorkflowParamContract,
  validateWorkflowParams,
} from '@/lib/server/workflow-params'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function safeObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function parseStrictFlag(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true
    if (['false', '0', 'no', 'off'].includes(normalized)) return false
  }
  return fallback
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
  const { workflow, version } = getWorkflowById(workflowId)
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

  let bodyRaw: unknown = {}
  try {
    bodyRaw = await req.json()
  } catch {
    bodyRaw = {}
  }
  const body = safeObject(bodyRaw)
  const strict = parseStrictFlag(body.strict, true)

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

  const checks = Array.isArray(runtimePreflight.payload.checks) ? runtimePreflight.payload.checks : []
  const warnings = Array.isArray(runtimePreflight.payload.warnings)
    ? [...runtimePreflight.payload.warnings]
    : []
  const guidance = runtimePreflight.payload.guidance ?? null

  if (contract.missingContractFields.length > 0) {
    warnings.push(
      `This workflow has incomplete parameter metadata. Placeholder fields were inferred: ${contract.missingContractFields.join(', ')}.`,
    )
  }

  const executable = runtimePreflight.payload.executable === true
  if (!executable && strict) {
    return NextResponse.json(
      {
        error: {
          code: 'WF_PREFLIGHT_FAILED',
          message:
            'This workflow cannot run in the current environment. Review runtime checks and resolve missing tools.',
          details: {
            checks,
            warnings,
            guidance,
          },
        },
        workflow_id: workflow.id,
        version,
        resolved_params: resolvedParams,
        guidance,
      },
      { status: 409 },
    )
  }

  return NextResponse.json({
    ok: executable,
    workflow_id: workflow.id,
    version,
    strict,
    resolved_params: resolvedParams,
    checks,
    warnings,
    guidance,
    missing_contract_fields: contract.missingContractFields,
  })
}
