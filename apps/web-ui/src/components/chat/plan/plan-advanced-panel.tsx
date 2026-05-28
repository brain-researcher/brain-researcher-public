'use client'

import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

type PlanAdvancedPanelProps = {
  title?: string
  description?: string
  children: ReactNode
  defaultOpen?: boolean
}

export function PlanAdvancedPanel({
  title = 'Advanced',
  description = 'Detailed controls, verification, parameters, and handoff stay here.',
  children,
  defaultOpen = false,
}: PlanAdvancedPanelProps) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <Card>
        <CardHeader className="pb-2">
          <CollapsibleTrigger
            data-testid="plan-advanced-toggle"
            className="flex w-full items-center justify-between gap-3 text-left"
          >
            <div>
              <CardTitle className="text-sm">{title}</CardTitle>
              <div className="text-sm text-muted-foreground">{description}</div>
            </div>
            <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform data-[state=open]:rotate-180')} />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent data-testid="plan-advanced-content">
          <CardContent className="space-y-6 pt-0">{children}</CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
