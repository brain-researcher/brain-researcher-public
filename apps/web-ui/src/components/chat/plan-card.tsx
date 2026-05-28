'use client'

import { Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type PlanCardProps = {
  title: string
  description?: string
  estRuntime?: string
  official?: boolean
  onReplacePlan?: () => void
  onAskAgent?: () => void
}

export function PlanCard({
  title,
  description,
  estRuntime,
  official = true,
  onAskAgent,
  onReplacePlan,
}: PlanCardProps) {
  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            Recommended Plan
          </span>
          {official ? <Badge>Official ✓</Badge> : <Badge variant="secondary">Suggested</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">{title}</div>
          {description ? (
            <div className="text-sm text-muted-foreground">{description}</div>
          ) : null}
          {estRuntime ? (
            <div className="text-xs text-muted-foreground">Est. runtime: {estRuntime}</div>
          ) : null}
        </div>
        {onReplacePlan || onAskAgent ? (
          <div className="flex flex-wrap gap-2">
            {onReplacePlan ? (
              <Button size="sm" onClick={onReplacePlan}>
                Replace Plan
              </Button>
            ) : null}
            {onAskAgent ? (
              <Button variant="outline" size="sm" onClick={onAskAgent}>
                Ask Agent
              </Button>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

