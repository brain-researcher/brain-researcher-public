'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { KPICard } from './KPICard'
import { LineChart } from '../charts/LineChart'
import { BarChart } from '../charts/BarChart'
import { cn } from '@/lib/utils'
import { 
  AnalyticsMetrics, 
  TimeRange, 
  KPICardData 
} from '@/types/analytics'
import { 
  Users, 
  Activity, 
  Zap, 
  Database, 
  TrendingUp, 
  Clock, 
  CheckCircle, 
  AlertCircle,
  Server,
  Brain
} from 'lucide-react'

interface MetricsOverviewProps {
  metrics: AnalyticsMetrics
  timeRange: TimeRange
  compactMode?: boolean
  className?: string
}

export function MetricsOverview({ 
  metrics, 
  timeRange, 
  compactMode = false, 
  className 
}: MetricsOverviewProps) {
  const buildTrend = (current: number, previous?: number | null): KPICardData['trend'] => {
    const safePrevious =
      typeof previous === 'number' && Number.isFinite(previous) ? previous : current

    const change = current - safePrevious
    const changePercentage = safePrevious === 0 ? 0 : (change / safePrevious) * 100

    const trend =
      Math.abs(change) < 1e-9 ? 'stable' : change > 0 ? 'up' : 'down'

    return {
      current,
      previous: safePrevious,
      change,
      changePercentage,
      trend,
    }
  }

  const latestUserGrowth = metrics.usage.userGrowth?.at?.(-1)
  const previousUserGrowth = metrics.usage.userGrowth?.at?.(-2)
  const activeUsersCurrent =
    typeof latestUserGrowth?.activeUsers === 'number'
      ? latestUserGrowth.activeUsers
      : metrics.usage.activeUsers
  const activeUsersPrevious =
    typeof previousUserGrowth?.activeUsers === 'number'
      ? previousUserGrowth.activeUsers
      : null

  const latestResponse = metrics.performance.responseTimeHistory?.at?.(-1)
  const previousResponse = metrics.performance.responseTimeHistory?.at?.(-2)
  const responseTimeCurrent =
    typeof latestResponse?.avgTime === 'number'
      ? latestResponse.avgTime
      : metrics.performance.avgResponseTime
  const responseTimePrevious =
    typeof previousResponse?.avgTime === 'number'
      ? previousResponse.avgTime
      : null
  
  // Calculate KPI data from metrics
  const kpiData: KPICardData[] = [
    {
      title: 'Active Users',
      value: activeUsersCurrent,
      format: 'number',
      subtitle: `${metrics.usage.newUsers} new users`,
      color: '#3b82f6',
      trend: buildTrend(activeUsersCurrent, activeUsersPrevious),
      isGoodWhenUp: true,
    },
    {
      title: 'Avg Response Time',
      value: responseTimeCurrent,
      format: 'number',
      unit: 'ms',
      subtitle: `${metrics.performance.p95ResponseTime}ms P95`,
      color: metrics.performance.avgResponseTime < 500 ? '#22c55e' : '#f59e0b',
      trend: buildTrend(responseTimeCurrent, responseTimePrevious),
      isGoodWhenUp: false,
      target: 500,
    },
    {
      title: 'Success Rate',
      value: metrics.performance.successRate,
      format: 'percentage',
      subtitle: `${metrics.performance.throughput} req/min`,
      color: metrics.performance.successRate >= 99 ? '#22c55e' : '#f59e0b',
      trend: buildTrend(metrics.performance.successRate, null),
      isGoodWhenUp: true,
      target: 99.5
    },
    {
      title: 'System Uptime',
      value: metrics.performance.uptime,
      format: 'percentage',
      subtitle: `${metrics.system.activeJobs} active jobs`,
      color: metrics.performance.uptime >= 99.9 ? '#22c55e' : '#ef4444',
      trend: buildTrend(metrics.performance.uptime, null),
      isGoodWhenUp: true,
      target: 99.9
    },
    {
      title: 'Analyses Run',
      value: metrics.research.analysesRun,
      format: 'number',
      subtitle: `${metrics.research.datasetStats.totalDatasets} datasets used`,
      color: '#8b5cf6',
      trend: buildTrend(metrics.research.analysesRun, null),
      isGoodWhenUp: true,
    },
    {
      title: 'Resource Usage',
      value: (metrics.system.cpuUsage + metrics.system.memoryUsage + metrics.system.gpuUsage) / 3,
      format: 'percentage',
      subtitle: `${metrics.system.storageUsage.toFixed(1)}% storage`,
      color: metrics.system.cpuUsage < 80 ? '#22c55e' : '#f59e0b',
      trend: buildTrend(
        (metrics.system.cpuUsage + metrics.system.memoryUsage + metrics.system.gpuUsage) / 3,
        null
      ),
      isGoodWhenUp: false,
      target: 80,
    }
  ]

  // Prepare chart data for user growth
  const userGrowthData = metrics.usage.userGrowth.map(item => ({
    ...item,
    date: new Date(item.date).toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric' 
    })
  }))

  // Prepare performance timeline data
  const performanceData = metrics.performance.responseTimeHistory.map(item => ({
    ...item,
    timestamp: new Date(item.timestamp).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit' 
    })
  }))

  // Popular tools data for bar chart
  const toolsData = Array.from(metrics.research.toolsUsed.entries())
    .sort(([,a], [,b]) => b - a)
    .slice(0, 8)
    .map(([tool, usage]) => ({
      tool: tool.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
      usage,
      percentage: (usage / Math.max(...Array.from(metrics.research.toolsUsed.values()))) * 100
    }))

  if (compactMode) {
    return (
      <div className={cn("grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4", className)}>
        {kpiData.map((kpi, index) => (
          <KPICard
            key={index}
            data={kpi}
            showTarget={false}
            className="min-h-[120px]"
          />
        ))}
      </div>
    )
  }

  return (
    <div className={cn("space-y-6", className)}>
      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {kpiData.map((kpi, index) => (
          <KPICard
            key={index}
            data={kpi}
            showTarget={true}
            className="min-h-[180px]"
          />
        ))}
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* User Growth Chart */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Users className="h-5 w-5 text-blue-500" />
              User Growth Trend
            </CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <LineChart
                data={userGrowthData}
                xAxisKey="date"
                lines={[
                  {
                    dataKey: 'activeUsers',
                    name: 'Active Users',
                    color: '#3b82f6',
                    strokeWidth: 2
                  },
                  {
                    dataKey: 'newUsers',
                    name: 'New Users',
                    color: '#22c55e',
                    strokeWidth: 2,
                    strokeDasharray: "5 5"
                  }
                ]}
                showGrid={true}
                showLegend={true}
                yAxisLabel="Users"
                formatYAxis={(value) => value.toLocaleString()}
              />
            </div>
          </CardContent>
        </Card>

        {/* Performance Timeline */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Zap className="h-5 w-5 text-yellow-500" />
              Response Time History
            </CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <LineChart
                data={performanceData}
                xAxisKey="timestamp"
                lines={[
                  {
                    dataKey: 'avgTime',
                    name: 'Average',
                    color: '#3b82f6',
                    strokeWidth: 2
                  },
                  {
                    dataKey: 'p95Time',
                    name: '95th Percentile',
                    color: '#ef4444',
                    strokeWidth: 2,
                    strokeDasharray: "3 3"
                  }
                ]}
                showGrid={true}
                showLegend={true}
                yAxisLabel="Response Time (ms)"
                formatYAxis={(value) => `${value}ms`}
                referenceLines={[
                  {
                    y: 500,
                    label: 'SLA Target',
                    stroke: '#22c55e',
                    strokeDasharray: "5 5"
                  }
                ]}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Additional Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Popular Tools */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Brain className="h-5 w-5 text-purple-500" />
              Most Used Analysis Tools
            </CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <BarChart
                data={toolsData}
                xAxisKey="tool"
                bars={[
                  {
                    dataKey: 'usage',
                    name: 'Usage Count',
                    color: '#8b5cf6'
                  }
                ]}
                showGrid={true}
                showLegend={false}
                yAxisLabel="Usage Count"
                formatYAxis={(value) => value.toLocaleString()}
                orientation="vertical"
              />
            </div>
          </CardContent>
        </Card>

        {/* System Health Overview */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Server className="h-5 w-5 text-green-500" />
              System Resource Usage
            </CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {/* CPU Usage */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">CPU Usage</span>
                  <span className="font-medium">{metrics.system.cpuUsage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${metrics.system.cpuUsage}%` }}
                  />
                </div>
              </div>

              {/* Memory Usage */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Memory Usage</span>
                  <span className="font-medium">{metrics.system.memoryUsage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                  <div
                    className="bg-green-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${metrics.system.memoryUsage}%` }}
                  />
                </div>
              </div>

              {/* GPU Usage */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">GPU Usage</span>
                  <span className="font-medium">{metrics.system.gpuUsage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                  <div
                    className="bg-purple-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${metrics.system.gpuUsage}%` }}
                  />
                </div>
              </div>

              {/* Storage Usage */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Storage Usage</span>
                  <span className="font-medium">{metrics.system.storageUsage.toFixed(1)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                  <div
                    className="bg-orange-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${metrics.system.storageUsage}%` }}
                  />
                </div>
              </div>

              {/* Job Queue Status */}
              <div className="pt-2 border-t">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Job Queue</span>
                  <div className="flex items-center gap-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm font-medium">
                      {metrics.system.activeJobs} active, {metrics.system.queueLength} queued
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Summary Stats */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-semibold">
            Summary for {timeRange.label}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">
                {metrics.usage.totalUsers.toLocaleString()}
              </div>
              <div className="text-sm text-muted-foreground">Total Users</div>
            </div>
            
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">
                {metrics.research.datasetStats.totalSubjects.toLocaleString()}
              </div>
              <div className="text-sm text-muted-foreground">Subjects Analyzed</div>
            </div>
            
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">
                {metrics.research.publicationMetrics.totalCitations}
              </div>
              <div className="text-sm text-muted-foreground">Total Citations</div>
            </div>
            
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-600">
                {metrics.system.completedJobs.toLocaleString()}
              </div>
              <div className="text-sm text-muted-foreground">Jobs Completed</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
