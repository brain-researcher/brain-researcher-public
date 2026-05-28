import { AlertCircle, Bot, Info } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { StudioPlanProjectionAlert } from './studio-plan-projection-types'

type WorkflowCardProps = {
  alerts: StudioPlanProjectionAlert[]
}

export function WorkflowCard({ alerts }: WorkflowCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Needs attention</CardTitle>
          <Badge variant={alerts.some((alert) => alert.severity === 'blocked') ? 'destructive' : 'outline'}>
            {alerts.some((alert) => alert.severity === 'blocked') ? 'Blocked' : 'Warnings'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {alerts.map((alert) => {
          const Icon = alert.severity === 'blocked' ? AlertCircle : Info
          return (
            <div key={alert.id} className="flex items-start gap-3 rounded-md border bg-muted/20 p-3">
              <Icon
                className={alert.severity === 'blocked' ? 'mt-0.5 h-4 w-4 text-destructive' : 'mt-0.5 h-4 w-4 text-amber-600'}
              />
              <div className="text-sm text-foreground">{alert.message}</div>
            </div>
          )
        })}
        <div>
          <Button type="button" variant="outline" size="sm" className="gap-2">
            <Bot className="h-4 w-4" />
            Let agent fix this in chat
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
