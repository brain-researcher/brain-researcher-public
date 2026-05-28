import { NextResponse } from 'next/server'

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
