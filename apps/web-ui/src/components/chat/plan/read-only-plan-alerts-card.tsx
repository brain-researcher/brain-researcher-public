import { AlertCircle, Bot, Info } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { StudioPlanProjectionAlert } from './studio-plan-projection-types'

type ReadOnlyPlanAlertsCardProps = {
  alerts: StudioPlanProjectionAlert[]
  onAskAgent?: () => void
}

export function ReadOnlyPlanAlertsCard({ alerts, onAskAgent }: ReadOnlyPlanAlertsCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Needs attention</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {alerts.length ? (
          alerts.map((alert) => {
            const Icon = alert.severity === 'blocked' ? AlertCircle : Info
            return (
              <div key={alert.id} className="flex items-start gap-3 rounded-md border bg-muted/20 p-3">
                <Icon
                  className={
                    alert.severity === 'blocked'
                      ? 'mt-0.5 h-4 w-4 text-destructive'
                      : 'mt-0.5 h-4 w-4 text-amber-600'
                  }
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">{alert.label}</div>
                  <div className="mt-1 text-sm text-muted-foreground">{alert.message}</div>
                </div>
              </div>
            )
          })
        ) : (
          <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            No blockers. The agent has prepared a runnable draft.
          </div>
        )}
        {onAskAgent ? (
          <div>
            <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onAskAgent}>
              <Bot className="h-4 w-4" />
              Ask agent to revise plan
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
