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

type ReadOnlyPlanRunGateProps = {
  status: StudioPlanProjectionStatus
  runtime: string
  primaryLabel: string
  secondaryLabel?: string
  canRun: boolean
  isSubmitting?: boolean
  onPrimaryAction: () => void
  onSecondaryAction?: () => void
}

export function ReadOnlyPlanRunGate({
  status,
  runtime,
  primaryLabel,
  secondaryLabel,
  canRun,
  isSubmitting,
  onPrimaryAction,
  onSecondaryAction,
}: ReadOnlyPlanRunGateProps) {
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
            ? 'The current plan passes the required checks. Approve and run when ready.'
            : 'Execution stays blocked until the agent or advanced editor resolves the missing inputs.'}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" disabled={!canRun || Boolean(isSubmitting)} onClick={onPrimaryAction}>
            {isSubmitting ? 'Starting…' : primaryLabel}
          </Button>
          {secondaryLabel && onSecondaryAction ? (
            <Button type="button" variant="outline" size="sm" onClick={onSecondaryAction}>
              {secondaryLabel}
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
