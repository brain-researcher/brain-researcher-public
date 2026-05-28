/**
 * Workflow Catalog API
 * Serves workflows from configs/workflows/workflow_catalog.yaml
 */
import { NextRequest, NextResponse } from 'next/server'
import { listWorkflows } from '@/lib/server/workflow-catalog'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const url = new URL(req.url)
  const params = url.searchParams

  const response = listWorkflows({
    stage: params.get('stage') || undefined,
    cost_tier: params.get('cost_tier') || undefined,
    modality: params.get('modality') || undefined,
    limit: params.get('limit') ? Number(params.get('limit')) : undefined,
    offset: params.get('offset') ? Number(params.get('offset')) : undefined,
  })

  return NextResponse.json(response)
}
