import { Badge } from '@/components/ui/badge'
import type { StudioPlanProjectionStatus } from './studio-plan-projection-types'

const BADGE_VARIANT: Record<StudioPlanProjectionStatus, 'default' | 'outline' | 'destructive' | 'secondary'> = {
  ready: 'default',
  warning: 'outline',
  blocked: 'destructive',
  running: 'secondary',
}

const BADGE_LABEL: Record<StudioPlanProjectionStatus, string> = {
  ready: 'Ready',
  warning: 'Warnings',
  blocked: 'Blocked',
  running: 'Running',
}

type ReadOnlyPlanHeaderProps = {
  title: string
  status: StudioPlanProjectionStatus
  intentSummary: string
  provenance: string
}

export function ReadOnlyPlanHeader({
  title,
  status,
  intentSummary,
  provenance,
}: ReadOnlyPlanHeaderProps) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-foreground">{title}</div>
          <div className="text-sm text-muted-foreground">
            Read-only projection of the agent&apos;s current execution plan.
          </div>
        </div>
        <Badge variant={BADGE_VARIANT[status]}>{BADGE_LABEL[status]}</Badge>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Intent</div>
        <div className="mt-2 text-sm text-foreground">{intentSummary}</div>
        <div className="mt-3 text-xs text-muted-foreground">{provenance}</div>
      </div>
    </section>
  )
}
