'use client'

import React from 'react'
import { LineChart } from '@/components/charts/LineChart'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { UsageMetrics } from '@/types/analytics'
import { format } from 'date-fns'

interface UsageChartProps {
  data: UsageMetrics
  loading?: boolean
  className?: string
}

export function UsageChart({ data, loading, className }: UsageChartProps) {
  const formatChartData = () => {
    if (!data?.userGrowth || !Array.isArray(data.userGrowth)) return []
    return data.userGrowth.map(item => ({
      date: format(new Date(item.date), 'MMM dd'),
      'New Users': item.newUsers,
      'Active Users': item.activeUsers,
      timestamp: item.date
    }))
  }

  const formatHourlyData = () => {
    if (!data?.hourlyActivity || !Array.isArray(data.hourlyActivity)) return []
    return data.hourlyActivity.map(item => ({
      hour: `${item.hour}:00`,
      Users: item.users,
      Sessions: item.sessions
    }))
  }

  if (loading) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle className="flex items-center">
            User Activity Over Time
            <Badge variant="secondary" className="ml-2">Loading...</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-80 w-full animate-pulse bg-gray-200 rounded" />
        </CardContent>
      </Card>
    )
  }

  return (
    <div className={className}>
      {/* Main usage trends */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>User Growth Trends</span>
            <div className="flex space-x-2">
              <Badge variant="outline">
                Total Users: {data?.totalUsers?.toLocaleString() || '0'}
              </Badge>
              <Badge variant={data?.bounceRate < 50 ? "default" : "destructive"}>
                Bounce Rate: {data?.bounceRate?.toFixed(1) || '0'}%
              </Badge>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            data={formatChartData()}
            lines={[
              {
                dataKey: 'Active Users',
                name: 'Active Users',
                color: '#3b82f6',
                strokeWidth: 2
              },
              {
                dataKey: 'New Users',
                name: 'New Users',
                color: '#10b981',
                strokeWidth: 2,
                strokeDasharray: '5 5'
              }
            ]}
            xAxisKey="date"
            xAxisLabel="Date"
            yAxisLabel="Users"
            showGrid={true}
            showLegend={true}
            showBrush={true}
            className="h-80"
            formatTooltip={(value, name) => `${value.toLocaleString()} users`}
          />
        </CardContent>
      </Card>

      {/* Hourly activity heatmap */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Daily Activity Pattern</span>
            <Badge variant="secondary">
              Avg Session: {data?.avgSessionDuration?.toFixed(0) || '0'} min
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            data={formatHourlyData()}
            lines={[
              {
                dataKey: 'Users',
                name: 'Active Users',
                color: '#8b5cf6',
                strokeWidth: 2
              },
              {
                dataKey: 'Sessions',
                name: 'Sessions',
                color: '#f59e0b',
                strokeWidth: 2
              }
            ]}
            xAxisKey="hour"
            xAxisLabel="Hour of Day"
            yAxisLabel="Count"
            showGrid={true}
            showLegend={true}
            className="h-64"
            curveType="monotone"
          />
        </CardContent>
      </Card>

      {/* Top pages */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Most Popular Pages</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {(data?.topPages || []).slice(0, 5).map((page, index) => (
              <div key={page.page} className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className="text-sm font-medium text-muted-foreground w-6">
                    #{index + 1}
                  </span>
                  <span className="font-medium">{page.page}</span>
                </div>
                <div className="text-right">
                  <div className="font-medium">
                    {page.views.toLocaleString()} views
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {page.uniqueUsers.toLocaleString()} unique users
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}