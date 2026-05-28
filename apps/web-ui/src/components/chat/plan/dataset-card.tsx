import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { StudioPlanProjectionRow } from './studio-plan-projection-types'

const STATUS_BADGE: Record<NonNullable<StudioPlanProjectionRow['status']>, { label: string; variant: 'default' | 'outline' | 'destructive' | 'secondary' }> = {
  passed: { label: 'Ready', variant: 'default' },
  warning: { label: 'Warning', variant: 'outline' },
  blocked: { label: 'Blocked', variant: 'destructive' },
  info: { label: 'Info', variant: 'secondary' },
}

type DatasetCardProps = {
  rows: StudioPlanProjectionRow[]
}

export function DatasetCard({ rows }: DatasetCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Plan summary</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-0">
        {rows.map((row) => {
          const status = row.status ? STATUS_BADGE[row.status] : null
          return (
            <div key={row.id} className="flex items-start justify-between gap-3 border-b pb-4 last:border-b-0 last:pb-0">
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {row.label}
                </div>
                <div className="mt-1 text-sm font-medium text-foreground">{row.value}</div>
                {row.detail ? <div className="mt-1 text-sm text-muted-foreground">{row.detail}</div> : null}
              </div>
              {status ? <Badge variant={status.variant}>{status.label}</Badge> : null}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
