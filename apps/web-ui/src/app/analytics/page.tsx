'use client'

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { 
  BarChart3, 
  Activity, 
  Database, 
  Cpu, 
  Users,
  TrendingUp,
  RefreshCw,
  Settings,
  AlertCircle
} from 'lucide-react'

// Components
import { KPICard } from '@/components/analytics/KPICard'
import { TimeRangeSelector } from '@/components/analytics/TimeRangeSelector'
import { UsageChart } from '@/components/analytics/UsageChart'
import { PerformanceMetrics } from '@/components/analytics/PerformanceMetrics'
import { ResearchInsights } from '@/components/analytics/ResearchInsights'
import { SystemHealthMonitor } from '@/components/analytics/SystemHealthMonitor'
import { ExportMenu } from '@/components/analytics/ExportMenu'

// Hooks and types
import { useAnalytics } from '@/hooks/useAnalytics'
import { KPICardData } from '@/types/analytics'

export default function AnalyticsPage() {
  const {
    metrics,
    loading,
    error,
    filter,
    realTimeEnabled,
    lastUpdated,
    setTimeRange,
    toggleRealTime,
    refresh,
    exportData,
    timeRanges
  } = useAnalytics()

  const getPreviousValue = (current: number, previous?: number) => {
    if (typeof previous !== 'number' || Number.isNaN(previous)) return current
    return previous
  }

  const computeTrend = (current: number, previous?: number) => {
    const safePrevious = getPreviousValue(current, previous)
    const change = current - safePrevious
    const changePercentage = safePrevious === 0 ? 0 : (change / safePrevious) * 100
    const trend = Math.abs(change) < 0.01 ? 'stable' : change > 0 ? 'up' : 'down'
    return {
      current,
      previous: safePrevious,
      change,
      changePercentage,
      trend: trend as 'up' | 'down' | 'stable'
    }
  }

  // Derived KPI data
  const getKPIData = (): KPICardData[] => {
    if (!metrics) return []

    const usageHistory = metrics.usage.userGrowth || []
    const usageTail = usageHistory.slice(-2)
    const latestUsage = usageTail[usageTail.length - 1]
    const previousUsage = usageTail.length > 1 ? usageTail[0] : undefined

    const responseHistory = metrics.performance.responseTimeHistory || []
    const responseTail = responseHistory.slice(-2)
    const latestResponse = responseTail[responseTail.length - 1]
    const previousResponse = responseTail.length > 1 ? responseTail[0] : undefined

    return [
      {
        title: 'Total Users',
        value: metrics.usage.totalUsers,
        format: 'number',
        trend: computeTrend(
          metrics.usage.totalUsers,
          Math.max(metrics.usage.totalUsers - metrics.usage.newUsers, 0)
        ),
        subtitle: 'All time registered users',
        color: '#3b82f6'
      },
      {
        title: 'Active Users',
        value: metrics.usage.activeUsers,
        format: 'number',
        trend: computeTrend(
          metrics.usage.activeUsers,
          previousUsage?.activeUsers
        ),
        subtitle: 'Users in selected period',
        color: '#10b981'
      },
      {
        title: 'Avg Response Time',
        value: metrics.performance.avgResponseTime,
        format: 'number',
        unit: 'ms',
        isGoodWhenUp: false,
        trend: computeTrend(
          metrics.performance.avgResponseTime,
          previousResponse?.avgTime
        ),
        subtitle: 'System performance',
        color: '#f59e0b',
        target: 500
      },
      {
        title: 'Success Rate',
        value: metrics.performance.successRate,
        format: 'percentage',
        trend: computeTrend(metrics.performance.successRate),
        subtitle: 'Request success rate',
        color: '#10b981',
        target: 99.5
      }
    ]
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="w-96">
          <CardContent className="p-6 text-center">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-lg font-semibold mb-2">Analytics Error</h2>
            <p className="text-muted-foreground mb-4">{error}</p>
            <Button onClick={refresh}>Try Again</Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50/50 dark:bg-gray-900/50">
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Analytics Dashboard</h1>
            <p className="text-muted-foreground mt-1">
              Monitor usage, performance, and system health
            </p>
            {lastUpdated && (
              <p className="text-xs text-muted-foreground mt-1">
                Last updated: {lastUpdated.toLocaleTimeString()}
              </p>
            )}
          </div>
          
          <div className="flex items-center space-x-4">
            {/* Real-time toggle */}
            <div className="flex items-center space-x-2">
              <Switch
                id="realtime"
                checked={realTimeEnabled}
                onCheckedChange={toggleRealTime}
              />
              <Label htmlFor="realtime" className="text-sm">
                Real-time
              </Label>
              {realTimeEnabled && (
                <Badge variant="secondary" className="animate-pulse">
                  Live
                </Badge>
              )}
            </div>

            {/* Time range selector */}
            <TimeRangeSelector
              value={filter.timeRange}
              onChange={setTimeRange}
              presets={timeRanges}
            />

            {/* Action buttons */}
            <Button
              variant="outline"
              size="sm"
              onClick={refresh}
              disabled={loading}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>

            <ExportMenu
              onExport={exportData}
              filter={filter}
            />
          </div>
        </div>

        {/* KPI Cards */}
        {metrics && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {getKPIData().map((kpi, index) => (
              <KPICard 
                key={index} 
                data={kpi} 
                showTarget={kpi.target !== undefined}
              />
            ))}
          </div>
        )}

        {/* Main Content */}
        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="overview" className="flex items-center space-x-2">
              <BarChart3 className="h-4 w-4" />
              <span>Overview</span>
            </TabsTrigger>
            <TabsTrigger value="usage" className="flex items-center space-x-2">
              <Users className="h-4 w-4" />
              <span>Usage</span>
            </TabsTrigger>
            <TabsTrigger value="performance" className="flex items-center space-x-2">
              <Activity className="h-4 w-4" />
              <span>Performance</span>
            </TabsTrigger>
            <TabsTrigger value="research" className="flex items-center space-x-2">
              <Database className="h-4 w-4" />
              <span>Research</span>
            </TabsTrigger>
            <TabsTrigger value="system" className="flex items-center space-x-2">
              <Cpu className="h-4 w-4" />
              <span>System</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Quick overview cards */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center">
                    <TrendingUp className="h-5 w-5 mr-2" />
                    Key Trends
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {metrics ? (
                    <div className="space-y-4">
                      <div className="flex justify-between items-center">
                        <span className="text-sm">User Growth</span>
                        <Badge variant="default" className="text-green-600 bg-green-50">
                          +{metrics.usage.newUsers} new users
                        </Badge>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm">Performance</span>
                        <Badge variant={metrics.performance.avgResponseTime < 500 ? "default" : "destructive"}>
                          {metrics.performance.avgResponseTime}ms avg
                        </Badge>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm">System Health</span>
                        <Badge variant={metrics.system.cpuUsage < 80 ? "default" : "destructive"}>
                          {metrics.system.cpuUsage.toFixed(0)}% CPU
                        </Badge>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm">Research Activity</span>
                        <Badge variant="secondary">
                          {metrics.research.analysesRun} analyses
                        </Badge>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {[1, 2, 3, 4].map(i => (
                        <div key={i} className="h-6 bg-gray-200 rounded animate-pulse" />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Current Status</CardTitle>
                </CardHeader>
                <CardContent>
                  {metrics ? (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="text-center p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20">
                          <div className="text-2xl font-bold text-blue-600">
                            {metrics.system.activeJobs}
                          </div>
                          <div className="text-sm text-muted-foreground">Active Jobs</div>
                        </div>
                        <div className="text-center p-4 rounded-lg bg-green-50 dark:bg-green-900/20">
                          <div className="text-2xl font-bold text-green-600">
                            {metrics.system.queueLength}
                          </div>
                          <div className="text-sm text-muted-foreground">In Queue</div>
                        </div>
                      </div>
                      <div className="text-center">
                        <Badge 
                          variant={
                            metrics.performance.successRate >= 99 ? "default" :
                            metrics.performance.successRate >= 95 ? "secondary" : "destructive"
                          }
                          className="text-lg px-4 py-1"
                        >
                          {metrics.performance.successRate.toFixed(1)}% Success Rate
                        </Badge>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="h-20 bg-gray-200 rounded animate-pulse" />
                        <div className="h-20 bg-gray-200 rounded animate-pulse" />
                      </div>
                      <div className="h-8 bg-gray-200 rounded animate-pulse" />
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="usage">
            {metrics?.usage ? (
              <UsageChart data={metrics.usage} loading={loading} />
            ) : (
              <Card>
                <CardContent className="p-8">
                  <div className="h-80 animate-pulse bg-gray-200 rounded" />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="performance">
            {metrics?.performance ? (
              <PerformanceMetrics data={metrics.performance} loading={loading} />
            ) : (
              <Card>
                <CardContent className="p-8">
                  <div className="h-80 animate-pulse bg-gray-200 rounded" />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="research">
            {metrics?.research ? (
              <ResearchInsights data={metrics.research} loading={loading} />
            ) : (
              <Card>
                <CardContent className="p-8">
                  <div className="h-80 animate-pulse bg-gray-200 rounded" />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="system">
            {metrics?.system ? (
              <SystemHealthMonitor data={metrics.system} loading={loading} />
            ) : (
              <Card>
                <CardContent className="p-8">
                  <div className="h-80 animate-pulse bg-gray-200 rounded" />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
