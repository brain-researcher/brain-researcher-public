'use client'

import React, { useMemo, useState, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  PlayCircle,
  PauseCircle,
  AlertCircle,
  Search,
  Filter,
  Download,
  Trash2,
  Eye,
  EyeOff,
  ChevronDown,
  ChevronRight,
  Activity,
  Cpu,
  HardDrive,
  Zap
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
    networkIO?: number
  }
  metadata?: {
    level?: 'info' | 'warning' | 'error'
    category?: string
    details?: Record<string, any>
  }
}

interface PipelineTimelineProps {
  events: TimelineEvent[]
  className?: string
  searchable?: boolean
  filterable?: boolean
  exportable?: boolean
  maxEvents?: number
  autoScroll?: boolean
  groupByNode?: boolean
  showResourceMetrics?: boolean
}

const eventIcons = {
  start: { icon: PlayCircle, color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900' },
  progress: { icon: Clock, color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800' },
  complete: { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-100 dark:bg-green-900' },
  error: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900' },
  pause: { icon: PauseCircle, color: 'text-yellow-500', bg: 'bg-yellow-100 dark:bg-yellow-900' },
  resume: { icon: PlayCircle, color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900' },
  retry: { icon: AlertCircle, color: 'text-orange-500', bg: 'bg-orange-100 dark:bg-orange-900' },
  skip: { icon: AlertCircle, color: 'text-gray-400', bg: 'bg-gray-100 dark:bg-gray-800' }
}

const eventTypeLabels = {
  start: 'Started',
  progress: 'Progress Update',
  complete: 'Completed',
  error: 'Failed',
  pause: 'Paused',
  resume: 'Resumed',
  retry: 'Retrying',
  skip: 'Skipped'
}

const eventVariants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  start: 'default',
  progress: 'secondary',
  complete: 'default',
  error: 'destructive',
  pause: 'secondary',
  resume: 'default',
  retry: 'outline',
  skip: 'outline'
}

export function PipelineTimeline({
  events,
  className = '',
  searchable = true,
  filterable = true,
  exportable = false,
  maxEvents = 1000,
  autoScroll = true,
  groupByNode = false,
  showResourceMetrics = true
}: PipelineTimelineProps) {
  const ALL_TYPES_OPTION = '__all_types__'
  const ALL_NODES_OPTION = '__all_nodes__'
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [selectedNodes, setSelectedNodes] = useState<string[]>([])
  const [timeRange, setTimeRange] = useState<'all' | '1h' | '24h' | '7d'>('all')
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
  const [activeTab, setActiveTab] = useState<'timeline' | 'grouped' | 'stats'>('timeline')

  const uniqueTypes = useMemo(() => Array.from(new Set(events.map(e => e.type))), [events])
  const uniqueNodes = useMemo(() => Array.from(new Set(events.map(e => e.nodeName))), [events])

  const filteredEvents = useMemo(() => {
    let filtered = [...events]

    // Text search
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(event =>
        event.nodeName.toLowerCase().includes(query) ||
        event.message?.toLowerCase().includes(query) ||
        event.type.toLowerCase().includes(query)
      )
    }

    // Type filter
    if (selectedTypes.length > 0) {
      filtered = filtered.filter(event => selectedTypes.includes(event.type))
    }

    // Node filter
    if (selectedNodes.length > 0) {
      filtered = filtered.filter(event => selectedNodes.includes(event.nodeName))
    }

    // Time range filter
    if (timeRange !== 'all') {
      const now = new Date()
      const cutoff = new Date(now)
      switch (timeRange) {
        case '1h':
          cutoff.setHours(now.getHours() - 1)
          break
        case '24h':
          cutoff.setDate(now.getDate() - 1)
          break
        case '7d':
          cutoff.setDate(now.getDate() - 7)
          break
      }
      filtered = filtered.filter(event => event.timestamp >= cutoff)
    }

    // Sort by timestamp (most recent first)
    filtered.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())

    // Limit events
    return filtered.slice(0, maxEvents)
  }, [events, searchQuery, selectedTypes, selectedNodes, timeRange, maxEvents])

  const groupedEvents = useMemo(() => {
    const groups: Record<string, TimelineEvent[]> = {}
    filteredEvents.forEach(event => {
      if (!groups[event.nodeId]) {
        groups[event.nodeId] = []
      }
      groups[event.nodeId].push(event)
    })
    return groups
  }, [filteredEvents])

  const eventStats = useMemo(() => {
    const stats = {
      total: events.length,
      byType: {} as Record<string, number>,
      byNode: {} as Record<string, number>,
      avgDuration: 0,
      errorRate: 0
    }

    events.forEach(event => {
      stats.byType[event.type] = (stats.byType[event.type] || 0) + 1
      stats.byNode[event.nodeName] = (stats.byNode[event.nodeName] || 0) + 1
    })

    const durations = events.filter(e => e.duration).map(e => e.duration!)
    stats.avgDuration = durations.reduce((sum, d) => sum + d, 0) / durations.length

    stats.errorRate = ((stats.byType.error || 0) / stats.total) * 100

    return stats
  }, [events])

  const formatTime = useCallback((date: Date) => {
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3
    } as Intl.DateTimeFormatOptions)
  }, [])

  const formatDuration = useCallback((ms?: number) => {
    if (!ms) return null
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m ${seconds % 60}s`
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`
    }
    return `${seconds}s`
  }, [])

  const exportEvents = useCallback(() => {
    const data = {
      exportedAt: new Date().toISOString(),
      totalEvents: filteredEvents.length,
      events: filteredEvents
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `pipeline-timeline-${Date.now()}.json`
    link.href = url
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }, [filteredEvents])

  const clearFilters = useCallback(() => {
    setSearchQuery('')
    setSelectedTypes([])
    setSelectedNodes([])
    setTimeRange('all')
  }, [])

  const toggleNodeExpansion = useCallback((nodeId: string) => {
    setExpandedNodes(prev => {
      const newSet = new Set(prev)
      if (newSet.has(nodeId)) {
        newSet.delete(nodeId)
      } else {
        newSet.add(nodeId)
      }
      return newSet
    })
  }, [])

  const renderEventItem = useCallback((event: TimelineEvent, index: number, isGrouped = false) => {
    const eventConfig = eventIcons[event.type]
    const EventIcon = eventConfig.icon

    return (
      <div key={`${event.id}-${index}`} className={isGrouped ? 'ml-4' : ''}>
        <div className="flex items-start gap-3 py-3">
          {/* Timeline indicator */}
          <div className="relative flex-shrink-0">
            <div className={`
              w-8 h-8 rounded-full border-2 bg-background flex items-center justify-center
              ${eventConfig.bg} ${index === 0 && !isGrouped ? 'border-primary' : 'border-muted-foreground/30'}
            `}>
              <EventIcon className={`h-4 w-4 ${eventConfig.color}`} />
            </div>
            {!isGrouped && index < filteredEvents.length - 1 && (
              <div className="absolute top-8 left-1/2 transform -translate-x-1/2 w-0.5 h-6 bg-muted-foreground/20" />
            )}
          </div>

          {/* Event content */}
          <div className="flex-1 space-y-2 pb-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {!isGrouped && (
                  <span className="font-medium text-sm">{event.nodeName}</span>
                )}
                <Badge variant={eventVariants[event.type]} className="text-xs">
                  {eventTypeLabels[event.type]}
                </Badge>
                {event.metadata?.level && event.metadata.level !== 'info' && (
                  <Badge variant={event.metadata.level === 'error' ? 'destructive' : 'secondary'} className="text-xs">
                    {event.metadata.level}
                  </Badge>
                )}
              </div>
              <span className="text-xs text-muted-foreground font-mono">
                {formatTime(event.timestamp)}
              </span>
            </div>

            {/* Progress information */}
            {event.progress !== undefined && (
              <div className="text-xs text-muted-foreground flex items-center gap-2">
                <span>Progress: {event.progress}%</span>
                <div className="w-20 bg-muted rounded-full h-1">
                  <div
                    className="bg-blue-500 h-1 rounded-full transition-all"
                    style={{ width: `${event.progress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Duration */}
            {event.duration && (
              <div className="text-xs text-muted-foreground">
                Duration: {formatDuration(event.duration)}
              </div>
            )}

            {/* Resource usage */}
            {showResourceMetrics && event.resources && (
              <div className="grid grid-cols-2 gap-2 text-xs">
                {event.resources.cpu !== undefined && (
                  <div className="flex items-center gap-1 p-1 rounded bg-muted/30">
                    <Cpu className="h-3 w-3 text-blue-500" />
                    <span>CPU: {Math.round(event.resources.cpu)}%</span>
                  </div>
                )}
                {event.resources.memory !== undefined && (
                  <div className="flex items-center gap-1 p-1 rounded bg-muted/30">
                    <HardDrive className="h-3 w-3 text-green-500" />
                    <span>RAM: {Math.round(event.resources.memory)}%</span>
                  </div>
                )}
                {event.resources.gpu !== undefined && (
                  <div className="flex items-center gap-1 p-1 rounded bg-muted/30">
                    <Zap className="h-3 w-3 text-yellow-500" />
                    <span>GPU: {Math.round(event.resources.gpu)}%</span>
                  </div>
                )}
                {event.resources.networkIO !== undefined && (
                  <div className="flex items-center gap-1 p-1 rounded bg-muted/30">
                    <Activity className="h-3 w-3 text-purple-500" />
                    <span>I/O: {Math.round(event.resources.networkIO)}%</span>
                  </div>
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
  }, [filteredEvents, showResourceMetrics, formatTime, formatDuration])

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
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Pipeline Timeline
          </h3>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">
              {filteredEvents.length} / {events.length} events
            </Badge>
            {exportable && (
              <Button onClick={exportEvents} variant="outline" size="sm">
                <Download className="h-4 w-4 mr-1" />
                Export
              </Button>
            )}
          </div>
        </div>

        {/* Filters */}
        {(searchable || filterable) && (
          <div className="space-y-3">
            {searchable && (
              <div className="relative">
                <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search events..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8"
                />
              </div>
            )}

            {filterable && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <Select value={timeRange} onValueChange={(value: any) => setTimeRange(value)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Time range" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All time</SelectItem>
                    <SelectItem value="1h">Last hour</SelectItem>
                    <SelectItem value="24h">Last 24 hours</SelectItem>
                    <SelectItem value="7d">Last 7 days</SelectItem>
                  </SelectContent>
                </Select>

                <Select
                  value={selectedTypes.length > 0 ? selectedTypes.join(',') : ALL_TYPES_OPTION}
                  onValueChange={(value) => setSelectedTypes(value === ALL_TYPES_OPTION ? [] : value.split(','))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Event types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_TYPES_OPTION}>All types</SelectItem>
                    {uniqueTypes.map(type => (
                      <SelectItem key={type} value={type}>
                        {eventTypeLabels[type as keyof typeof eventTypeLabels]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select
                  value={selectedNodes.length > 0 ? selectedNodes.join(',') : ALL_NODES_OPTION}
                  onValueChange={(value) => setSelectedNodes(value === ALL_NODES_OPTION ? [] : value.split(','))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Nodes" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_NODES_OPTION}>All nodes</SelectItem>
                    {uniqueNodes.map(node => (
                      <SelectItem key={node} value={node}>
                        {node}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {(searchQuery || selectedTypes.length > 0 || selectedNodes.length > 0 || timeRange !== 'all') && (
              <Button onClick={clearFilters} variant="outline" size="sm" className="w-full">
                <Trash2 className="h-4 w-4 mr-2" />
                Clear Filters
              </Button>
            )}
          </div>
        )}
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)} className="h-full flex flex-col">
        <TabsList className="mx-4 mt-2 grid w-full grid-cols-3">
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="grouped">By Node</TabsTrigger>
          <TabsTrigger value="stats">Statistics</TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="flex-1 overflow-hidden">
          <ScrollArea className="h-96">
            <div className="p-4">
              {filteredEvents.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  No events match your filters
                </div>
              ) : (
                <div className="space-y-0">
                  {filteredEvents.map((event, index) => renderEventItem(event, index))}
                </div>
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="grouped" className="flex-1 overflow-hidden">
          <ScrollArea className="h-96">
            <div className="p-4 space-y-4">
              {Object.entries(groupedEvents).map(([nodeId, nodeEvents]) => (
                <div key={nodeId} className="border rounded-lg">
                  <button
                    onClick={() => toggleNodeExpansion(nodeId)}
                    className="w-full p-3 flex items-center justify-between hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      {expandedNodes.has(nodeId) ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                      <span className="font-medium">{nodeEvents[0].nodeName}</span>
                      <Badge variant="outline" className="text-xs">
                        {nodeEvents.length} events
                      </Badge>
                    </div>
                  </button>
                  {expandedNodes.has(nodeId) && (
                    <div className="border-t">
                      {nodeEvents.map((event, index) => renderEventItem(event, index, true))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="stats" className="flex-1 overflow-hidden">
          <ScrollArea className="h-96">
            <div className="p-4 space-y-6">
              <div>
                <h4 className="font-medium mb-3">Overall Statistics</h4>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-lg font-semibold">{eventStats.total}</div>
                    <div className="text-muted-foreground">Total Events</div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-lg font-semibold">
                      {eventStats.avgDuration ? formatDuration(eventStats.avgDuration) : '--'}
                    </div>
                    <div className="text-muted-foreground">Avg Duration</div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-lg font-semibold">{Math.round(eventStats.errorRate)}%</div>
                    <div className="text-muted-foreground">Error Rate</div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-lg font-semibold">{Object.keys(eventStats.byNode).length}</div>
                    <div className="text-muted-foreground">Active Nodes</div>
                  </div>
                </div>
              </div>

              <div>
                <h4 className="font-medium mb-3">Events by Type</h4>
                <div className="space-y-2">
                  {Object.entries(eventStats.byType).map(([type, count]) => (
                    <div key={type} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant={eventVariants[type]} className="text-xs">
                          {eventTypeLabels[type as keyof typeof eventTypeLabels]}
                        </Badge>
                      </div>
                      <span className="font-mono text-sm">{count}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h4 className="font-medium mb-3">Events by Node</h4>
                <div className="space-y-2">
                  {Object.entries(eventStats.byNode)
                    .sort(([,a], [,b]) => b - a)
                    .slice(0, 10)
                    .map(([node, count]) => (
                      <div key={node} className="flex items-center justify-between">
                        <span className="text-sm truncate">{node}</span>
                        <span className="font-mono text-sm">{count}</span>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  )
}

export default PipelineTimeline
