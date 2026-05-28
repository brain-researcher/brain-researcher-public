'use client'

import React from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { MetricsOverview } from '@/components/analytics/MetricsOverview'
import { RealTimeMonitor } from '@/components/analytics/RealTimeMonitor'
import { TimeRangeSelector } from '@/components/analytics/TimeRangeSelector'
import { useAnalytics } from '@/hooks/useAnalytics'
import { RefreshCw } from 'lucide-react'

export function AnalyticsDashboard() {
  const { metrics, loading, error, filter, setTimeRange, refresh, timeRanges } = useAnalytics()

  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-red-600">
          Analytics unavailable: {error}
        </CardContent>
      </Card>
    )
  }

  if (loading && !metrics) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin" />
        Loading analytics…
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="text-sm text-muted-foreground">No data yet.</div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Analytics</h2>
          <p className="text-sm text-muted-foreground">
            Usage, performance, and system metrics.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <TimeRangeSelector
            value={filter.timeRange}
            onChange={setTimeRange}
            presets={timeRanges}
          />
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      <MetricsOverview metrics={metrics} timeRange={filter.timeRange} />
      <RealTimeMonitor metrics={metrics} />
    </div>
  )
}
