/**
 * ToolUsageHeatmap - Tool usage summary (no mock data).
 *
 * NOTE: The current telemetry API (FeatureUsage) provides aggregate feature stats only.
 * A true hour×day heatmap requires per-time-bucket breakdowns that are not available yet.
 */

'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { RefreshCw, Grid3x3 as Thermometer, Clock, Users, Zap } from 'lucide-react'
import { useTelemetry, type FeatureUsage } from './telemetry-provider'
import { useInteractionTracking } from './telemetry-provider'

type ToolRow = {
  name: string
  totalUses: number
  uniqueUsers: number
  successRate: number
  avgDurationMs?: number
  peakUsageHour?: number
  trend: 'up' | 'down' | 'stable'
  category: string
}

const TOOL_CATEGORIES: Record<string, { label: string; badgeVariant: 'default' | 'secondary' | 'outline' }> = {
  analysis: { label: 'Analysis', badgeVariant: 'default' },
  visualization: { label: 'Visualization', badgeVariant: 'secondary' },
  preprocessing: { label: 'Preprocessing', badgeVariant: 'secondary' },
  statistics: { label: 'Statistics', badgeVariant: 'secondary' },
  data_management: { label: 'Data', badgeVariant: 'outline' },
  workflow: { label: 'Workflow', badgeVariant: 'outline' },
  export: { label: 'Export', badgeVariant: 'outline' },
}

const categorizeTool = (toolName: string): string => {
  const name = toolName.toLowerCase()
  if (name.includes('analysis') || name.includes('glm') || name.includes('model')) return 'analysis'
  if (name.includes('plot') || name.includes('chart') || name.includes('visual')) return 'visualization'
  if (name.includes('preprocess') || name.includes('clean') || name.includes('filter')) return 'preprocessing'
  if (name.includes('stat') || name.includes('test') || name.includes('correlation')) return 'statistics'
  if (name.includes('load') || name.includes('save') || name.includes('import')) return 'data_management'
  if (name.includes('workflow') || name.includes('pipeline') || name.includes('batch')) return 'workflow'
  if (name.includes('export') || name.includes('download') || name.includes('share')) return 'export'
  return 'analysis'
}

const formatDuration = (ms?: number) => {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '–'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}

export const ToolUsageHeatmap: React.FC = () => {
  const { getFeatureAnalysis } = useTelemetry()
  const trackInteraction = useInteractionTracking('tool_usage_heatmap')

  const [timeRange, setTimeRange] = useState<'7d' | '30d'>('7d')
  const [features, setFeatures] = useState<FeatureUsage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const rows: ToolRow[] = useMemo(() => {
    return features
      .map((feature) => ({
        name: feature.featureName,
        totalUses: feature.totalUses,
        uniqueUsers: feature.uniqueUsers,
        successRate: feature.successRate,
        avgDurationMs: feature.avgDurationMs,
        peakUsageHour: feature.peakUsageHour,
        trend: (
          feature.trend === 'increasing'
            ? 'up'
            : feature.trend === 'decreasing'
              ? 'down'
              : 'stable'
        ) as ToolRow['trend'],
        category: categorizeTool(feature.featureName),
      }))
      .sort((a, b) => b.totalUses - a.totalUses)
  }, [features])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const endTime = new Date()
      const daysMap: Record<'7d' | '30d', number> = { '7d': 7, '30d': 30 }
      const startTime = new Date(endTime.getTime() - daysMap[timeRange] * 24 * 60 * 60 * 1000)

      const featuresData = await getFeatureAnalysis({
        start_time: startTime.toISOString(),
        end_time: endTime.toISOString(),
        min_usage_count: 1,
      })
      setFeatures(Array.isArray(featuresData) ? featuresData : [])

      trackInteraction('data_loaded', { timeRange, toolsCount: Array.isArray(featuresData) ? featuresData.length : 0 })
    } catch (err) {
      setFeatures([])
      setError(err instanceof Error ? err.message : 'Failed to load tool usage data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange])

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading tool usage…
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center justify-between gap-4 p-8 text-sm">
          <span className="text-red-600">Failed to load tool usage: {error}</span>
          <Button variant="outline" size="sm" onClick={loadData}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Thermometer className="h-5 w-5" />
              Tool Usage
            </CardTitle>
            <CardDescription>
              Aggregate telemetry by tool. Heatmap view requires per-hour/per-day breakdowns that are not available yet.
            </CardDescription>
          </div>

          <div className="flex items-center gap-2">
            <Select value={timeRange} onValueChange={(value) => setTimeRange(value as '7d' | '30d')}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="Time range" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7d">Last 7 days</SelectItem>
                <SelectItem value="30d">Last 30 days</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={loadData}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {rows.length === 0 ? (
          <div className="text-sm text-muted-foreground">No data yet.</div>
        ) : (
          <div className="space-y-3">
            {rows.slice(0, 25).map((row) => {
              const categoryMeta = TOOL_CATEGORIES[row.category] ?? TOOL_CATEGORIES.analysis
              const successPct = Number.isFinite(row.successRate) ? Math.round(row.successRate * 100) : null
              return (
                <div key={row.name} className="rounded-lg border p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="font-medium truncate">{row.name}</div>
                        <Badge variant={categoryMeta.badgeVariant}>{categoryMeta.label}</Badge>
                        <Badge variant="outline" className="capitalize">
                          {row.trend}
                        </Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Total uses: {row.totalUses.toLocaleString()} • Unique users: {row.uniqueUsers.toLocaleString()}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <div className="flex items-center gap-1">
                        <Zap className="h-4 w-4 text-muted-foreground" />
                        <span>{successPct === null ? '–' : `${successPct}%`}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Clock className="h-4 w-4 text-muted-foreground" />
                        <span>{formatDuration(row.avgDurationMs)}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Users className="h-4 w-4 text-muted-foreground" />
                        <span>{row.peakUsageHour == null ? '–' : `${row.peakUsageHour}:00`}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
