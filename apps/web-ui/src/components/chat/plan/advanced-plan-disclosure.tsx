'use client'

import { ChevronDown } from 'lucide-react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

type AdvancedPlanSection = {
  id: string
  title: string
  description: string
}

type AdvancedPlanDisclosureProps = {
  sections: AdvancedPlanSection[]
}

export function AdvancedPlanDisclosure({ sections }: AdvancedPlanDisclosureProps) {
  return (
    <Collapsible>
      <Card>
        <CardHeader className="pb-2">
          <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 text-left">
            <div>
              <CardTitle className="text-sm">Advanced</CardTitle>
              <div className="text-sm text-muted-foreground">
                Full verification, parameters, steps, DAG, and handoff stay here.
              </div>
            </div>
            <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform data-[state=open]:rotate-180')} />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="space-y-3 pt-0">
            {sections.map((section) => (
              <div key={section.id} className="rounded-md border bg-muted/20 p-3">
                <div className="text-sm font-medium text-foreground">{section.title}</div>
                <div className="mt-1 text-sm text-muted-foreground">{section.description}</div>
              </div>
            ))}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
