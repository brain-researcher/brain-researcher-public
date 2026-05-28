'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LineChart } from '../charts/LineChart'
import { cn } from '@/lib/utils'
import { AnalyticsMetrics } from '@/types/analytics'
import { serviceEndpoints } from '@/lib/service-endpoints'
import { 
  Activity, 
  Zap, 
  Users, 
  Server, 
  Pause, 
  Play,
  Radio,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Wifi,
  WifiOff,
  Clock,
  Eye,
  MousePointer,
  Database
} from 'lucide-react'

interface RealTimeMonitorProps {
  metrics: AnalyticsMetrics
  connectionStatusOverride?: 'connected' | 'disconnected' | 'reconnecting'
  refreshInterval?: number
  className?: string
}

interface RealTimeDataPoint {
  timestamp: string
  activeUsers: number
  responseTime: number | null
  requestsPerSecond: number | null
  cpuUsage: number
  memoryUsage: number
  errorRate: number | null
}

export function RealTimeMonitor({ 
  metrics, 
  connectionStatusOverride,
  refreshInterval = 5000, 
  className 
}: RealTimeMonitorProps) {
  const [isActive, setIsActive] = useState(true)
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('reconnecting')
  const [realtimeData, setRealtimeData] = useState<RealTimeDataPoint[]>([])
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const fetchRealtime = useCallback(async () => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/analytics/realtime'), {
        headers: { 'Cache-Control': 'no-cache' },
      })
      if (!response.ok) {
        throw new Error(`Realtime analytics failed: ${response.status}`)
      }
      const data = await response.json()
      if (!isMountedRef.current) return

      const now = data?.timestamp ? new Date(data.timestamp) : new Date()

      const newDataPoint: RealTimeDataPoint = {
        timestamp: now.toISOString(),
        activeUsers: typeof data?.activeUsers === 'number' ? data.activeUsers : 0,
        responseTime: typeof data?.responseTime === 'number' ? data.responseTime : null,
        requestsPerSecond: typeof data?.requestsPerSecond === 'number' ? data.requestsPerSecond : null,
        cpuUsage: typeof data?.cpuUsage === 'number' ? data.cpuUsage : 0,
        memoryUsage: typeof data?.memoryUsage === 'number' ? data.memoryUsage : 0,
        errorRate: typeof data?.errorRate === 'number' ? data.errorRate : null
      }

      setRealtimeData(prev => {
        const updated = [...prev, newDataPoint]
        return updated.slice(-50)
      })
      setLastUpdate(now)
      setConnectionStatus('connected')
    } catch (error) {
      if (isMountedRef.current) {
        console.error('Failed to fetch realtime analytics:', error)
        setConnectionStatus('disconnected')
      }
    }
  }, [metrics])

  // Poll real-time analytics snapshot
  useEffect(() => {
    if (!isActive) return

    fetchRealtime()
    intervalRef.current = setInterval(fetchRealtime, refreshInterval)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [isActive, refreshInterval, fetchRealtime])

  // Format data for charts
  const chartData = realtimeData.map(point => ({
    ...point,
    time: new Date(point.timestamp).toLocaleTimeString('en-US', { 
      hour12: false,
      minute: '2-digit',
      second: '2-digit'
    })
  }))

  // Calculate trends
  const getTrend = (current: number | null, previous: number | null): 'up' | 'down' | 'stable' => {
    if (current === null || previous === null) return 'stable'
    if (Math.abs(current - previous) < 0.1) return 'stable'
    return current > previous ? 'up' : 'down'
  }

  // Current vs previous values for trend calculation
  const currentData = realtimeData[realtimeData.length - 1]
  const previousData = realtimeData[realtimeData.length - 2]

  const trends = currentData && previousData ? {
    activeUsers: getTrend(currentData.activeUsers, previousData.activeUsers),
    responseTime: getTrend(currentData.responseTime, previousData.responseTime),
    requestsPerSecond: getTrend(currentData.requestsPerSecond, previousData.requestsPerSecond),
    cpuUsage: getTrend(currentData.cpuUsage, previousData.cpuUsage)
  } : {
    activeUsers: 'stable' as const,
    responseTime: 'stable' as const,
    requestsPerSecond: 'stable' as const,
    cpuUsage: 'stable' as const
  }

  const getTrendIcon = (trend: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up': return <TrendingUp className="h-3 w-3" />
      case 'down': return <TrendingDown className="h-3 w-3" />
      default: return <Minus className="h-3 w-3" />
    }
  }

  const getTrendColor = (trend: 'up' | 'down' | 'stable', isGoodWhenUp = true) => {
    if (trend === 'stable') return 'text-gray-500'
    if (isGoodWhenUp) {
      return trend === 'up' ? 'text-green-500' : 'text-red-500'
    } else {
      return trend === 'up' ? 'text-red-500' : 'text-green-500'
    }
  }

  const handleToggleMonitoring = () => {
    setIsActive(!isActive)
  }

  const handleReconnect = () => {
    setConnectionStatus('reconnecting')
    fetchRealtime()
  }

  const effectiveStatus = connectionStatusOverride ?? connectionStatus

  return (
    <div className={cn("space-y-6", className)}>
      {/* Real-time Status Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {effectiveStatus === 'connected' ? (
              <>
                <Wifi className="h-5 w-5 text-green-500" />
                <Badge variant="default" className="text-xs">Live</Badge>
              </>
            ) : (
              <>
                <WifiOff className="h-5 w-5 text-red-500" />
                <Badge variant="destructive" className="text-xs">
                  {effectiveStatus === 'reconnecting' ? 'Reconnecting' : 'Disconnected'}
                </Badge>
              </>
            )}
          </div>
          
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" />
            <span>
              Last updated: {lastUpdate.toLocaleTimeString()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleToggleMonitoring}
            className="flex items-center gap-2"
          >
            {isActive ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {isActive ? 'Pause' : 'Resume'}
          </Button>
          
          {effectiveStatus === 'disconnected' && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleReconnect}
              className="flex items-center gap-2"
            >
              <RefreshCw className="h-4 w-4" />
              Reconnect
            </Button>
          )}
        </div>
      </div>

      {/* Connection Status Alert */}
      {effectiveStatus !== 'connected' && (
        <Alert className="border-yellow-500 bg-yellow-50 dark:bg-yellow-950">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {effectiveStatus === 'disconnected' 
              ? 'Real-time monitoring is disconnected. Some data may be outdated.'
              : 'Attempting to reconnect to real-time data stream...'}
          </AlertDescription>
        </Alert>
      )}

      {/* Real-time Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Users className="h-5 w-5 text-blue-500" />
                <h3 className="text-sm font-medium">Active Users</h3>
              </div>
              <div className={cn("flex items-center gap-1", getTrendColor(trends.activeUsers, true))}>
                {getTrendIcon(trends.activeUsers)}
                <Radio className={cn("h-3 w-3", isActive && effectiveStatus === 'connected' ? "animate-pulse" : "")} />
              </div>
            </div>
            
	            <div className="space-y-2">
	              <div className="text-2xl font-bold">
	                {currentData ? currentData.activeUsers.toLocaleString() : '–'}
	              </div>
	              <div className="text-xs text-muted-foreground">
	                {previousData && currentData && (
	                  <>
                    {currentData.activeUsers > previousData.activeUsers ? '+' : ''}
                    {(currentData.activeUsers - previousData.activeUsers).toLocaleString()} from previous
                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Zap className="h-5 w-5 text-yellow-500" />
                <h3 className="text-sm font-medium">Response Time</h3>
              </div>
              <div className={cn("flex items-center gap-1", getTrendColor(trends.responseTime, false))}>
                {getTrendIcon(trends.responseTime)}
                <Radio className={cn("h-3 w-3", isActive && effectiveStatus === 'connected' ? "animate-pulse" : "")} />
              </div>
            </div>
            
	            <div className="space-y-2">
	              <div className="text-2xl font-bold">
	                {currentData?.responseTime == null ? '–' : `${currentData.responseTime.toFixed(0)}ms`}
	              </div>
	              <div className="text-xs text-muted-foreground">
	                {previousData && currentData && currentData.responseTime != null && previousData.responseTime != null && (
	                  <>
	                    {currentData.responseTime > previousData.responseTime ? '+' : ''}
	                    {(currentData.responseTime - previousData.responseTime).toFixed(0)}ms change
	                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-green-500" />
                <h3 className="text-sm font-medium">Requests/sec</h3>
              </div>
              <div className={cn("flex items-center gap-1", getTrendColor(trends.requestsPerSecond, true))}>
                {getTrendIcon(trends.requestsPerSecond)}
                <Radio className={cn("h-3 w-3", isActive && effectiveStatus === 'connected' ? "animate-pulse" : "")} />
              </div>
            </div>
            
	            <div className="space-y-2">
	              <div className="text-2xl font-bold">
	                {currentData?.requestsPerSecond == null ? '–' : currentData.requestsPerSecond.toFixed(1)}
	              </div>
	              <div className="text-xs text-muted-foreground">
	                {previousData && currentData && currentData.requestsPerSecond != null && previousData.requestsPerSecond != null && (
	                  <>
	                    {currentData.requestsPerSecond > previousData.requestsPerSecond ? '+' : ''}
	                    {(currentData.requestsPerSecond - previousData.requestsPerSecond).toFixed(1)} change
	                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Server className="h-5 w-5 text-purple-500" />
                <h3 className="text-sm font-medium">CPU Usage</h3>
              </div>
              <div className={cn("flex items-center gap-1", getTrendColor(trends.cpuUsage, false))}>
                {getTrendIcon(trends.cpuUsage)}
                <Radio className={cn("h-3 w-3", isActive && effectiveStatus === 'connected' ? "animate-pulse" : "")} />
              </div>
            </div>
            
	            <div className="space-y-2">
	              <div className="text-2xl font-bold">
	                {currentData ? `${currentData.cpuUsage.toFixed(1)}%` : '–'}
	              </div>
	              <div className="text-xs text-muted-foreground">
	                {previousData && currentData && (
	                  <>
                    {currentData.cpuUsage > previousData.cpuUsage ? '+' : ''}
                    {(currentData.cpuUsage - previousData.cpuUsage).toFixed(1)}% change
                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Real-time Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active Users Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5 text-blue-500" />
              Active Users (Live)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              {chartData.length > 0 ? (
                <LineChart
                  data={chartData}
                  xAxisKey="time"
                  lines={[
                    {
                      dataKey: 'activeUsers',
                      name: 'Active Users',
                      color: '#3b82f6',
                      strokeWidth: 2,
                      dot: false
                    }
                  ]}
                  showGrid={true}
                  showLegend={false}
                  yAxisLabel="Users"
                  formatYAxis={(value) => value.toLocaleString()}
                />
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground">
                  <RefreshCw className="h-8 w-8 animate-spin" />
                  <span className="ml-2">Collecting real-time data...</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Response Time Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-yellow-500" />
              Response Time (Live)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              {chartData.length > 0 ? (
                <LineChart
                  data={chartData}
                  xAxisKey="time"
                  lines={[
                    {
                      dataKey: 'responseTime',
                      name: 'Response Time',
                      color: '#f59e0b',
                      strokeWidth: 2,
                      dot: false
                    }
                  ]}
                  showGrid={true}
                  showLegend={false}
                  yAxisLabel="Response Time (ms)"
                  formatYAxis={(value) => `${value}ms`}
                  referenceLines={[
                    {
                      y: 500,
                      label: 'SLA Target',
                      stroke: '#ef4444',
                      strokeDasharray: "3 3"
                    }
                  ]}
                />
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground">
                  <RefreshCw className="h-8 w-8 animate-spin" />
                  <span className="ml-2">Collecting real-time data...</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* System Resources Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5 text-purple-500" />
            System Resources (Live)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            {chartData.length > 0 ? (
              <LineChart
                data={chartData}
                xAxisKey="time"
                lines={[
                  {
                    dataKey: 'cpuUsage',
                    name: 'CPU Usage',
                    color: '#8b5cf6',
                    strokeWidth: 2,
                    dot: false
                  },
                  {
                    dataKey: 'memoryUsage',
                    name: 'Memory Usage',
                    color: '#22c55e',
                    strokeWidth: 2,
                    dot: false
                  },
                  {
                    dataKey: 'errorRate',
                    name: 'Error Rate',
                    color: '#ef4444',
                    strokeWidth: 2,
                    dot: false,
                    strokeDasharray: "3 3"
                  }
                ]}
                showGrid={true}
                showLegend={true}
                yAxisLabel="Percentage (%)"
                formatYAxis={(value) => `${value.toFixed(1)}%`}
                domain={[0, 100]}
                referenceLines={[
                  {
                    y: 80,
                    label: 'High Usage Threshold',
                    stroke: '#f59e0b',
                    strokeDasharray: "5 5"
                  }
                ]}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                <RefreshCw className="h-8 w-8 animate-spin" />
                <span className="ml-2">Collecting real-time data...</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Real-time Alerts */}
      {currentData && (
        <div className="space-y-4">
          {currentData.responseTime > 1000 && (
            <Alert className="border-red-500 bg-red-50 dark:bg-red-950">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>High Response Time Alert:</strong> Current response time ({currentData.responseTime.toFixed(0)}ms) 
                exceeds the critical threshold of 1000ms.
              </AlertDescription>
            </Alert>
          )}
          
          {currentData.cpuUsage > 85 && (
            <Alert className="border-yellow-500 bg-yellow-50 dark:bg-yellow-950">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>High CPU Usage Alert:</strong> Current CPU usage ({currentData.cpuUsage.toFixed(1)}%) 
                is approaching critical levels.
              </AlertDescription>
            </Alert>
          )}
          
          {currentData.errorRate > 5 && (
            <Alert className="border-red-500 bg-red-50 dark:bg-red-950">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>High Error Rate Alert:</strong> Current error rate ({currentData.errorRate.toFixed(1)}%) 
                exceeds acceptable thresholds.
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}
    </div>
  )
}
