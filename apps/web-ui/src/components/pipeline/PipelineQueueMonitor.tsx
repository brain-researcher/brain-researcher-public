'use client'

import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { DashboardData } from '@/hooks/useDashboardData'
import { Activity, Cpu, Clock, TrendingUp, RefreshCw, Wifi, WifiOff } from 'lucide-react'

type QueueMonitorProps = {
  dashboardData: DashboardData | null
  dashboardError: string | null
  connected?: boolean
  onRefresh?: () => void
  className?: string
}

type QueueSample = {
  timestamp: Date
  running: number
  queued: number
  throughputPerMinute: number | null
  oldestPendingSeconds: number | null
  cpuUsage: number | null
  memoryUsage: number | null
  queueSource: string | null
  activeWorkers: number | null
}

const toNumberOrNull = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

const formatDuration = (seconds: number | null) => {
  if (seconds === null) return '–'
  if (seconds <= 0) return '0s'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  if (mins <= 0) return `${secs}s`
  return `${mins}m ${secs}s`
}

export function PipelineQueueMonitor({
  dashboardData,
  dashboardError,
  connected = false,
  onRefresh,
  className,
}: QueueMonitorProps) {
  const [samples, setSamples] = useState<QueueSample[]>([])

  useEffect(() => {
    if (!dashboardData) return

    const queue = dashboardData.jobMetrics?.queue
    const cluster = dashboardData.resourceMetrics?.cluster
    const cpuUsage = toNumberOrNull((cluster as any)?.cpuUsage ?? (cluster as any)?.cpu_usage)
    const memoryUsage = toNumberOrNull(
      (cluster as any)?.memoryUsage ?? (cluster as any)?.memory_usage
    )

    const throughput = toNumberOrNull(dashboardData.jobMetrics.throughputPerMinute)
    const oldestPending = toNumberOrNull(dashboardData.jobMetrics.oldestPendingSeconds)
    const activeWorkers = toNumberOrNull(dashboardData.jobMetrics.activeWorkers)

    const timestamp = new Date(dashboardData.timestamp)
    const next: QueueSample = {
      timestamp: Number.isNaN(timestamp.getTime()) ? new Date() : timestamp,
      running: queue?.running ?? 0,
      queued: queue?.queued ?? 0,
      throughputPerMinute: throughput,
      oldestPendingSeconds: oldestPending,
      cpuUsage,
      memoryUsage,
      queueSource: dashboardData.jobMetrics.queueSource ?? null,
      activeWorkers: activeWorkers === null ? null : Math.max(0, Math.round(activeWorkers)),
    }

    setSamples((prev) => {
      const nextSamples = [...prev, next]
      return nextSamples.slice(-30)
    })
  }, [dashboardData])

  const current = samples[samples.length - 1]
  const previous = samples[samples.length - 2]

  const statusBadge = useMemo(() => {
    if (dashboardError) {
      return (
        <Badge variant="destructive" className="text-xs">
          Unavailable
        </Badge>
      )
    }
    return connected ? (
      <Badge variant="default" className="text-xs">
        Live
      </Badge>
    ) : (
      <Badge variant="secondary" className="text-xs">
        Polling
      </Badge>
    )
  }, [connected, dashboardError])

  const statusIcon = useMemo(() => {
    if (dashboardError) return <WifiOff className="h-4 w-4 text-rose-500" />
    return connected ? (
      <Wifi className="h-4 w-4 text-emerald-600" />
    ) : (
      <WifiOff className="h-4 w-4 text-amber-600" />
    )
  }, [connected, dashboardError])

  const deltaText = (value: number | null, prev: number | null, suffix = '') => {
    if (value === null || prev === null) return null
    const delta = value - prev
    if (Math.abs(delta) < 1e-9) return `0${suffix} change`
    const prefix = delta > 0 ? '+' : ''
    return `${prefix}${delta.toFixed(1)}${suffix} change`
  }

  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            {statusIcon}
            {statusBadge}
          </div>
          <div className="text-sm text-muted-foreground">
            {current ? `Updated: ${current.timestamp.toLocaleTimeString()}` : 'No data yet.'}
          </div>
          {current?.queueSource && (
            <Badge variant="outline" className="text-xs">
              source: {current.queueSource}
            </Badge>
          )}
          {typeof current?.activeWorkers === 'number' && (
            <span className="text-xs text-muted-foreground">
              workers: {current.activeWorkers}
            </span>
          )}
        </div>
        {onRefresh && (
          <Button variant="outline" size="sm" onClick={onRefresh} className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        )}
      </div>

      {dashboardError ? (
        <div className="text-sm text-red-600">No data yet: {dashboardError}</div>
      ) : !current ? (
        <div className="text-sm text-muted-foreground">No data yet.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Activity className="h-5 w-5 text-blue-500" />
                  <h3 className="text-sm font-medium">Running jobs</h3>
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-2xl font-bold">{current.running.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground">
                  {previous ? `${current.running - previous.running} from previous` : ''}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Clock className="h-5 w-5 text-yellow-500" />
                  <h3 className="text-sm font-medium">Queue depth</h3>
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-2xl font-bold">{current.queued.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground">
                  {previous ? `${current.queued - previous.queued} from previous` : ''}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-green-500" />
                  <h3 className="text-sm font-medium">Jobs/min</h3>
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-2xl font-bold">
                  {current.throughputPerMinute === null
                    ? '–'
                    : current.throughputPerMinute.toFixed(1)}
                </div>
                <div className="text-xs text-muted-foreground">
                  {previous?.throughputPerMinute != null && current.throughputPerMinute != null
                    ? deltaText(current.throughputPerMinute, previous.throughputPerMinute, '')
                    : ''}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Cpu className="h-5 w-5 text-purple-500" />
                  <h3 className="text-sm font-medium">CPU usage</h3>
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-2xl font-bold">
                  {current.cpuUsage === null ? '–' : `${current.cpuUsage.toFixed(1)}%`}
                </div>
                <div className="text-xs text-muted-foreground">
                  {previous?.cpuUsage != null && current.cpuUsage != null
                    ? deltaText(current.cpuUsage, previous.cpuUsage, '%')
                    : current.oldestPendingSeconds != null
                      ? `Oldest queued: ${formatDuration(current.oldestPendingSeconds)}`
                      : current.queued > 0
                        ? 'Oldest queued: –'
                        : ''}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
