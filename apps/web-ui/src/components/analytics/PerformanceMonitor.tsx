'use client'

import React, { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LineChart } from '../charts/LineChart'
import { BarChart } from '../charts/BarChart'
import { cn } from '@/lib/utils'
import { PerformanceMetrics, SystemMetrics, TimeRange } from '@/types/analytics'
import { 
  Zap, 
  Server, 
  AlertTriangle, 
  CheckCircle, 
  Activity,
  Clock,
  TrendingUp,
  TrendingDown,
  Cpu,
  HardDrive,
  MemoryStick,
  Database,
  Network,
  Shield,
  Target,
  Gauge,
  Timer,
  AlertCircle,
  Info
} from 'lucide-react'

interface PerformanceMonitorProps {
  metrics: PerformanceMetrics
  systemMetrics: SystemMetrics
  timeRange: TimeRange
  compactMode?: boolean
  className?: string
}

export function PerformanceMonitor({ 
  metrics, 
  systemMetrics, 
  timeRange, 
  compactMode = false, 
  className 
}: PerformanceMonitorProps) {
  const [selectedView, setSelectedView] = useState<'overview' | 'system' | 'errors' | 'endpoints'>('overview')

  // Performance status calculation
  const getPerformanceStatus = () => {
    const avgResponseTime = metrics.avgResponseTime
    const successRate = metrics.successRate
    const uptime = metrics.uptime

    if (avgResponseTime > 1000 || successRate < 95 || uptime < 99) {
      return { status: 'critical', color: 'red', label: 'Critical' }
    } else if (avgResponseTime > 500 || successRate < 98 || uptime < 99.5) {
      return { status: 'warning', color: 'yellow', label: 'Warning' }
    } else {
      return { status: 'healthy', color: 'green', label: 'Healthy' }
    }
  }

  const performanceStatus = getPerformanceStatus()

  // System health indicators
  const systemHealthIndicators = [
    {
      name: 'CPU Usage',
      value: systemMetrics.cpuUsage,
      unit: '%',
      status: systemMetrics.cpuUsage > 80 ? 'critical' : systemMetrics.cpuUsage > 60 ? 'warning' : 'healthy',
      icon: <Cpu className="h-4 w-4" />
    },
    {
      name: 'Memory Usage',
      value: systemMetrics.memoryUsage,
      unit: '%',
      status: systemMetrics.memoryUsage > 85 ? 'critical' : systemMetrics.memoryUsage > 70 ? 'warning' : 'healthy',
      icon: <MemoryStick className="h-4 w-4" />
    },
    {
      name: 'GPU Usage',
      value: systemMetrics.gpuUsage,
      unit: '%',
      status: systemMetrics.gpuUsage > 90 ? 'critical' : systemMetrics.gpuUsage > 75 ? 'warning' : 'healthy',
      icon: <Zap className="h-4 w-4" />
    },
    {
      name: 'Storage Usage',
      value: systemMetrics.storageUsage,
      unit: '%',
      status: systemMetrics.storageUsage > 90 ? 'critical' : systemMetrics.storageUsage > 80 ? 'warning' : 'healthy',
      icon: <HardDrive className="h-4 w-4" />
    }
  ]

  // Response time data
  const responseTimeData = metrics.responseTimeHistory.map(item => ({
    ...item,
    timestamp: new Date(item.timestamp).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit' 
    })
  }))

  // System resource history
  const resourceHistoryData = systemMetrics.resourceHistory.map(item => ({
    ...item,
    timestamp: new Date(item.timestamp).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit' 
    })
  }))

  // Error breakdown data
  const errorData = metrics.errorBreakdown.map(error => ({
    ...error,
    severity: error.type.includes('5') ? 'Server Error' : 
              error.type.includes('4') ? 'Client Error' : 'Other'
  }))

  // Endpoint performance sorted by response time
  const sortedEndpoints = [...metrics.endpointPerformance]
    .sort((a, b) => b.avgTime - a.avgTime)
    .slice(0, 10)

  // Job queue visualization data
  const jobQueueData = systemMetrics.jobQueue
    .reduce((acc, job) => {
      const status = job.status
      acc[status] = (acc[status] || 0) + 1
      return acc
    }, {} as Record<string, number>)

  const jobQueueChartData = Object.entries(jobQueueData).map(([status, count]) => ({
    status: status.charAt(0).toUpperCase() + status.slice(1),
    count,
    percentage: (count / systemMetrics.jobQueue.length) * 100
  }))

  if (compactMode) {
    return (
      <div className={cn("space-y-4", className)}>
        {/* Compact Performance Indicators */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Response Time</p>
                  <p className="text-lg font-semibold">{metrics.avgResponseTime}ms</p>
                </div>
                <Timer className="h-4 w-4 text-blue-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Success Rate</p>
                  <p className="text-lg font-semibold">{metrics.successRate.toFixed(1)}%</p>
                </div>
                <CheckCircle className="h-4 w-4 text-green-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">CPU Usage</p>
                  <p className="text-lg font-semibold">{systemMetrics.cpuUsage.toFixed(1)}%</p>
                </div>
                <Cpu className="h-4 w-4 text-purple-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Active Jobs</p>
                  <p className="text-lg font-semibold">{systemMetrics.activeJobs}</p>
                </div>
                <Activity className="h-4 w-4 text-orange-500" />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className={cn("space-y-6", className)}>
      {/* Performance Status Alert */}
      <Alert className={cn(
        performanceStatus.status === 'critical' ? 'border-red-500 bg-red-50 dark:bg-red-950' :
        performanceStatus.status === 'warning' ? 'border-yellow-500 bg-yellow-50 dark:bg-yellow-950' :
        'border-green-500 bg-green-50 dark:bg-green-950'
      )}>
        <div className="flex items-center gap-2">
          {performanceStatus.status === 'critical' ? <AlertCircle className="h-4 w-4" /> :
           performanceStatus.status === 'warning' ? <AlertTriangle className="h-4 w-4" /> :
           <CheckCircle className="h-4 w-4" />}
          <AlertDescription>
            <strong>System Status: {performanceStatus.label}</strong>
            {performanceStatus.status !== 'healthy' && (
              <span className="ml-2">
                Performance metrics indicate {performanceStatus.status === 'critical' ? 'critical' : 'warning'} conditions. 
                Review the detailed metrics below.
              </span>
            )}
          </AlertDescription>
        </div>
      </Alert>

      {/* Key Performance Indicators */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Timer className="h-5 w-5 text-blue-500" />
                <h3 className="text-sm font-medium">Response Time</h3>
              </div>
              <Badge variant={metrics.avgResponseTime < 500 ? "default" : "destructive"}>
                {metrics.avgResponseTime < 500 ? 'Good' : 'Slow'}
              </Badge>
            </div>
            
            <div className="space-y-2">
              <div className="text-2xl font-bold">{metrics.avgResponseTime}ms</div>
              <div className="text-xs text-muted-foreground space-y-1">
                <div>P50: {metrics.p50ResponseTime}ms</div>
                <div>P95: {metrics.p95ResponseTime}ms</div>
                <div>P99: {metrics.p99ResponseTime}ms</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Target className="h-5 w-5 text-green-500" />
                <h3 className="text-sm font-medium">Success Rate</h3>
              </div>
              <Badge variant={metrics.successRate >= 99 ? "default" : "destructive"}>
                {metrics.successRate >= 99 ? 'Excellent' : 'Poor'}
              </Badge>
            </div>
            
            <div className="space-y-2">
              <div className="text-2xl font-bold">{metrics.successRate.toFixed(2)}%</div>
              <div className="text-xs text-muted-foreground space-y-1">
                <div>Throughput: {metrics.throughput} req/min</div>
                <div>Error Rate: {metrics.errorRate.toFixed(2)}%</div>
              </div>
              
              <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700 mt-2">
                <div
                  className="bg-green-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${metrics.successRate}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-purple-500" />
                <h3 className="text-sm font-medium">System Uptime</h3>
              </div>
              <Badge variant={metrics.uptime >= 99.9 ? "default" : "destructive"}>
                {metrics.uptime >= 99.9 ? 'Stable' : 'Unstable'}
              </Badge>
            </div>
            
            <div className="space-y-2">
              <div className="text-2xl font-bold">{metrics.uptime.toFixed(3)}%</div>
              <div className="text-xs text-muted-foreground">
                Last 30 days availability
              </div>
              
              <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                <div
                  className="bg-purple-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${metrics.uptime}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Database className="h-5 w-5 text-orange-500" />
                <h3 className="text-sm font-medium">Job Queue</h3>
              </div>
              <Badge variant={systemMetrics.queueLength > 10 ? "destructive" : "secondary"}>
                {systemMetrics.queueLength > 10 ? 'Congested' : 'Normal'}
              </Badge>
            </div>
            
            <div className="space-y-2">
              <div className="text-2xl font-bold">{systemMetrics.queueLength}</div>
              <div className="text-xs text-muted-foreground space-y-1">
                <div>Active: {systemMetrics.activeJobs}</div>
                <div>Completed: {systemMetrics.completedJobs}</div>
                <div>Failed: {systemMetrics.failedJobs}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* System Health Indicators */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5 text-indigo-500" />
            System Health Indicators
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {systemHealthIndicators.map((indicator) => (
              <div key={indicator.name} className="p-4 rounded-lg border">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {indicator.icon}
                    <span className="text-sm font-medium">{indicator.name}</span>
                  </div>
                  <Badge 
                    variant={
                      indicator.status === 'critical' ? 'destructive' :
                      indicator.status === 'warning' ? 'secondary' : 'default'
                    }
                    className="text-xs"
                  >
                    {indicator.status}
                  </Badge>
                </div>
                
                <div className="text-2xl font-bold mb-2">
                  {indicator.value.toFixed(1)}{indicator.unit}
                </div>
                
                <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                  <div
                    className={cn(
                      "h-2 rounded-full transition-all duration-300",
                      indicator.status === 'critical' ? "bg-red-600" :
                      indicator.status === 'warning' ? "bg-yellow-600" : "bg-green-600"
                    )}
                    style={{ width: `${Math.min(indicator.value, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Detailed Performance Tabs */}
      <Tabs value={selectedView} onValueChange={(value) => setSelectedView(value as any)} className="space-y-4">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="system">System Resources</TabsTrigger>
          <TabsTrigger value="errors">Error Analysis</TabsTrigger>
          <TabsTrigger value="endpoints">Endpoints</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Response Time Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Activity className="h-5 w-5 text-blue-500" />
                  Response Time Trends
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <LineChart
                    data={responseTimeData}
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

            {/* Job Queue Status */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-orange-500" />
                  Job Queue Status
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <BarChart
                    data={jobQueueChartData}
                    xAxisKey="status"
                    bars={[
                      {
                        dataKey: 'count',
                        name: 'Jobs',
                        color: '#f59e0b'
                      }
                    ]}
                    showGrid={true}
                    showLegend={false}
                    yAxisLabel="Number of Jobs"
                    formatYAxis={(value) => value.toString()}
                  />
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="system" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Server className="h-5 w-5 text-green-500" />
                System Resource Usage Over Time
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <LineChart
                  data={resourceHistoryData}
                  xAxisKey="timestamp"
                  lines={[
                    {
                      dataKey: 'cpu',
                      name: 'CPU',
                      color: '#3b82f6',
                      strokeWidth: 2
                    },
                    {
                      dataKey: 'memory',
                      name: 'Memory',
                      color: '#22c55e',
                      strokeWidth: 2
                    },
                    {
                      dataKey: 'gpu',
                      name: 'GPU',
                      color: '#8b5cf6',
                      strokeWidth: 2
                    },
                    {
                      dataKey: 'storage',
                      name: 'Storage',
                      color: '#f59e0b',
                      strokeWidth: 2
                    }
                  ]}
                  showGrid={true}
                  showLegend={true}
                  yAxisLabel="Usage (%)"
                  formatYAxis={(value) => `${value}%`}
                  domain={[0, 100]}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="errors" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Error Breakdown */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5 text-red-500" />
                  Error Breakdown
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <BarChart
                    data={errorData}
                    xAxisKey="type"
                    bars={[
                      {
                        dataKey: 'count',
                        name: 'Error Count',
                        color: '#ef4444'
                      }
                    ]}
                    showGrid={true}
                    showLegend={false}
                    yAxisLabel="Error Count"
                    formatYAxis={(value) => value.toString()}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Error Details Table */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Info className="h-5 w-5 text-blue-500" />
                  Error Details
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {errorData.map((error, index) => (
                    <div key={index} className="flex items-center justify-between p-3 rounded-lg border">
                      <div>
                        <p className="font-medium text-sm">{error.type}</p>
                        <p className="text-xs text-muted-foreground">{error.severity}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium">{error.count.toLocaleString()}</p>
                        <p className="text-xs text-muted-foreground">
                          {error.percentage.toFixed(1)}%
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="endpoints" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Network className="h-5 w-5 text-purple-500" />
                Endpoint Performance Analysis
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Top 10 slowest endpoints by average response time
              </p>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {sortedEndpoints.map((endpoint, index) => (
                  <div key={endpoint.endpoint} className="flex items-center justify-between p-4 rounded-lg border">
                    <div className="flex items-center gap-3">
                      <Badge variant="outline" className="text-xs">
                        #{index + 1}
                      </Badge>
                      <div>
                        <p className="font-medium text-sm">{endpoint.endpoint}</p>
                        <p className="text-xs text-muted-foreground">
                          {endpoint.calls.toLocaleString()} calls • {endpoint.errors} errors
                        </p>
                      </div>
                    </div>
                    
                    <div className="text-right">
                      <p className="text-sm font-medium">{endpoint.avgTime}ms</p>
                      <p className="text-xs text-muted-foreground">
                        {((endpoint.errors / endpoint.calls) * 100).toFixed(2)}% error rate
                      </p>
                    </div>
                    
                    <Badge 
                      variant={endpoint.avgTime > 1000 ? "destructive" : endpoint.avgTime > 500 ? "secondary" : "default"}
                      className="text-xs ml-2"
                    >
                      {endpoint.avgTime > 1000 ? 'Slow' : endpoint.avgTime > 500 ? 'Medium' : 'Fast'}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}