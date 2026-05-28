'use client'

import { useMemo, useState } from 'react'

import type { HypothesisCandidate } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type SortKey = 'total_score' | 'novelty' | 'coherence' | 'leverage' | 'feasibility'

type HypothesisListPanelProps = {
  candidates: HypothesisCandidate[]
  selectedId: string | null
  selectedForBatch: Set<string>
  onSelect: (candidateId: string) => void
  onToggleBatch: (candidateId: string, nextChecked: boolean) => void
}

const SCORE_LABELS: Record<SortKey, string> = {
  total_score: 'Total score',
  novelty: 'Novelty',
  coherence: 'Coherence',
  leverage: 'Leverage',
  feasibility: 'Feasibility',
}

const scoreFor = (candidate: HypothesisCandidate, key: SortKey): number => {
  const score = candidate.score
  switch (key) {
    case 'novelty':
      return score.novelty ?? -1
    case 'coherence':
      return score.coherence ?? -1
    case 'leverage':
      return score.leverage ?? -1
    case 'feasibility':
      return score.feasibility ?? -1
    case 'total_score':
    default:
      return score.total_score ?? -1
  }
}

const formatScore = (value: number | null): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  return value.toFixed(2)
}

export function HypothesisListPanel({
  candidates,
  selectedId,
  selectedForBatch,
  onSelect,
  onToggleBatch,
}: HypothesisListPanelProps) {
  const [sortKey, setSortKey] = useState<SortKey>('total_score')

  const sortedCandidates = useMemo(() => {
    return [...candidates].sort((left, right) => scoreFor(right, sortKey) - scoreFor(left, sortKey))
  }, [candidates, sortKey])

  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Hypotheses</CardTitle>
          <Select value={sortKey} onValueChange={(value) => setSortKey(value as SortKey)}>
            <SelectTrigger className="h-8 w-[160px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SCORE_LABELS) as SortKey[]).map((key) => (
                <SelectItem key={key} value={key} className="text-xs">
                  {SCORE_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {!sortedCandidates.length ? (
          <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
            No hypotheses available for this selection.
          </div>
        ) : null}

        <div className="space-y-2 max-h-[36rem] overflow-y-auto pr-1">
          {sortedCandidates.map((candidate) => {
            const active = selectedId === candidate.id
            const checked = selectedForBatch.has(candidate.id)
            return (
              <div
                key={candidate.id}
                className={`rounded-md border px-3 py-2 transition-colors ${
                  active
                    ? 'border-primary bg-primary/5'
                    : 'border-border/70 hover:border-primary/40 hover:bg-muted/40'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <button type="button" className="text-left flex-1" onClick={() => onSelect(candidate.id)}>
                    <div className="text-sm font-medium text-foreground line-clamp-1">{candidate.title}</div>
                    <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{candidate.statement}</div>
                  </button>
                  <div className="pt-0.5">
                    <Checkbox
                      checked={checked}
                      onCheckedChange={(next) => onToggleBatch(candidate.id, Boolean(next))}
                      aria-label={`Select ${candidate.title} for batch run`}
                    />
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                  <Badge variant={candidate.status === 'provisional' ? 'secondary' : 'outline'}>
                    {candidate.status}
                  </Badge>
                  <Badge variant="outline">score {formatScore(candidate.score.total_score)}</Badge>
                  {candidate.tags.slice(0, 3).map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
