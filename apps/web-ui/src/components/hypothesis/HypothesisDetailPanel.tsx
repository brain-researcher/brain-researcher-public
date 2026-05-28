'use client'

import type { HypothesisCandidate } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AgentTraceTabs } from '@/components/hypothesis/AgentTraceTabs'
import { MDECard } from '@/components/hypothesis/MDECard'

type HypothesisDetailPanelProps = {
  candidate: HypothesisCandidate | null
  onRunSingle?: (candidateId: string) => void
}

const formatScore = (value: number | null): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : 'n/a'

export function HypothesisDetailPanel({ candidate, onRunSingle }: HypothesisDetailPanelProps) {
  if (!candidate) {
    return (
      <Card className="border-border/70">
        <CardContent className="p-6">
          <div className="text-sm text-muted-foreground">Pick a hypothesis to inspect evidence and MDE details.</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card className="border-border/70">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">{candidate.title}</CardTitle>
              <div className="mt-1 text-sm text-muted-foreground">{candidate.statement}</div>
            </div>
            <Badge variant={candidate.status === 'provisional' ? 'secondary' : 'outline'}>
              {candidate.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
            <div className="rounded-md border p-2">Total: {formatScore(candidate.score.total_score)}</div>
            <div className="rounded-md border p-2">Novelty: {formatScore(candidate.score.novelty)}</div>
            <div className="rounded-md border p-2">Coherence: {formatScore(candidate.score.coherence)}</div>
            <div className="rounded-md border p-2">Leverage: {formatScore(candidate.score.leverage)}</div>
            <div className="rounded-md border p-2">Feasibility: {formatScore(candidate.score.feasibility)}</div>
            <div className="rounded-md border p-2">Risk: {formatScore(candidate.score.risk)}</div>
          </div>

          <div className="flex flex-wrap gap-2">
            {candidate.tags.length ? (
              candidate.tags.map((tag) => (
                <Badge key={tag} variant="secondary">
                  {tag}
                </Badge>
              ))
            ) : (
              <div className="text-xs text-muted-foreground">No tags.</div>
            )}
          </div>

          {onRunSingle ? (
            <div className="flex justify-end">
              <Button size="sm" onClick={() => onRunSingle(candidate.id)}>
                Run Batch for this hypothesis
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="border-border/70">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Agent Network Flow</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <AgentTraceTabs traces={candidate.traces} />
        </CardContent>
      </Card>

      <MDECard mde={candidate.mde} />

      <Card className="border-border/70">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Evidence</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {!candidate.evidence.length ? (
            <div className="text-xs text-muted-foreground">No evidence items yet.</div>
          ) : (
            <div className="space-y-2">
              {candidate.evidence.map((item) => (
                <div key={item.id} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium">{item.label}</div>
                    <Badge variant="outline">{item.kind}</Badge>
                  </div>
                  {item.summary ? <div className="mt-1 text-xs text-muted-foreground">{item.summary}</div> : null}
                  {item.url ? (
                    <a
                      className="mt-1 inline-block text-xs text-blue-600 hover:underline"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open source
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
