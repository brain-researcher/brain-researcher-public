/**
 * Workflow Stages List API
 * Returns unique stages from workflow_catalog.yaml
 */
import { NextResponse } from 'next/server'
import { listWorkflowStages } from '@/lib/server/workflow-catalog'

export const dynamic = 'force-dynamic'

export async function GET() {
  const stages = listWorkflowStages()
  return NextResponse.json({ stages })
}
