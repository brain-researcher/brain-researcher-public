/**
 * Single Workflow API
 * Reads from configs/workflows/workflow_catalog.yaml
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWorkflowById } from '@/lib/server/workflow-catalog'

export const dynamic = 'force-dynamic'

export async function GET(
  _req: NextRequest,
  { params }: { params: { workflowId: string } }
) {
  const workflowId = params.workflowId
  const { workflow, version } = getWorkflowById(workflowId)

  if (!workflow) {
    return NextResponse.json({ error: 'workflow_not_found' }, { status: 404 })
  }

  return NextResponse.json({ ...workflow, version })
}
