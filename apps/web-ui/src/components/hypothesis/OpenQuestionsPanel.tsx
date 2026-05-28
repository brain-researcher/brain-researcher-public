'use client'

import type { OpenQuestion } from '@/types/hypothesis'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type OpenQuestionsPanelProps = {
  questions: OpenQuestion[]
  selectedId: string | null
  onSelect: (questionId: string | null) => void
  loading?: boolean
  error?: string | null
}

export function OpenQuestionsPanel({
  questions,
  selectedId,
  onSelect,
  loading = false,
  error,
}: OpenQuestionsPanelProps) {
  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Open Questions</CardTitle>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onSelect(null)}
          >
            Show all
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {loading ? <div className="text-xs text-muted-foreground">Loading questions...</div> : null}
        {error ? <div className="text-xs text-red-600">{error}</div> : null}

        {!loading && !questions.length ? (
          <div className="text-xs text-muted-foreground">No open questions yet.</div>
        ) : null}

        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {questions.map((question) => {
            const active = selectedId === question.id
            return (
              <button
                key={question.id}
                type="button"
                className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                  active
                    ? 'border-primary bg-primary/5'
                    : 'border-border/70 hover:border-primary/40 hover:bg-muted/40'
                }`}
                onClick={() => onSelect(question.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-medium text-foreground">{question.title}</div>
                  <Badge variant={question.priority === 'high' ? 'default' : 'secondary'}>
                    {question.priority || 'medium'}
                  </Badge>
                </div>
                {question.description ? (
                  <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{question.description}</div>
                ) : null}
                {question.leverage_hint ? (
                  <div className="mt-2 text-[11px] text-blue-700">Leverage: {question.leverage_hint}</div>
                ) : null}
              </button>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
