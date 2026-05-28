'use client'

import React, { useMemo } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  PlayCircle,
  PauseCircle,
  AlertCircle
} from 'lucide-react'

export interface TimelineEvent {
  id: string
  nodeId: string
  nodeName: string
  type: 'start' | 'progress' | 'complete' | 'error' | 'pause' | 'resume' | 'retry' | 'skip'
  timestamp: Date
  message?: string
  progress?: number
  duration?: number
  resources?: {
    cpu?: number
    memory?: number
    gpu?: number
  }
}

interface PipelineTimelineProps {
  events: TimelineEvent[]
  className?: string
}

const eventIcons = {
  start: { icon: PlayCircle, color: 'text-blue-500' },
  progress: { icon: Clock, color: 'text-gray-500' },
  complete: { icon: CheckCircle, color: 'text-green-500' },
  error: { icon: XCircle, color: 'text-red-500' },
  pause: { icon: PauseCircle, color: 'text-yellow-500' },
  resume: { icon: PlayCircle, color: 'text-blue-500' }
}

export function PipelineTimeline({ events, className = '' }: PipelineTimelineProps) {
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
  }, [events])

  const formatTime = (date: Date) => {
    const timeStr = date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
    const ms = date.getMilliseconds().toString().padStart(3, '0')
    return `${timeStr}.${ms}`
  }

  const formatDuration = (ms?: number) => {
    if (!ms) return null
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }

  const getEventTypeLabel = (type: string) => {
    switch (type) {
      case 'start': return 'Started'
      case 'progress': return 'Progress'
      case 'complete': return 'Completed'
      case 'error': return 'Failed'
      case 'pause': return 'Paused'
      case 'resume': return 'Resumed'
      default: return type
    }
  }

  const getEventVariant = (type: string): "default" | "secondary" | "destructive" | "outline" => {
    switch (type) {
      case 'start': return 'default'
      case 'complete': return 'default'
      case 'error': return 'destructive'
      case 'pause': return 'secondary'
      case 'resume': return 'default'
      default: return 'outline'
    }
  }

  if (events.length === 0) {
    return (
      <Card className={`p-6 ${className}`}>
        <div className="text-center text-muted-foreground">
          <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p>No timeline events yet</p>
          <p className="text-sm">Events will appear here when the pipeline starts executing.</p>
        </div>
      </Card>
    )
  }

  return (
    <Card className={className}>
      <div className="p-4 border-b">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Execution Timeline
          </h3>
          <Badge variant="secondary">
            {events.length} events
          </Badge>
        </div>
      </div>

      <ScrollArea className="h-64">
        <div className="p-4">
          {sortedEvents.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">
              No events recorded
            </div>
          ) : (
            <div className="space-y-4">
              {sortedEvents.map((event, index) => {
                const eventConfig = eventIcons[event.type] || eventIcons.progress
                const EventIcon = eventConfig.icon
                
                return (
                  <div key={`${event.id}-${index}`}>
                    <div className="flex items-start gap-3">
                      {/* Timeline indicator */}
                      <div className="relative flex-shrink-0">
                        <div className={`
                          w-8 h-8 rounded-full border-2 bg-background flex items-center justify-center
                          ${index === 0 ? 'border-primary' : 'border-muted-foreground/30'}
                        `}>
                          <EventIcon className={`h-4 w-4 ${eventConfig.color}`} />
                        </div>
                        {index < sortedEvents.length - 1 && (
                          <div className="absolute top-8 left-1/2 transform -translate-x-1/2 w-0.5 h-6 bg-muted-foreground/20" />
                        )}
                      </div>

                      {/* Event content */}
                      <div className="flex-1 space-y-1 pb-4">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm">{event.nodeName}</span>
                            <Badge variant={getEventVariant(event.type)} className="text-xs">
                              {getEventTypeLabel(event.type)}
                            </Badge>
                          </div>
                          <span className="text-xs text-muted-foreground font-mono">
                            {formatTime(event.timestamp)}
                          </span>
                        </div>

                        {/* Progress information */}
                        {event.progress !== undefined && (
                          <div className="text-xs text-muted-foreground">
                            Progress: {event.progress}%
                          </div>
                        )}

                        {/* Duration */}
                        {event.duration && (
                          <div className="text-xs text-muted-foreground">
                            Duration: {formatDuration(event.duration)}
                          </div>
                        )}

                        {/* Resource usage */}
                        {event.resources && (
                          <div className="flex gap-4 text-xs text-muted-foreground">
                            {event.resources.cpu !== undefined && (
                              <span>CPU: {Math.round(event.resources.cpu)}%</span>
                            )}
                            {event.resources.memory !== undefined && (
                              <span>Memory: {Math.round(event.resources.memory)}%</span>
                            )}
                            {event.resources.gpu !== undefined && (
                              <span>GPU: {Math.round(event.resources.gpu)}%</span>
                            )}
                          </div>
                        )}

                        {/* Message */}
                        {event.message && (
                          <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded font-mono">
                            {event.message}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </ScrollArea>
    </Card>
  )
}

export default PipelineTimeline