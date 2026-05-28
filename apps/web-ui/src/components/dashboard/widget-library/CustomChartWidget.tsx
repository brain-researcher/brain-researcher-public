'use client'

import React, { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { 
  BarChart3,
  LineChart,
  ScatterChart,
  Settings,
  RefreshCw
} from 'lucide-react'
import { LineChart as RechartsLineChart, BarChart as RechartsBarChart, XAxis, YAxis, CartesianGrid, Tooltip, Line, Bar, ResponsiveContainer, ScatterChart as RechartsScatterChart, Scatter as ScatterDot } from 'recharts'
import { CustomChartData, WidgetComponentProps } from '@/types/dashboard'

interface CustomChartWidgetProps extends WidgetComponentProps {
  data?: CustomChartData
}

export const CustomChartWidget: React.FC<CustomChartWidgetProps> = ({
  widget,
  data,
  loading = false,
  error,
  onRefresh,
  onConfigChange,
  className = ''
}) => {
  const [chartType, setChartType] = useState<'line' | 'bar' | 'scatter'>('line')
  
  const renderChart = (chartData: CustomChartData) => {
    const commonProps = {
      data: chartData.data,
      margin: { top: 5, right: 30, left: 20, bottom: 5 }
    }

    switch (chartType) {
      case 'bar':
        return (
          <ResponsiveContainer width="100%" height={200}>
            <RechartsBarChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={chartData.config.x_axis} />
              <YAxis />
              <Tooltip />
              <Bar dataKey={chartData.config.y_axis} fill="#3b82f6" />
            </RechartsBarChart>
          </ResponsiveContainer>
        )
      case 'scatter':
        return (
          <ResponsiveContainer width="100%" height={200}>
            <RechartsScatterChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={chartData.config.x_axis} />
              <YAxis />
              <Tooltip />
              <ScatterDot dataKey={chartData.config.y_axis} fill="#3b82f6" />
            </RechartsScatterChart>
          </ResponsiveContainer>
        )
      default:
        return (
          <ResponsiveContainer width="100%" height={200}>
            <RechartsLineChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={chartData.config.x_axis} />
              <YAxis />
              <Tooltip />
              <Line 
                type="monotone" 
                dataKey={chartData.config.y_axis} 
                stroke="#3b82f6" 
                strokeWidth={2}
                dot={{ fill: '#3b82f6', strokeWidth: 2, r: 4 }}
              />
            </RechartsLineChart>
          </ResponsiveContainer>
        )
    }
  }

  const getChartIcon = (type: string) => {
    switch (type) {
      case 'bar':
        return <BarChart3 className="h-4 w-4" />
      case 'scatter':
        return <ScatterChart className="h-4 w-4" />
      default:
        return <LineChart className="h-4 w-4" />
    }
  }

  if (loading) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Custom Chart
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse">
            <div className="h-48 bg-gray-200 rounded"></div>
            <div className="mt-3 space-y-2">
              <div className="h-4 bg-gray-200 rounded w-1/3"></div>
              <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Custom Chart
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
            <BarChart3 className="h-8 w-8 mb-2" />
            <p className="text-sm text-center">{error}</p>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
                Retry
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card className={`h-full ${className}`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Custom Chart
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
            <BarChart3 className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm text-center">No data yet.</p>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
                Retry
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`h-full ${className}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            {getChartIcon(chartType)}
            {data.config.title || 'Custom Chart'}
          </CardTitle>
          <div className="flex items-center gap-1">
            {onRefresh && (
              <Button variant="ghost" size="sm" onClick={onRefresh}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
            {onConfigChange && (
              <Button variant="ghost" size="sm">
                <Settings className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Chart Type Selector */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Type:</span>
          <Select value={chartType} onValueChange={(value: 'line' | 'bar' | 'scatter') => setChartType(value)}>
            <SelectTrigger className="w-24 h-7">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="line">
                <div className="flex items-center gap-2">
                  <LineChart className="h-3 w-3" />
                  Line
                </div>
              </SelectItem>
              <SelectItem value="bar">
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-3 w-3" />
                  Bar
                </div>
              </SelectItem>
              <SelectItem value="scatter">
                <div className="flex items-center gap-2">
                  <ScatterChart className="h-3 w-3" />
                  Scatter
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Chart */}
        <div className="w-full">
          {renderChart(data)}
        </div>

        {/* Chart Info */}
        <div className="pt-2 border-t">
          <div className="grid grid-cols-2 gap-4 text-xs text-muted-foreground">
            <div>
              <p className="font-medium">X-Axis: {data.config.x_axis}</p>
            </div>
            <div>
              <p className="font-medium">Y-Axis: {data.config.y_axis}</p>
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-2">
          <Button variant="outline" size="sm">
            Export Data
          </Button>
          <Button variant="outline" size="sm">
            <Settings className="h-4 w-4 mr-1" />
            Configure
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
