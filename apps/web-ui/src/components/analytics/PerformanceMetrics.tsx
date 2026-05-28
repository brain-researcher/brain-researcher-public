'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { LineChart } from '@/components/charts/LineChart'
import { BarChart } from '@/components/charts/BarChart'
import { PerformanceMetrics as PerformanceMetricsType } from '@/types/analytics'
import { AlertTriangle, CheckCircle, Clock, Zap } from 'lucide-react'
import { format } from 'date-fns'

interface PerformanceMetricsProps {
  data: PerformanceMetricsType
  loading?: boolean
  className?: string
}

export function PerformanceMetrics({ data, loading, className }: PerformanceMetricsProps) {
  const formatResponseTimeData = () => {
    return data.responseTimeHistory.map(item => ({
      timestamp: format(new Date(item.timestamp), 'MMM dd HH:mm'),
      'Average': item.avgTime,
      'P95': item.p95Time,
      date: item.timestamp
    }))
  }

  const formatErrorData = () => {
    return data.errorBreakdown.map(item => ({
      type: item.type,
      count: item.count,
      percentage: item.percentage
    }))
  }

  const formatEndpointData = () => {
    return data.endpointPerformance
      .sort((a, b) => b.calls - a.calls)
      .slice(0, 10)
      .map(item => ({
        endpoint: item.endpoint.length > 30 
          ? `...${item.endpoint.slice(-27)}` 
          : item.endpoint,
        'Avg Response (ms)': item.avgTime,
        'Total Calls': item.calls,
        'Error Rate (%)': (item.errors / item.calls * 100).toFixed(2)
      }))
  }

  const getUptimeColor = (uptime: number) => {
    if (uptime >= 99.9) return 'text-green-600'
    if (uptime >= 99.0) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getResponseTimeStatus = (avgTime: number) => {
    if (avgTime < 200) return { icon: CheckCircle, color: 'text-green-600', label: 'Excellent' }
    if (avgTime < 500) return { icon: Clock, color: 'text-yellow-600', label: 'Good' }
    if (avgTime < 1000) return { icon: AlertTriangle, color: 'text-orange-600', label: 'Warning' }
    return { icon: AlertTriangle, color: 'text-red-600', label: 'Critical' }
  }

  if (loading) {
    return (
      <div className={className}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {[1, 2, 3, 4].map(i => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="h-20 animate-pulse bg-gray-200 rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  const responseTimeStatus = getResponseTimeStatus(data.avgResponseTime)
  const ResponseTimeIcon = responseTimeStatus.icon

  return (
    <div className={className}>
      {/* Key metrics cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Avg Response Time</p>
                <p className="text-2xl font-bold">{data.avgResponseTime}ms</p>
              </div>
              <ResponseTimeIcon className={`h-8 w-8 ${responseTimeStatus.color}`} />
            </div>
            <Badge 
              variant="secondary" 
              className={`mt-2 ${responseTimeStatus.color}`}
            >
              {responseTimeStatus.label}
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Success Rate</p>
                <p className="text-2xl font-bold">{data.successRate.toFixed(1)}%</p>
              </div>
              <CheckCircle className={`h-8 w-8 ${
                data.successRate >= 99 ? 'text-green-600' : 
                data.successRate >= 95 ? 'text-yellow-600' : 'text-red-600'
              }`} />
            </div>
            <Progress 
              value={data.successRate} 
              className="mt-2"
            />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Throughput</p>
                <p className="text-2xl font-bold">{data.throughput.toFixed(0)}</p>
                <p className="text-xs text-muted-foreground">requests/sec</p>
              </div>
              <Zap className="h-8 w-8 text-blue-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Uptime</p>
                <p className={`text-2xl font-bold ${getUptimeColor(data.uptime)}`}>
                  {data.uptime.toFixed(2)}%
                </p>
              </div>
              <div className={`h-8 w-8 rounded-full ${
                data.uptime >= 99.9 ? 'bg-green-100 text-green-600' :
                data.uptime >= 99.0 ? 'bg-yellow-100 text-yellow-600' : 
                'bg-red-100 text-red-600'
              } flex items-center justify-center`}>
                <CheckCircle className="h-5 w-5" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Response time trend */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Response Time Trends</span>
            <div className="flex space-x-2">
              <Badge variant="outline">P50: {data.p50ResponseTime}ms</Badge>
              <Badge variant="outline">P95: {data.p95ResponseTime}ms</Badge>
              <Badge variant="outline">P99: {data.p99ResponseTime}ms</Badge>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            data={formatResponseTimeData()}
            lines={[
              {
                dataKey: 'Average',
                name: 'Average Response Time',
                color: '#3b82f6',
                strokeWidth: 2
              },
              {
                dataKey: 'P95',
                name: '95th Percentile',
                color: '#f59e0b',
                strokeWidth: 2,
                strokeDasharray: '5 5'
              }
            ]}
            xAxisKey="timestamp"
            xAxisLabel="Time"
            yAxisLabel="Response Time (ms)"
            showGrid={true}
            showLegend={true}
            className="h-80"
            referenceLines={[
              { y: 500, label: 'Target', stroke: '#10b981', strokeDasharray: '3 3' }
            ]}
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Error breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Error Breakdown</span>
              <Badge variant={data.errorRate < 1 ? "default" : "destructive"}>
                {data.errorRate.toFixed(1)}% Error Rate
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart
              data={formatErrorData()}
              bars={[
                {
                  dataKey: 'count',
                  name: 'Error Count',
                  color: '#ef4444'
                }
              ]}
              xAxisKey="type"
              xAxisLabel="Error Type"
              yAxisLabel="Count"
              showGrid={true}
              className="h-64"
            />
          </CardContent>
        </Card>

        {/* Top endpoints by performance */}
        <Card>
          <CardHeader>
            <CardTitle>Endpoint Performance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4 max-h-80 overflow-y-auto">
              {data.endpointPerformance
                .sort((a, b) => b.avgTime - a.avgTime)
                .slice(0, 8)
                .map((endpoint, index) => (
                <div key={endpoint.endpoint} className="flex items-center justify-between p-3 rounded-lg border">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate" title={endpoint.endpoint}>
                      {endpoint.endpoint}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {endpoint.calls.toLocaleString()} calls
                    </p>
                  </div>
                  <div className="text-right ml-4">
                    <p className={`font-medium text-sm ${
                      endpoint.avgTime < 200 ? 'text-green-600' :
                      endpoint.avgTime < 500 ? 'text-yellow-600' :
                      'text-red-600'
                    }`}>
                      {endpoint.avgTime.toFixed(0)}ms
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {(endpoint.errors / endpoint.calls * 100).toFixed(1)}% errors
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}