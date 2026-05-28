import { notFound } from 'next/navigation'

import { DemoReplayWorkbench } from '@/components/demos/DemoReplayWorkbench'
import { resolveDemoEntry } from '@/lib/server/demo-index'

export default function DemoResultPackagePage({ params }: { params: { demoId: string } }) {
  const entry = resolveDemoEntry(params.demoId || '')
  if (!entry) {
    notFound()
  }
  return <DemoReplayWorkbench demoId={entry.slug} />
}

export const dynamic = 'force-dynamic'
