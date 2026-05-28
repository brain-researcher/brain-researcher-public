'use client'

import { CheckCircle, AlertCircle, Clock, XCircle, GitBranch } from 'lucide-react'
import type { BranchEvent, ExecutionStep } from '@/types/chat'

interface BranchTimelineProps {
  branchEvents?: BranchEvent[]
  plannerState?: Record<string, any>
  steps?: ExecutionStep[]
  selectedOnly?: boolean
}

const EVENT_STYLES: Record<string, { label: string; icon: typeof CheckCircle; className: string }> = {
  branch_started: { label: 'Started', icon: Clock, className: 'text-blue-600' },
  branch_failed: { label: 'Failed', icon: XCircle, className: 'text-red-600' },
  branch_succeeded: { label: 'Succeeded', icon: CheckCircle, className: 'text-emerald-600' },
  branch_skipped: { label: 'Skipped', icon: AlertCircle, className: 'text-amber-600' }
}

const parseTimestamp = (value?: string | number) => {
  if (typeof value === 'number') {
    return value < 1e12 ? value * 1000 : value
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value)
    return Number.isNaN(parsed) ? null : parsed
  }
  return null
}

export function BranchTimeline({
  branchEvents = [],
  plannerState,
  steps = [],
  selectedOnly = false
}: BranchTimelineProps) {
  const selectedBranchId = plannerState?.selectedBranchId ?? plannerState?.selected_branch_id
  const selectedTool = typeof selectedBranchId === 'string' && selectedBranchId.startsWith('br:')
    ? selectedBranchId.slice(3)
    : undefined

  const eventsWithTimestamps = branchEvents.map((event, index) => ({
    ...event,
    index,
    tsValue: parseTimestamp(event.timestamp)
  }))

  const canSort = eventsWithTimestamps.every((event) => event.tsValue !== null)
  const orderedEvents = [...eventsWithTimestamps].sort((a, b) => {
    if (!canSort) return a.index - b.index
    return (a.tsValue as number) - (b.tsValue as number)
  })

  const candidateSteps = steps
    .filter((step) => step.branchRank !== undefined || step.branchGroupId || step.branchStepId)
    .reduce<Record<string, ExecutionStep>>((acc, step) => {
      const rank = typeof step.branchRank === 'number' ? step.branchRank : undefined
      if (rank === undefined) return acc
      const groupId = step.branchGroupId ?? 'default'
      const key = `${groupId}:${rank}`
      if (!acc[key]) {
        acc[key] = step
      }
      return acc
    }, {})

  const candidates = Object.values(candidateSteps).sort((a, b) => {
    const groupA = a.branchGroupId ?? 'default'
    const groupB = b.branchGroupId ?? 'default'
    if (groupA !== groupB) {
      return groupA.localeCompare(groupB)
    }
    const rankA = typeof a.branchRank === 'number' ? a.branchRank : 0
    const rankB = typeof b.branchRank === 'number' ? b.branchRank : 0
    return rankA - rankB
  })

  const hasAnyData = orderedEvents.length > 0 || candidates.length > 0
  if (!hasAnyData) {
    return (
      <div className="text-xs text-muted-foreground">
        No branch timeline events recorded.
      </div>
    )
  }

  const filteredEvents = selectedOnly && (selectedTool || selectedBranchId)
    ? orderedEvents.filter((event) => {
        if (selectedTool) {
          return event.branchTool === selectedTool
        }
        if (selectedBranchId) {
          return event.branchId === selectedBranchId
        }
        return true
      })
    : orderedEvents

  const filteredCandidates = selectedOnly && selectedTool
    ? candidates.filter((step) => step.tool === selectedTool)
    : candidates

  const noEventsMessage = selectedOnly && (selectedTool || selectedBranchId)
    ? 'No events for the selected branch.'
    : 'No branch events recorded.'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <GitBranch className="h-3.5 w-3.5" />
          Branch candidates
        </span>
        {selectedBranchId && (
          <span className="text-xs font-semibold text-emerald-700">
            Selected: {selectedTool ?? selectedBranchId}
          </span>
        )}
      </div>

      {filteredCandidates.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {filteredCandidates.map((step) => {
            const rank = step.branchRank ?? 0
            const isSelected = selectedTool ? step.tool === selectedTool : false
            return (
              <div
                key={`${step.id}-${rank}`}
                className={`rounded-full border px-3 py-1 text-[11px] font-medium ${
                  isSelected ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-border text-muted-foreground'
                }`}
              >
                #{rank} {step.tool || step.id}
              </div>
            )
          })}
        </div>
      )}

      {filteredEvents.length === 0 && (
        <div className="text-xs text-muted-foreground">
          {noEventsMessage}
        </div>
      )}

      <div className="space-y-2">
        {filteredEvents.map((event) => {
          const eventType = (event.eventType ?? 'branch_event').toLowerCase()
          const style = EVENT_STYLES[eventType] ?? {
            label: 'Event',
            icon: AlertCircle,
            className: 'text-muted-foreground'
          }
          const Icon = style.icon
          const isSelected = selectedTool
            ? event.branchTool === selectedTool
            : selectedBranchId
              ? event.branchId === selectedBranchId
              : false
          return (
            <div
              key={`${event.eventType ?? 'evt'}-${event.branchStepId ?? event.index}`}
              className={`rounded-md border px-3 py-2 text-xs ${
                isSelected ? 'border-emerald-200 bg-emerald-50/40' : 'border-border'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Icon className={`h-4 w-4 ${style.className}`} />
                    <span className="font-semibold">{style.label}</span>
                    {typeof event.branchRank === 'number' && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[10px]">
                        rank {event.branchRank}
                      </span>
                    )}
                  </div>
                  <div className="text-muted-foreground">
                    {event.branchTool ? `Tool: ${event.branchTool}` : 'Tool: unknown'}
                    {event.branchStepId && ` • Step: ${event.branchStepId}`}
                  </div>
                </div>
                {event.tsValue !== null && (
                  <span className="text-[10px] text-muted-foreground">
                    {new Date(event.tsValue).toLocaleTimeString()}
                  </span>
                )}
              </div>

              {event.error && (
                <div className="mt-2 flex items-start gap-2 rounded bg-red-50 p-2 text-[11px] text-red-700">
                  <AlertCircle className="h-3.5 w-3.5" />
                  <span className="whitespace-pre-wrap">{event.error}</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
