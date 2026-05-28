import { Badge } from '@/components/ui/badge'
import type { StudioPlanProjectionStatus } from './studio-plan-projection-types'

const BADGE_VARIANT: Record<StudioPlanProjectionStatus, 'default' | 'outline' | 'destructive' | 'secondary'> = {
  ready: 'default',
  warning: 'outline',
  blocked: 'destructive',
  running: 'secondary',
}

const LABEL: Record<StudioPlanProjectionStatus, string> = {
  ready: 'Ready',
  warning: 'Warning',
  blocked: 'Blocked',
  running: 'Running',
}

type PlanHeaderProps = {
  title: string
  status: StudioPlanProjectionStatus
  intentSummary: string
  provenance: string
  lastUpdated: string
}

export function PlanHeader({ title, status, intentSummary, provenance, lastUpdated }: PlanHeaderProps) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-foreground">{title}</div>
          <div className="text-sm text-muted-foreground">
            Read-only projection of what the agent is preparing to run.
          </div>
        </div>
        <Badge variant={BADGE_VARIANT[status]}>{LABEL[status]}</Badge>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Intent</div>
        <div className="mt-2 text-sm text-foreground">{intentSummary}</div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{provenance}</span>
          <span>{lastUpdated}</span>
        </div>
      </div>
    </section>
  )
}
