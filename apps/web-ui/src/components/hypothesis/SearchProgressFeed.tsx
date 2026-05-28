'use client'

import type { ProgressEvent, ProgressStage } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type SearchProgressFeedProps = {
  currentStage: ProgressStage
  events: ProgressEvent[]
}

const STAGE_STYLE: Record<ProgressStage, string> = {
  clarifying: 'bg-slate-100 text-slate-700',
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

export function SearchProgressFeed({ currentStage, events }: SearchProgressFeedProps) {
  const visible = events.slice(-8)

  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Search Progress</CardTitle>
          <Badge variant="outline">stage: {currentStage}</Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
          {visible.length ? (
            visible.map((event, idx) => (
              <div key={`${event.ts}-${idx}`} className="rounded-md border border-border/70 p-2 text-xs">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className={`inline-flex rounded px-2 py-0.5 font-medium ${STAGE_STYLE[event.stage]}`}>
                    {event.stage}
                  </span>
                  <span className="text-muted-foreground">{new Date(event.ts).toLocaleTimeString()}</span>
                </div>
                <div>{event.message}</div>
                {event.metrics ? (
                  <div className="text-muted-foreground mt-1">
                    {Object.entries(event.metrics)
                      .map(([key, value]) => `${key}: ${value}`)
                      .join(' | ')}
                  </div>
                ) : null}
              </div>
            ))
          ) : (
            <div className="text-xs text-muted-foreground">
              Waiting for query. Send a broad research term in chat to begin clarifying intent.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
