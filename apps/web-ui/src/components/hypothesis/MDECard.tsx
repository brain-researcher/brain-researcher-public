'use client'

import type { MDEPlan } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type MDECardProps = {
  mde: MDEPlan | null
}

export function MDECard({ mde }: MDECardProps) {
  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between gap-2">
          <span>Minimum Discriminating Test (MDE)</span>
          <Badge variant="outline">{mde?.status || 'draft'}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {!mde ? (
          <div className="text-xs text-muted-foreground">No MDE plan yet.</div>
        ) : (
          <>
            <div>
              <div className="text-xs font-medium">Objective</div>
              <div className="text-sm text-muted-foreground">{mde.objective}</div>
            </div>
            <div>
              <div className="text-xs font-medium">Cheapest test</div>
              <div className="text-sm text-muted-foreground">{mde.minimal_test}</div>
            </div>
            <div>
              <div className="text-xs font-medium">Falsifier</div>
              <div className="text-sm text-muted-foreground">{mde.falsifier}</div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <div className="text-xs font-medium">Expected signals</div>
                <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground space-y-1">
                  {mde.expected_signals.length ? (
                    mde.expected_signals.map((signal, idx) => <li key={`signal-${idx}`}>{signal}</li>)
                  ) : (
                    <li>Not specified</li>
                  )}
                </ul>
              </div>
              <div>
                <div className="text-xs font-medium">Confounds</div>
                <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground space-y-1">
                  {mde.confounds.length ? (
                    mde.confounds.map((confound, idx) => <li key={`confound-${idx}`}>{confound}</li>)
                  ) : (
                    <li>Not specified</li>
                  )}
                </ul>
              </div>
            </div>
            {mde.cost_estimate ? (
              <div className="text-xs text-muted-foreground">Estimated cost: {mde.cost_estimate}</div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}
