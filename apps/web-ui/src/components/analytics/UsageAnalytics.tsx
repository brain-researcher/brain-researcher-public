'use client'

import React, { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LineChart } from '../charts/LineChart'
import { BarChart } from '../charts/BarChart'
import { cn } from '@/lib/utils'
import { UsageMetrics, TimeRange } from '@/types/analytics'
import { 
  Users, 
  Clock, 
  MousePointer, 
  Globe, 
  Smartphone,
  Monitor,
  Tablet,
  TrendingUp,
  TrendingDown,
  Activity,
  Eye,
  UserCheck,
  UserX,
  Calendar,
  ArrowRight
} from 'lucide-react'

interface UsageAnalyticsProps {
  metrics: UsageMetrics
  timeRange: TimeRange
  compactMode?: boolean
  className?: string
}

export function UsageAnalytics({ 
  metrics, 
  timeRange, 
  compactMode = false, 
  className 
}: UsageAnalyticsProps) {
  const [selectedView, setSelectedView] = useState<'overview' | 'engagement' | 'behavior'>('overview')

  const hourlyActivityChartData = [...metrics.hourlyActivity]
    .sort((a, b) => a.hour - b.hour)
    .map(item => ({
      ...item,
      hourLabel: `${item.hour}:00`
    }))

  // Top pages with engagement metrics
  const topPagesWithMetrics = metrics.topPages.map(page => ({
    ...page,
    engagementRate: page.views > 0 ? (page.uniqueUsers / page.views) * 100 : 0,
  })).sort((a, b) => b.engagementRate - a.engagementRate)

  // User growth data formatted for chart
  const userGrowthChartData = metrics.userGrowth.map(item => ({
    ...item,
    date: new Date(item.date).toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric' 
    }),
  }))

  const getDeviceIcon = (device: string) => {
    switch (device.toLowerCase()) {
      case 'desktop': return <Monitor className="h-4 w-4" />
      case 'mobile': return <Smartphone className="h-4 w-4" />
      case 'tablet': return <Tablet className="h-4 w-4" />
      default: return <Monitor className="h-4 w-4" />
    }
  }

  if (compactMode) {
    return (
      <div className={cn("space-y-4", className)}>
        {/* Compact KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Active Users</p>
                  <p className="text-lg font-semibold">{metrics.activeUsers.toLocaleString()}</p>
                </div>
                <Users className="h-4 w-4 text-blue-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Bounce Rate</p>
                  <p className="text-lg font-semibold">{metrics.bounceRate.toFixed(1)}%</p>
                </div>
                <TrendingDown className="h-4 w-4 text-red-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Avg Session</p>
                  <p className="text-lg font-semibold">
                    {Math.round(metrics.avgSessionDuration / 60)}m
                  </p>
                </div>
                <Clock className="h-4 w-4 text-green-500" />
              </div>
            </CardContent>
          </Card>
          
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">Page Views</p>
                  <p className="text-lg font-semibold">{metrics.pageViewsPerSession.toFixed(1)}</p>
                </div>
                <Eye className="h-4 w-4 text-purple-500" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Compact chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">User Activity Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-48">
              <LineChart
                data={userGrowthChartData.slice(-7)}
                xAxisKey="date"
                lines={[
                  {
                    dataKey: 'activeUsers',
                    name: 'Active Users',
                    color: '#3b82f6'
                  }
                ]}
                showGrid={false}
                showLegend={false}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className={cn("space-y-6", className)}>
      {/* Usage Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Users className="h-5 w-5 text-blue-500" />
                <h3 className="text-sm font-medium">User Base</h3>
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-2xl font-bold">{metrics.totalUsers.toLocaleString()}</span>
                <Badge variant="secondary" className="text-xs">
                  Total
                </Badge>
              </div>
              
              <div className="flex justify-between text-sm text-muted-foreground">
                <span>Active: {metrics.activeUsers.toLocaleString()}</span>
                <span>New: {metrics.newUsers.toLocaleString()}</span>
              </div>
              
              <div className="pt-2">
                <div className="flex items-center gap-2 text-xs">
                  <UserCheck className="h-3 w-3 text-green-500" />
                  <span>
                    {((metrics.activeUsers / metrics.totalUsers) * 100).toFixed(1)}% active
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-green-500" />
                <h3 className="text-sm font-medium">Engagement</h3>
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-2xl font-bold">
                  {Math.round(metrics.avgSessionDuration / 60)}m
                </span>
                <Badge variant="secondary" className="text-xs">
                  Avg Session
                </Badge>
              </div>
              
              <div className="flex justify-between text-sm text-muted-foreground">
                <span>Sessions/User: {metrics.sessionsPerUser.toFixed(1)}</span>
              </div>
              
              <div className="flex justify-between text-sm text-muted-foreground">
                <span>Pages/Session: {metrics.pageViewsPerSession.toFixed(1)}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <MousePointer className="h-5 w-5 text-purple-500" />
                <h3 className="text-sm font-medium">Bounce Rate</h3>
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-2xl font-bold">
                  {metrics.bounceRate.toFixed(1)}%
                </span>
                <Badge 
                  variant={metrics.bounceRate < 40 ? "default" : "destructive"} 
                  className="text-xs"
                >
                  {metrics.bounceRate < 40 ? 'Good' : 'High'}
                </Badge>
              </div>
              
              <div className="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700">
                <div
                  className={cn(
                    "h-2 rounded-full transition-all duration-300",
                    metrics.bounceRate < 40 ? "bg-green-600" : "bg-red-600"
                  )}
                  style={{ width: `${metrics.bounceRate}%` }}
                />
              </div>
              
              <div className="text-xs text-muted-foreground">
                Industry avg: 40-60%
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Globe className="h-5 w-5 text-orange-500" />
                <h3 className="text-sm font-medium">Traffic Source</h3>
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span>Direct</span>
                  <span>45%</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Search</span>
                  <span>35%</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Social</span>
                  <span>20%</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Detailed Analytics Tabs */}
      <Tabs value={selectedView} onValueChange={(value) => setSelectedView(value as any)} className="space-y-4">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="engagement">Engagement</TabsTrigger>
          <TabsTrigger value="behavior">Behavior</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* User Growth Chart */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-blue-500" />
                  User Growth Over Time
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <LineChart
                    data={userGrowthChartData}
                    xAxisKey="date"
                    lines={[
                      {
                        dataKey: 'activeUsers',
                        name: 'Active Users',
                        color: '#3b82f6',
                        strokeWidth: 3
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

            {/* Top Pages */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Eye className="h-5 w-5 text-green-500" />
                  Most Popular Pages
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {topPagesWithMetrics.slice(0, 6).map((page, index) => (
                    <div key={page.page} className="flex items-center justify-between p-3 rounded-lg border">
                      <div className="flex items-center gap-3">
                        <Badge variant="outline" className="text-xs">
                          #{index + 1}
                        </Badge>
                        <div>
                          <p className="font-medium text-sm">{page.page}</p>
                          <p className="text-xs text-muted-foreground">
                            {page.views.toLocaleString()} views • {page.uniqueUsers.toLocaleString()} unique
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium">
                          {page.engagementRate.toFixed(1)}%
                        </p>
                        <p className="text-xs text-muted-foreground">engagement</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Device Type Distribution */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Monitor className="h-5 w-5 text-purple-500" />
                Device Type Distribution
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                No data yet. Device breakdown requires telemetry ingestion (user-agent/device type),
                which isn’t available from the current analytics payload.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="engagement" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Session Duration Distribution */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Clock className="h-5 w-5 text-orange-500" />
                  Session Duration Distribution
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  No data yet. Session duration buckets require per-session analytics events, which are not
                  included in the current metrics API.
                </div>
              </CardContent>
            </Card>

            {/* Retention & Churn */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <UserCheck className="h-5 w-5 text-green-500" />
                  User Retention Trends
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  No data yet. Retention/churn requires cohort tracking (user/session IDs over time),
                  which isn’t available from the current usage metrics.
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="behavior" className="space-y-6">
          {/* Hourly activity */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Calendar className="h-5 w-5 text-indigo-500" />
                Hourly Activity
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Aggregate activity by hour (day-of-week breakdown is not available yet).
              </p>
            </CardHeader>
            <CardContent>
              {hourlyActivityChartData.length === 0 ? (
                <div className="text-sm text-muted-foreground">No data yet.</div>
              ) : (
                <div className="h-64">
                  <BarChart
                    data={hourlyActivityChartData}
                    xAxisKey="hourLabel"
                    bars={[
                      {
                        dataKey: 'users',
                        name: 'Users',
                        color: '#6366f1'
                      },
                      {
                        dataKey: 'sessions',
                        name: 'Sessions',
                        color: '#0ea5e9'
                      }
                    ]}
                    showGrid={true}
                    showLegend={true}
                    yAxisLabel="Count"
                    formatYAxis={(value) => value.toLocaleString()}
                  />
                </div>
              )}
            </CardContent>
          </Card>

          {/* User Journey Flow */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ArrowRight className="h-5 w-5 text-blue-500" />
                Common User Journeys
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                No data yet. User journeys require path analytics (page view sequences) which are not
                captured by the current metrics API.
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
