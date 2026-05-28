'use client'

import type { AgentName, AgentTrace } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const ORDERED_AGENTS: AgentName[] = ['explorer', 'critic', 'verifier', 'ranker']

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1)

type AgentTraceTabsProps = {
  traces: AgentTrace[]
}

export function AgentTraceTabs({ traces }: AgentTraceTabsProps) {
  const map = new Map(traces.map((trace) => [trace.agent, trace]))

  if (!traces.length) {
    return <div className="text-xs text-muted-foreground">No agent traces available yet.</div>
  }

  return (
    <Tabs defaultValue={ORDERED_AGENTS[0]} className="space-y-3">
      <TabsList className="grid w-full grid-cols-4">
        {ORDERED_AGENTS.map((agent) => {
          const trace = map.get(agent)
          return (
            <TabsTrigger key={agent} value={agent} className="text-xs">
              {capitalize(agent)}
              {trace ? (
                <Badge variant={trace.status === 'ok' ? 'secondary' : 'outline'} className="ml-2 text-[10px]">
                  {trace.status}
                </Badge>
              ) : null}
            </TabsTrigger>
          )
        })}
      </TabsList>

      {ORDERED_AGENTS.map((agent) => {
        const trace = map.get(agent)
        return (
          <TabsContent key={agent} value={agent} className="mt-0">
            {trace ? (
              <div className="space-y-2 rounded-md border border-border/70 p-3">
                <div className="text-sm font-medium">{trace.summary}</div>
                {trace.details.length ? (
                  <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-1">
                    {trace.details.map((detail, index) => (
                      <li key={`${agent}-${index}`}>{detail}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-xs text-muted-foreground">No extra details.</div>
                )}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">No {agent} output for this hypothesis.</div>
            )}
          </TabsContent>
        )
      })}
    </Tabs>
  )
}
