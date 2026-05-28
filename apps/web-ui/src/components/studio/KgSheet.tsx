'use client'

import { useMemo } from 'react'

import { Button } from '@/components/ui/button'
import { SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'

type KgSheetProps = {
  onOpenExplorer: () => void
  onOpenSuggestions: () => void
  onAskAssistant: () => void
}

export function KgSheet({
  onOpenExplorer,
  onOpenSuggestions,
  onAskAssistant,
}: KgSheetProps) {
  const helperCopy = useMemo(() => {
    return [
      'Use the knowledge graph to explore concepts and evidence.',
      'Review Suggestions to accept/reject proposed updates from your analyses.',
    ].join(' ')
  }, [])

  return (
    <SheetContent
      side="right"
      className="w-[92vw] max-w-[520px] overflow-y-auto"
    >
      <SheetHeader>
        <SheetTitle>Knowledge Graph</SheetTitle>
        <SheetDescription>{helperCopy}</SheetDescription>
      </SheetHeader>

      <div className="mt-6 space-y-4">
        <div className="rounded-lg border bg-muted/20 p-4 text-sm text-muted-foreground">
          Tip: if you get stuck, use “Ask assistant” and describe what concept or evidence you’re looking for.
        </div>

        <div className="flex flex-col gap-2">
          <Button onClick={onOpenExplorer}>Open Explorer</Button>
          <Button variant="outline" onClick={onOpenSuggestions}>
            Review Suggestions
          </Button>
          <Button variant="outline" onClick={onAskAssistant}>
            Ask assistant
          </Button>
        </div>
      </div>
    </SheetContent>
  )
}
