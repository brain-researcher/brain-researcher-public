import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest, { params }: { params: { jobId: string } }) {
  const { jobId } = params
  const target = new URL(`/api/analyses/${encodeURIComponent(jobId)}/events`, req.url)
  return NextResponse.redirect(target, 307)
}
