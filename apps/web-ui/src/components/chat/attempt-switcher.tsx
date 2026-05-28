'use client'

import type { ComponentProps } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Circle, Info, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { AnalysisSummary, AnalysesListResponse } from '@/types/analysis'

type AttemptSwitcherProps = {
  threadId: string
  currentAnalysisId: string
  onSelect: (analysisId: string) => void
}

type AttemptOption = {
  analysisId: string
  label: string
  status: AnalysisSummary['status']
  title?: string
}

const statusBadgeVariant = (
  status: AnalysisSummary['status'],
): ComponentProps<typeof Badge>['variant'] => {
  switch (status) {
    case 'completed':
      return 'default'
    case 'failed':
      return 'destructive'
    case 'running':
      return 'secondary'
    default:
      return 'outline'
  }
}

const statusIcon = (status: AnalysisSummary['status']) => {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
    case 'failed':
      return <XCircle className="h-3.5 w-3.5 text-red-600" />
    default:
      return <Circle className="h-3.5 w-3.5 text-muted-foreground" />
  }
}

export function AttemptSwitcher({ threadId, currentAnalysisId, onSelect }: AttemptSwitcherProps) {
  const [items, setItems] = useState<AnalysisSummary[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const fetchAttempts = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const res = await fetch('/api/analyses?limit=100', { cache: 'no-store' })
        if (!res.ok) {
          if (res.status === 401) {
            if (!cancelled) {
              setItems([])
              setError(null)
            }
            return
          }
          const text = await res.text().catch(() => '')
          throw new Error(text || `Failed to load analyses (${res.status})`)
        }
        const data = (await res.json()) as AnalysesListResponse
        const nextItems = Array.isArray(data?.items) ? data.items : []
        if (!cancelled) {
          setItems(nextItems)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
          setItems([])
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void fetchAttempts()
    return () => {
      cancelled = true
    }
  }, [threadId, currentAnalysisId])

  const options = useMemo<AttemptOption[]>(() => {
    const attempts = items
      .filter((it) => (it.thread_id || null) === threadId)
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))

    if (attempts.length < 2) {
      return []
    }

    const total = attempts.length
    return attempts.map((attempt, index) => {
      const attemptNumber = total - index
      return {
        analysisId: attempt.analysis_id,
        label: index === 0 ? 'Latest' : `Attempt ${attemptNumber}`,
        status: attempt.status,
        title: attempt.title,
      }
    })
  }, [items, threadId])

  const selected = options.find((opt) => opt.analysisId === currentAnalysisId) || options[0]

  if (!selected || options.length < 2) {
    return null
  }

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          Attempts
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                  aria-label="About attempts"
                >
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="max-w-xs">
                Each attempt is an immutable execution snapshot of your plan. Editing the plan creates a new attempt.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </span>
        {isLoading ? <span className="text-muted-foreground">loading…</span> : null}
        {error ? <span className="text-red-600">failed to load</span> : null}
      </div>

      <div className="flex items-center gap-2">
        <Badge variant={statusBadgeVariant(selected.status)} className="h-5 px-2 text-xs">
          <span className="mr-1 inline-flex">{statusIcon(selected.status)}</span>
          {selected.status}
        </Badge>
        <Select value={selected.analysisId} onValueChange={onSelect}>
          <SelectTrigger
            className="h-8 min-w-[160px] text-xs"
            data-testid="attempt-switcher-select"
            aria-label="Attempts"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((opt) => (
              <SelectItem key={opt.analysisId} value={opt.analysisId} className="text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span>{opt.label}</span>
                  <span className="text-muted-foreground">{opt.title || opt.status}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
