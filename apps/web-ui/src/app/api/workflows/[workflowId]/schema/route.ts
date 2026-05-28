import { NextRequest, NextResponse } from 'next/server'

import { getWorkflowById } from '@/lib/server/workflow-catalog'
import { resolveWorkflowParamContract } from '@/lib/server/workflow-params'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

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

export async function GET(
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

  const contract = resolveWorkflowParamContract(workflow)
  return NextResponse.json({
    workflow_id: workflow.id,
    version,
    direct_run_enabled: isWorkflowDirectRunEnabled(workflow),
    schema_source: workflow.params?.schema ? 'catalog' : 'runtime_placeholders',
    schema: contract.schema,
    defaults: contract.defaultsBySource,
    discovered_inputs: contract.discoveredInputKeys,
    missing_contract_fields: contract.missingContractFields,
  })
}
