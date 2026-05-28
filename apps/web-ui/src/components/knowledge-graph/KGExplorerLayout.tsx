'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Code2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'

export type KGExplorerLayoutProps = {
  children: ReactNode
}

const KG_HANDOFF_PROMPT =
  'Use the Brain Researcher knowledge graph to ground further analysis. Start with br.kg_context() to load the current context, then explore relevant nodes via br.kg_neighbors(node_id="<node_id>").'

export function KGExplorerLayout({ children }: KGExplorerLayoutProps) {
  const [handoffOpen, setHandoffOpen] = useState(false)

  const handoffPayload: HandoffTemplatePayload = {
    kind: 'template',
    workflowId: 'kg_context',
    workflowLabel: 'Knowledge Graph context',
    promptOverride: KG_HANDOFF_PROMPT,
    title: 'Hand off KG context',
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">{children}</div>
      <aside className="space-y-4">
        <Card>
          <CardContent className="p-4 space-y-3">
            <div className="text-sm font-medium">Continue with this context</div>
            <p className="text-xs text-muted-foreground">
              Open Studio to keep exploring graph evidence, or hand off the context to your coding agent.
            </p>
            {/* TODO(kg-studio-injection): auto-inject br.kg_context(...) cell once the Marimo embedding API lands. */}
            <Button asChild className="w-full">
              <Link href="/studio?kgContext=1" prefetch={false}>
                Open in Studio
              </Link>
            </Button>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => setHandoffOpen(true)}
            >
              <Code2 className="mr-2 h-4 w-4" />
              Hand off
            </Button>
          </CardContent>
        </Card>
      </aside>
      <HandoffModal
        open={handoffOpen}
        onClose={() => setHandoffOpen(false)}
        mode="template"
        payload={handoffPayload}
      />
    </div>
  )
}
