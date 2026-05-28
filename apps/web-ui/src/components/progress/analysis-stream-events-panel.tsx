'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { openSSE } from '@/lib/api'
import type { AnalysisStreamEventV1 } from '@/types/contracts.generated'

type KnownEventType = Exclude<AnalysisStreamEventV1['event_type'], undefined>

type ParsedStreamEvent =
  | {
      kind: 'known'
      event: AnalysisStreamEventV1
    }
  | {
      kind: 'unknown'
      receivedAt: string
      reason: string
      raw: unknown
    }

const EVENT_TYPE_KEYS = {
  'job.started': true,
  'tool.call.started': true,
  'tool.call.finished': true,
  'artifact.written': true,
  'log.line': true,
  'observation.appended': true,
  stage: true,
  warning: true,
  metric: true,
  'analysis.completed': true,
  error: true,
  unknown: true,
} satisfies Record<KnownEventType, true>

const KNOWN_EVENT_TYPES = Object.keys(EVENT_TYPE_KEYS) as KnownEventType[]

const KNOWN_SSE_EVENT_NAMES: ReadonlyArray<string> = [
  // Backends may deliver typed events as:
  // - default EventSource messages (no explicit SSE "event:")
  // - a single typed channel (e.g. "analysis_stream_event")
  // - per-event event names (e.g. "tool.call.started")
  'analysis_stream_event',
  ...KNOWN_EVENT_TYPES,
] as const

function assertNever(value: never): never {
  throw new Error(`Unhandled event type: ${String(value)}`)
}

function isoNow(): string {
  return new Date().toISOString()
}

function formatClock(timestamp: string): string {
  const ms = Date.parse(timestamp)
  if (Number.isNaN(ms)) return timestamp
  return new Date(ms).toLocaleTimeString(undefined, { hour12: false })
}

function isKnownEventType(value: unknown): value is KnownEventType {
  return (
    typeof value === 'string' &&
    Object.prototype.hasOwnProperty.call(EVENT_TYPE_KEYS, value)
  )
}

function parseAnalysisStreamEvent(raw: unknown): ParsedStreamEvent {
  const receivedAt = isoNow()
  if (!raw || typeof raw !== 'object') {
    return {
      kind: 'unknown',
      receivedAt,
      reason: 'Event payload is not an object.',
      raw,
    }
  }

  const obj = raw as Record<string, unknown>
  const schemaVersion = obj.schema_version
  if (schemaVersion != null && schemaVersion !== 'analysis-stream-event-v1') {
    return {
      kind: 'unknown',
      receivedAt,
      reason: `Unexpected schema_version: ${String(schemaVersion)}`,
      raw,
    }
  }

  if (!isKnownEventType(obj.event_type)) {
    return {
      kind: 'unknown',
      receivedAt,
      reason: `Unrecognized event_type: ${String(obj.event_type ?? 'missing')}`,
      raw,
    }
  }

  return { kind: 'known', event: raw as AnalysisStreamEventV1 }
}

function renderKnownEventLine(event: AnalysisStreamEventV1): {
  label: React.ReactNode
  badge?: { variant: 'default' | 'secondary' | 'destructive' | 'outline'; text: string }
  detail?: unknown
  lineClassName?: string
} {
  const base = (
    <span className="flex flex-wrap items-center gap-2">
      <span className="text-slate-400">{formatClock(event.timestamp)}</span>
      <span className="text-slate-200">{event.event_type}</span>
    </span>
  )

  const eventType = event.event_type
  if (!eventType) {
    return {
      label: base,
      badge: { variant: 'secondary', text: 'Missing event_type' },
      detail: event,
      lineClassName: 'text-amber-300',
    }
  }

  switch (eventType) {
    case 'job.started': {
      const statusText = event.payload?.status ?? 'running'
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">status={statusText}</span>
            {event.payload?.message ? (
              <span className="text-slate-400">{event.payload.message}</span>
            ) : null}
          </span>
        ),
        badge: { variant: 'outline', text: 'Job' },
        detail: event,
      }
    }
    case 'tool.call.started': {
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">tool={event.payload.tool_id}</span>
            <span className="text-slate-500">call={event.payload.tool_call_id}</span>
          </span>
        ),
        badge: { variant: 'default', text: 'Tool start' },
        detail: event.payload.params ?? event,
      }
    }
    case 'tool.call.finished': {
      const variant =
        event.payload.status === 'succeeded'
          ? 'outline'
          : event.payload.status === 'failed'
            ? 'destructive'
            : 'secondary'
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">call={event.payload.tool_call_id}</span>
            <span className="text-slate-300">status={event.payload.status}</span>
            {typeof event.payload.artifacts?.length === 'number' ? (
              <span className="text-slate-500">artifacts={event.payload.artifacts.length}</span>
            ) : null}
            {event.payload.error_message ? (
              <span className="text-red-300">{event.payload.error_message}</span>
            ) : null}
          </span>
        ),
        badge: { variant, text: 'Tool end' },
        detail: event,
      }
    }
    case 'artifact.written': {
      const artifact = event.payload.artifact
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">kind={artifact.kind}</span>
            <span className="text-slate-500 break-all">{artifact.uri}</span>
          </span>
        ),
        badge: { variant: 'outline', text: 'Artifact' },
        detail: artifact,
      }
    }
    case 'log.line': {
      return {
        label: (
          <span className="flex items-start gap-3">
            <span className="text-slate-400">{formatClock(event.timestamp)}</span>
            <span className={event.payload.stream === 'stderr' ? 'text-red-200' : 'text-green-200'}>
              {event.payload.line}
            </span>
          </span>
        ),
        badge: {
          variant: event.payload.stream === 'stderr' ? 'destructive' : 'secondary',
          text: event.payload.stream,
        },
        detail: event,
        lineClassName: 'whitespace-pre-wrap break-words',
      }
    }
    case 'observation.appended': {
      const observation = event.payload.observation
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-500 break-all">{observation.uri}</span>
          </span>
        ),
        badge: { variant: 'secondary', text: 'Observation' },
        detail: observation,
      }
    }
    case 'stage': {
      const variant =
        event.payload.status === 'failed'
          ? 'destructive'
          : event.payload.status === 'warned' || event.payload.status === 'blocked'
            ? 'secondary'
            : 'outline'
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">stage={event.payload.stage}</span>
            <span className="text-slate-300">status={event.payload.status}</span>
            {event.payload.tool_id ? (
              <span className="text-slate-500">tool={event.payload.tool_id}</span>
            ) : null}
            {event.payload.message ? (
              <span className="text-slate-400">{event.payload.message}</span>
            ) : null}
          </span>
        ),
        badge: { variant, text: 'Stage' },
        detail: event.payload.details ?? event,
      }
    }
    case 'warning': {
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-amber-200">{event.payload.message}</span>
          </span>
        ),
        badge: { variant: 'secondary', text: 'Warning' },
        detail: event.payload.details ?? event,
      }
    }
    case 'metric': {
      const unit = event.payload.unit ? ` ${event.payload.unit}` : ''
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">
              {event.payload.name}={event.payload.value}
              {unit}
            </span>
          </span>
        ),
        badge: { variant: 'outline', text: 'Metric' },
        detail: event.payload.details ?? event,
      }
    }
    case 'analysis.completed': {
      const variant =
        event.payload.status === 'succeeded'
          ? 'outline'
          : event.payload.status === 'failed'
            ? 'destructive'
            : 'secondary'
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">status={event.payload.status}</span>
            {event.payload.message ? (
              <span className="text-slate-400">{event.payload.message}</span>
            ) : null}
          </span>
        ),
        badge: { variant, text: 'Complete' },
        detail: event,
      }
    }
    case 'error': {
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-red-300">{event.payload.message}</span>
          </span>
        ),
        badge: { variant: 'destructive', text: 'Error' },
        detail: event.payload.details ?? event,
      }
    }
    case 'unknown': {
      return {
        label: (
          <span className="flex flex-wrap items-center gap-2">
            {base}
            <span className="text-slate-300">raw={event.payload.raw_event_type}</span>
          </span>
        ),
        badge: { variant: 'secondary', text: 'Unknown' },
        detail: event.payload.raw_payload ?? event,
      }
    }
    default:
      return assertNever(eventType)
  }
}

type AnalysisStreamEventsPanelProps = {
  analysisId: string
  maxEvents?: number
}

export function AnalysisStreamEventsPanel({
  analysisId,
  maxEvents = 250,
}: AnalysisStreamEventsPanelProps) {
  const [events, setEvents] = useState<ParsedStreamEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const sourceRef = useRef<EventSource | null>(null)

  const streamUrl = useMemo(() => {
    return `/api/analyses/${encodeURIComponent(analysisId)}/analysis-stream`
  }, [analysisId])

  const pushEvent = useCallback(
    (parsed: ParsedStreamEvent) => {
      setEvents((prev) => {
        const next = prev.length >= maxEvents ? prev.slice(prev.length - maxEvents + 1) : prev
        return [...next, parsed]
      })
    },
    [maxEvents],
  )

  useEffect(() => {
    setEvents([])
    setIsConnected(false)

    const source = openSSE(streamUrl)
    sourceRef.current = source

    const handleMessage = (evt: MessageEvent) => {
      const rawData = typeof evt.data === 'string' ? evt.data.trim() : ''
      if (!rawData) {
        return
      }
      try {
        const json = JSON.parse(rawData)
        const parsed = parseAnalysisStreamEvent(json)
        pushEvent(parsed)

        if (parsed.kind === 'known' && parsed.event.event_type === 'analysis.completed') {
          source.close()
          sourceRef.current = null
          setIsConnected(false)
        }
      } catch (err) {
        pushEvent({
          kind: 'unknown',
          receivedAt: isoNow(),
          reason: 'Failed to parse event JSON.',
          raw: { error: String(err), data: rawData },
        })
      }
    }

    const handleNamedEvent = (evt: Event) => {
      handleMessage(evt as MessageEvent)
    }

    source.onopen = () => setIsConnected(true)
    source.onmessage = handleMessage

    for (const name of KNOWN_SSE_EVENT_NAMES) {
      source.addEventListener(name, handleNamedEvent as EventListener)
    }

    source.onerror = () => {
      setIsConnected(false)
    }

    return () => {
      source.close()
      sourceRef.current = null
      setIsConnected(false)
    }
  }, [pushEvent, streamUrl])

  const clear = () => setEvents([])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Stream:</span>
          <Badge variant={isConnected ? 'outline' : 'secondary'}>
            {isConnected ? 'Connected' : 'Disconnected'}
          </Badge>
          <span>•</span>
          <span>Events: {events.length}</span>
        </div>
        <Button size="sm" variant="outline" onClick={clear} disabled={events.length === 0}>
          Clear
        </Button>
      </div>

      <ScrollArea className="h-80 rounded-md border bg-slate-950 p-3 font-mono text-xs">
        {events.length === 0 ? (
          <div className="text-slate-400">No events yet.</div>
        ) : (
          <div className="space-y-2">
            {events.map((evt, idx) => {
              if (evt.kind === 'known') {
                const rendered = renderKnownEventLine(evt.event)
                return (
                  <div
                    key={`${evt.event.seq}:${evt.event.event_type ?? idx}`}
                    className={`flex items-start justify-between gap-3 ${rendered.lineClassName ?? ''}`}
                  >
                    <div className="min-w-0 flex-1 text-slate-200">{rendered.label}</div>
                    <div className="flex shrink-0 items-center gap-2">
                      {rendered.badge ? (
                        <Badge variant={rendered.badge.variant}>{rendered.badge.text}</Badge>
                      ) : null}
                      {rendered.detail ? (
                        <details className="shrink-0">
                          <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                            json
                          </summary>
                          <pre className="mt-2 max-w-[36rem] overflow-x-auto rounded-md border border-slate-800 bg-slate-900 p-3 text-slate-200">
                            {JSON.stringify(rendered.detail, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  </div>
                )
              }

              return (
                <div
                  key={`unknown:${evt.receivedAt}:${idx}`}
                  className="space-y-2 rounded-md border border-slate-800 bg-slate-900 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2 text-slate-200">
                      <span className="text-slate-400">{formatClock(evt.receivedAt)}</span>
                      <span className="text-amber-300">Unknown event</span>
                      <span className="text-slate-400">{evt.reason}</span>
                    </div>
                    <Badge variant="secondary">Unknown</Badge>
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap break-words text-slate-200">
                    {JSON.stringify(evt.raw, null, 2)}
                  </pre>
                </div>
              )
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
