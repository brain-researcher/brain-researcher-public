import { NextResponse } from 'next/server'
import { load_behavior_policies } from '@/lib/server/behavior-policies'

export async function GET() {
  try {
    const policies = await load_behavior_policies()
    return NextResponse.json({ policies })
  } catch (error: any) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}
