'use client'

import React from 'react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { 
  RefreshCw, 
  BarChart3, 
  Activity, 
  Users, 
  Server,
  TrendingUp,
  Clock,
  Database
} from 'lucide-react'

interface LoadingProgressProps {
  stage: string
  progress: number
  message?: string
  className?: string
}

export function LoadingProgress({ stage, progress, message, className }: LoadingProgressProps) {
  return (
    <Card className={cn("border-dashed", className)}>
      <CardContent className="p-6">
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <RefreshCw className="h-5 w-5 animate-spin text-blue-500" />
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Loading Analytics Data</span>
                <Badge variant="outline" className="text-xs">
                  {progress}%
                </Badge>
              </div>
              <Progress value={progress} className="h-2" />
            </div>
          </div>
          
          <div className="space-y-1">
            <div className="text-sm text-muted-foreground">
              Current Stage: <span className="font-medium text-foreground">{stage}</span>
            </div>
            {message && (
              <div className="text-xs text-muted-foreground">{message}</div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

interface KPICardSkeletonProps {
  className?: string
}

export function KPICardSkeleton({ className }: KPICardSkeletonProps) {
  return (
    <Card className={className}>
      <CardContent className="p-6">
        <div className="space-y-4">
          <div className="flex items-start justify-between">
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-3 w-20" />
            </div>
            <Skeleton className="h-3 w-3 rounded-full" />
          </div>
          
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-12" />
              <Skeleton className="h-3 w-16" />
            </div>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-2 w-full" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

interface ChartSkeletonProps {
  title?: string
  height?: number
  showLegend?: boolean
  className?: string
}

export function ChartSkeleton({ 
  title, 
  height = 300, 
  showLegend = true, 
  className 
}: ChartSkeletonProps) {
  return (
    <Card className={className}>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-muted-foreground" />
            {title ? (
              <span className="font-semibold">{title}</span>
            ) : (
              <Skeleton className="h-6 w-32" />
            )}
          </div>
          <Skeleton className="h-4 w-4 rounded" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {showLegend && (
            <div className="flex gap-4">
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-3 rounded-full" />
                <Skeleton className="h-3 w-16" />
              </div>
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-3 rounded-full" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
          )}
          
          <div 
            className="bg-muted/30 rounded animate-pulse flex items-center justify-center"
            style={{ height: `${height}px` }}
          >
            <div className="text-center space-y-2">
              <Activity className="h-8 w-8 mx-auto text-muted-foreground/50 animate-pulse" />
              <div className="text-sm text-muted-foreground">Loading chart data...</div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

interface MetricsOverviewSkeletonProps {
  compactMode?: boolean
  className?: string
}

export function MetricsOverviewSkeleton({ compactMode = false, className }: MetricsOverviewSkeletonProps) {
  const kpiCount = 6
  const chartCount = compactMode ? 0 : 4

  return (
    <div className={cn("space-y-6", className)}>
      {/* KPI Cards Grid */}
      <div className={cn(
        "grid gap-6",
        compactMode 
          ? "grid-cols-2 md:grid-cols-3 lg:grid-cols-6" 
          : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
      )}>
        {Array.from({ length: kpiCount }, (_, i) => (
          <KPICardSkeleton 
            key={i} 
            className={compactMode ? "min-h-[120px]" : "min-h-[180px]"} 
          />
        ))}
      </div>

      {/* Charts Section */}
      {!compactMode && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ChartSkeleton title="User Growth Trend" height={250} />
            <ChartSkeleton title="Performance Timeline" height={250} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ChartSkeleton title="Tool Usage Analysis" height={250} showLegend={false} />
            <ChartSkeleton title="System Resources" height={250} showLegend={false} />
          </div>

          {/* Summary Card */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-muted-foreground" />
                <Skeleton className="h-6 w-32" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                {Array.from({ length: 4 }, (_, i) => (
                  <div key={i} className="text-center space-y-2">
                    <Skeleton className="h-8 w-16 mx-auto" />
                    <Skeleton className="h-4 w-20 mx-auto" />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

interface UsageAnalyticsSkeletonProps {
  compactMode?: boolean
  className?: string
}

export function UsageAnalyticsSkeleleton({ compactMode = false, className }: UsageAnalyticsSkeletonProps) {
  return (
    <div className={cn("space-y-6", className)}>
      {/* Usage Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {Array.from({ length: 4 }, (_, i) => {
          const icons = [Users, Activity, Clock, Database]
          const Icon = icons[i]
          return (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Icon className="h-5 w-5 text-muted-foreground" />
                    <Skeleton className="h-4 w-20" />
                  </div>
                  <Skeleton className="h-5 w-12 rounded-full" />
                </div>
                <div className="space-y-2">
                  <Skeleton className="h-8 w-16" />
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-2 w-full" />
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {!compactMode && (
        <>
          {/* Tab Skeleton */}
          <div className="space-y-4">
            <div className="flex space-x-1 bg-muted p-1 rounded-lg w-fit">
              {['Overview', 'Engagement', 'Behavior'].map((tab) => (
                <Skeleton key={tab} className="h-9 w-24 rounded-md" />
              ))}
            </div>

            {/* Chart Skeletons */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ChartSkeleton title="User Growth Over Time" height={250} />
              <ChartSkeleton title="Most Popular Pages" height={250} showLegend={false} />
            </div>

            <ChartSkeleton title="Device Type Distribution" height={200} showLegend={false} />
          </div>
        </>
      )}
    </div>
  )
}

interface PerformanceMonitorSkeletonProps {
  compactMode?: boolean
  className?: string
}

export function PerformanceMonitorSkeleton({ compactMode = false, className }: PerformanceMonitorSkeletonProps) {
  return (
    <div className={cn("space-y-6", className)}>
      {/* Alert Skeleton */}
      {!compactMode && (
        <div className="flex items-center gap-3 p-4 rounded-lg border">
          <Skeleton className="h-4 w-4 rounded-full" />
          <div className="space-y-1 flex-1">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-64" />
          </div>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {Array.from({ length: 4 }, (_, i) => {
          const icons = [Clock, Activity, Server, Database]
          const Icon = icons[i]
          return (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Icon className="h-5 w-5 text-muted-foreground" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
                <div className="space-y-2">
                  <Skeleton className="h-8 w-20" />
                  <div className="space-y-1">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-3 w-20" />
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* System Health Indicators */}
      {!compactMode && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Server className="h-5 w-5 text-muted-foreground" />
              <Skeleton className="h-6 w-48" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="p-4 rounded-lg border space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Skeleton className="h-4 w-4" />
                      <Skeleton className="h-4 w-20" />
                    </div>
                    <Skeleton className="h-4 w-12 rounded-full" />
                  </div>
                  <Skeleton className="h-8 w-16" />
                  <Skeleton className="h-2 w-full" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

interface RealTimeMonitorSkeletonProps {
  className?: string
}

export function RealTimeMonitorSkeleton({ className }: RealTimeMonitorSkeletonProps) {
  return (
    <div className={cn("space-y-6", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-5" />
            <Skeleton className="h-5 w-12 rounded-full" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-4" />
            <Skeleton className="h-4 w-32" />
          </div>
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-20" />
        </div>
      </div>

      {/* Real-time Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-5 w-5" />
                  <Skeleton className="h-4 w-20" />
                </div>
                <div className="flex items-center gap-1">
                  <Skeleton className="h-3 w-3" />
                  <Skeleton className="h-3 w-3 rounded-full animate-pulse" />
                </div>
              </div>
              <div className="space-y-2">
                <Skeleton className="h-8 w-20" />
                <Skeleton className="h-3 w-24" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Real-time Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartSkeleton title="Active Users (Live)" height={250} showLegend={false} />
        <ChartSkeleton title="Response Time (Live)" height={250} showLegend={false} />
      </div>

      <ChartSkeleton title="System Resources (Live)" height={300} />
    </div>
  )
}

export interface AnalyticsLoadingStatesProps {
  stage: 'initial' | 'metrics' | 'usage' | 'performance' | 'realtime' | 'charts' | 'complete'
  progress?: number
  message?: string
  componentType?: 'dashboard' | 'overview' | 'usage' | 'performance' | 'realtime'
  compactMode?: boolean
  className?: string
}

export function AnalyticsLoadingStates({
  stage,
  progress = 0,
  message,
  componentType = 'dashboard',
  compactMode = false,
  className
}: AnalyticsLoadingStatesProps) {
  const stageMessages = {
    initial: 'Initializing analytics dashboard...',
    metrics: 'Loading performance metrics...',
    usage: 'Fetching usage analytics...',
    performance: 'Gathering system data...',
    realtime: 'Connecting to real-time stream...',
    charts: 'Rendering visualizations...',
    complete: 'Analytics dashboard ready!'
  }

  const currentMessage = message || stageMessages[stage]

  if (stage === 'initial') {
    return <LoadingProgress stage={stage} progress={progress} message={currentMessage} className={className} />
  }

  // Component-specific loading states
  switch (componentType) {
    case 'overview':
      return <MetricsOverviewSkeleton compactMode={compactMode} className={className} />
    
    case 'usage':
      return <UsageAnalyticsSkeleleton compactMode={compactMode} className={className} />
    
    case 'performance':
      return <PerformanceMonitorSkeleton compactMode={compactMode} className={className} />
    
    case 'realtime':
      return <RealTimeMonitorSkeleton className={className} />
    
    default:
      return (
        <div className={cn("space-y-6", className)}>
          <LoadingProgress stage={stage} progress={progress} message={currentMessage} />
          <MetricsOverviewSkeleton compactMode={compactMode} />
        </div>
      )
  }
}