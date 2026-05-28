import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { StudioPlanProjectionStatus } from './studio-plan-projection-types'

const BADGE_LABEL: Record<StudioPlanProjectionStatus, string> = {
  ready: 'Ready to run',
  warning: 'Warnings present',
  blocked: 'Run blocked',
  running: 'Running',
}

type RunGateCardProps = {
  status: StudioPlanProjectionStatus
  runtime: string
  primaryLabel: string
  secondaryLabel: string
  canRun: boolean
}

export function RunGateCard({ status, runtime, primaryLabel, secondaryLabel, canRun }: RunGateCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Run gate</CardTitle>
          <Badge variant={status === 'blocked' ? 'destructive' : status === 'warning' ? 'outline' : 'default'}>
            {BADGE_LABEL[status]}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div className="text-sm text-muted-foreground">Estimated runtime: {runtime}</div>
        <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
          {canRun
            ? 'The agent has resolved the required inputs. You can approve and run this plan.'
            : 'Run stays blocked until the missing planning issue is resolved in chat.'}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" disabled={!canRun}>
            {primaryLabel}
          </Button>
          <Button type="button" variant="outline" size="sm">
            {secondaryLabel}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
