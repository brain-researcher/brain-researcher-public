import { NextRequest, NextResponse } from 'next/server'

import { streamAnalysisProgress } from '@/app/api/analyses/[analysisId]/stream/route'
import { resolveSharedAnalysisAccess } from '@/lib/server/share-access'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest, { params }: { params: { token: string } }) {
  const token = typeof params.token === 'string' ? params.token.trim() : ''
  const resolved = await resolveSharedAnalysisAccess(token)
  if (resolved.ok === false) {
    return NextResponse.json(resolved.body, { status: resolved.status })
  }

  return streamAnalysisProgress(req, resolved.analysisId)
}
