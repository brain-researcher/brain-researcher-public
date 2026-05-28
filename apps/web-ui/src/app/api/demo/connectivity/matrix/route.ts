import { NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function demoDisabled() {
  return NextResponse.json(
    { error: 'demo_disabled', detail: 'Demo routes are disabled.' },
    { status: 410 },
  )
}

export const GET = demoDisabled
export const POST = demoDisabled
export const PUT = demoDisabled
export const PATCH = demoDisabled
export const DELETE = demoDisabled
