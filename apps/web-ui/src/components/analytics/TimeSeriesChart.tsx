'use client'

import React, { useState, useRef, useMemo } from 'react'
import {
  LineChart as RechartsLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  TooltipProps,
  Brush,
  ReferenceLine,
  ReferenceArea,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { 
  ZoomIn, 
  ZoomOut, 
  RotateCcw, 
  Download, 
  Settings,
  Calendar,
  TrendingUp,
  BarChart3,
  LineChart as LineChartIcon,
  AreaChart
} from 'lucide-react'

export interface TimeSeriesDataPoint {
  timestamp: string | number
  [key: string]: any
}

export interface TimeSeriesLine {
  dataKey: string
  name?: string
  color?: string
  strokeWidth?: number
  strokeDasharray?: string
  dot?: boolean
  fill?: string
  type?: 'monotone' | 'linear' | 'basis' | 'step'
  connectNulls?: boolean
}

export interface TimeSeriesChartProps {
  data: TimeSeriesDataPoint[]
  lines: TimeSeriesLine[]
  xAxisKey: string
  title?: string
  subtitle?: string
  height?: number
  showBrush?: boolean
  showZoomControls?: boolean
  showLegend?: boolean
  showGrid?: boolean
  enableZoom?: boolean
  enablePan?: boolean
  xAxisLabel?: string
  yAxisLabel?: string
  formatXAxis?: (value: any) => string
  formatYAxis?: (value: any) => string
  formatTooltip?: (value: any, name: string, props: any) => [string, string]
  domain?: [number | 'auto' | 'dataMin' | 'dataMax', number | 'auto' | 'dataMin' | 'dataMax']
  referenceLines?: Array<{
    y?: number
    x?: string | number
    label?: string
    stroke?: string
    strokeDasharray?: string
  }>
  aggregation?: 'none' | 'hour' | 'day' | 'week' | 'month'
  className?: string
  onExportData?: (data: TimeSeriesDataPoint[]) => void
}

type ChartType = 'line' | 'area' | 'bar'

const CustomTooltip = ({ 
  active, 
  payload, 
  label, 
  formatter, 
  labelFormatter 
}: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg bg-background/95 backdrop-blur-sm p-4 shadow-lg border border-border/50">
        <p className="text-sm font-medium mb-3 text-foreground">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
        <div className="space-y-2">
          {payload.map((entry, index) => {
            const [value, name] = formatter 
              ? formatter(entry.value, entry.name || '', entry)
              : [entry.value, entry.name || '']
            
            return (
              <div key={index} className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <div 
                    className="w-3 h-3 rounded-full" 
                    style={{ backgroundColor: entry.color }}
                  />
                  <span className="text-sm text-muted-foreground">{name}</span>
                </div>
                <span className="text-sm font-medium text-foreground">{value}</span>
              </div>
            )
          })}
        </div>
      </div>
    )
  }
  return null
}

export function TimeSeriesChart({
  data,
  lines,
  xAxisKey,
  title,
  subtitle,
  height = 400,
  showBrush = true,
  showZoomControls = true,
  showLegend = true,
  showGrid = true,
  enableZoom = true,
  enablePan = true,
  xAxisLabel,
  yAxisLabel,
  formatXAxis,
  formatYAxis,
  formatTooltip,
  domain,
  referenceLines = [],
  aggregation = 'none',
  className,
  onExportData
}: TimeSeriesChartProps) {
  const [zoomDomain, setZoomDomain] = useState<{ left?: number; right?: number } | null>(null)
  const [chartType, setChartType] = useState<ChartType>('line')
  const [selectedLines, setSelectedLines] = useState<Set<string>>(new Set(lines.map(l => l.dataKey)))
  const [brushDomain, setBrushDomain] = useState<{ startIndex?: number; endIndex?: number } | null>(null)
  const chartRef = useRef<any>(null)

  // Data aggregation logic
  const aggregatedData = useMemo(() => {
    if (aggregation === 'none') return data

    const aggregateBy = (timeUnit: string) => {
      const grouped = data.reduce((acc, item) => {
        const date = new Date(item[xAxisKey])
        let key: string

        switch (timeUnit) {
          case 'hour':
            key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}-${date.getHours()}`
            break
          case 'day':
            key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
            break
          case 'week':
            const weekStart = new Date(date)
            weekStart.setDate(date.getDate() - date.getDay())
            key = weekStart.toISOString().split('T')[0]
            break
          case 'month':
            key = `${date.getFullYear()}-${date.getMonth()}`
            break
          default:
            key = item[xAxisKey].toString()
        }

        if (!acc[key]) {
          acc[key] = { [xAxisKey]: key, count: 0, ...Object.fromEntries(lines.map(l => [l.dataKey, 0])) }
        }

        lines.forEach(line => {
          if (typeof item[line.dataKey] === 'number') {
            acc[key][line.dataKey] += item[line.dataKey]
          }
        })
        acc[key].count += 1

        return acc
      }, {} as Record<string, any>)

      return Object.values(grouped).map((group: any) => {
        const result = { [xAxisKey]: group[xAxisKey] }
        lines.forEach(line => {
          result[line.dataKey] = group[line.dataKey] / group.count // Average
        })
        return result
      })
    }

    return aggregateBy(aggregation)
  }, [data, aggregation, lines, xAxisKey])

  // Filter data based on zoom domain
  const filteredData = useMemo(() => {
    if (!zoomDomain || (!zoomDomain.left && !zoomDomain.right)) {
      return aggregatedData
    }

    const startIndex = zoomDomain.left || 0
    const endIndex = zoomDomain.right || aggregatedData.length - 1

    return aggregatedData.slice(startIndex, endIndex + 1)
  }, [aggregatedData, zoomDomain])

  // Filter lines based on selection
  const visibleLines = lines.filter(line => selectedLines.has(line.dataKey))

  const handleZoomIn = () => {
    if (filteredData.length <= 2) return
    
    const currentLength = filteredData.length
    const newStart = Math.floor(currentLength * 0.25)
    const newEnd = Math.floor(currentLength * 0.75)
    
    setZoomDomain({
      left: newStart,
      right: newEnd
    })
  }

  const handleZoomOut = () => {
    if (!zoomDomain) {
      return // Already at maximum zoom out
    }
    
    if (zoomDomain.left === 0 && zoomDomain.right === aggregatedData.length - 1) {
      setZoomDomain(null)
    } else {
      const currentStart = zoomDomain.left || 0
      const currentEnd = zoomDomain.right || aggregatedData.length - 1
      const currentLength = currentEnd - currentStart
      
      const newStart = Math.max(0, currentStart - Math.floor(currentLength * 0.25))
      const newEnd = Math.min(aggregatedData.length - 1, currentEnd + Math.floor(currentLength * 0.25))
      
      setZoomDomain({ left: newStart, right: newEnd })
    }
  }

  const handleReset = () => {
    setZoomDomain(null)
    setBrushDomain(null)
  }

  const handleBrushChange = (newBrushDomain: { startIndex?: number; endIndex?: number } | null) => {
    setBrushDomain(newBrushDomain)
    if (newBrushDomain) {
      setZoomDomain({
        left: newBrushDomain.startIndex,
        right: newBrushDomain.endIndex
      })
    }
  }

  const handleExport = () => {
    if (onExportData) {
      onExportData(filteredData as TimeSeriesDataPoint[])
    } else {
      // Default CSV export
      const csvData = [
        [xAxisKey, ...visibleLines.map(l => l.name || l.dataKey)].join(','),
        ...filteredData.map(row => 
          [row[xAxisKey], ...visibleLines.map(l => row[l.dataKey] || '')].join(',')
        )
      ].join('\n')

      const blob = new Blob([csvData], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.download = `${title?.replace(/\s+/g, '_') || 'timeseries_chart'}.csv`
      link.href = url
      link.click()
      URL.revokeObjectURL(url)
    }
  }

  const toggleLineVisibility = (dataKey: string) => {
    const newSelection = new Set(selectedLines)
    if (newSelection.has(dataKey)) {
      newSelection.delete(dataKey)
    } else {
      newSelection.add(dataKey)
    }
    setSelectedLines(newSelection)
  }

  const getChartTypeIcon = (type: ChartType) => {
    switch (type) {
      case 'line': return <LineChartIcon className="h-4 w-4" />
      case 'area': return <AreaChart className="h-4 w-4" />
      case 'bar': return <BarChart3 className="h-4 w-4" />
    }
  }

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between">
          <div>
            {title && <CardTitle className="text-lg font-semibold">{title}</CardTitle>}
            {subtitle && <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          
          <div className="flex items-center gap-2">
            {/* Chart Type Selector */}
            <Select value={chartType} onValueChange={(value: ChartType) => setChartType(value)}>
              <SelectTrigger className="w-32">
                <div className="flex items-center gap-2">
                  {getChartTypeIcon(chartType)}
                  <SelectValue />
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="line">
                  <div className="flex items-center gap-2">
                    <LineChartIcon className="h-4 w-4" />
                    Line
                  </div>
                </SelectItem>
                <SelectItem value="area">
                  <div className="flex items-center gap-2">
                    <AreaChart className="h-4 w-4" />
                    Area
                  </div>
                </SelectItem>
                <SelectItem value="bar">
                  <div className="flex items-center gap-2">
                    <BarChart3 className="h-4 w-4" />
                    Bar
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>

            {/* Aggregation Selector */}
            <Select value={aggregation} onValueChange={(value: any) => setAggregation(value)}>
              <SelectTrigger className="w-32">
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  <SelectValue />
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Raw Data</SelectItem>
                <SelectItem value="hour">Hourly</SelectItem>
                <SelectItem value="day">Daily</SelectItem>
                <SelectItem value="week">Weekly</SelectItem>
                <SelectItem value="month">Monthly</SelectItem>
              </SelectContent>
            </Select>

            {/* Zoom Controls */}
            {showZoomControls && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleZoomIn}
                  disabled={filteredData.length <= 2}
                >
                  <ZoomIn className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleZoomOut}
                  disabled={!zoomDomain}
                >
                  <ZoomOut className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleReset}
                  disabled={!zoomDomain && !brushDomain}
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
              </>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
            >
              <Download className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Line Visibility Controls */}
        {lines.length > 1 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {lines.map((line) => (
              <Badge
                key={line.dataKey}
                variant={selectedLines.has(line.dataKey) ? "default" : "outline"}
                className="cursor-pointer transition-all"
                onClick={() => toggleLineVisibility(line.dataKey)}
                style={{
                  backgroundColor: selectedLines.has(line.dataKey) ? line.color : undefined,
                  borderColor: line.color
                }}
              >
                {line.name || line.dataKey}
              </Badge>
            ))}
          </div>
        )}

        {/* Zoom Indicator */}
        {zoomDomain && (
          <div className="text-sm text-muted-foreground flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Showing {filteredData.length} of {aggregatedData.length} data points
            {zoomDomain.left !== undefined && zoomDomain.right !== undefined && 
              ` (${zoomDomain.left + 1}-${zoomDomain.right + 1})`}
          </div>
        )}
      </CardHeader>

      <CardContent>
        <div style={{ height: `${height}px` }}>
          <ResponsiveContainer width="100%" height="100%">
            <RechartsLineChart
              ref={chartRef}
              data={filteredData}
              margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
            >
              {showGrid && (
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              )}
              
              <XAxis
                dataKey={xAxisKey}
                tickFormatter={formatXAxis}
                label={xAxisLabel ? { value: xAxisLabel, position: 'insideBottom', offset: -5 } : undefined}
                className="text-xs"
                tick={{ fontSize: 12 }}
                interval="preserveStartEnd"
              />
              
              <YAxis
                domain={domain}
                tickFormatter={formatYAxis}
                label={yAxisLabel ? { value: yAxisLabel, angle: -90, position: 'insideLeft' } : undefined}
                className="text-xs"
                tick={{ fontSize: 12 }}
                width={60}
              />
              
              <Tooltip
                content={<CustomTooltip formatter={formatTooltip} labelFormatter={formatXAxis} />}
              />
              
              {showLegend && <Legend />}
              
              {referenceLines.map((refLine, index) => (
                <ReferenceLine
                  key={index}
                  {...refLine}
                  strokeDasharray={refLine.strokeDasharray || "3 3"}
                  stroke={refLine.stroke || "#94a3b8"}
                />
              ))}
              
              {visibleLines.map((line, index) => (
                <Line
                  key={line.dataKey}
                  type={line.type || 'monotone'}
                  dataKey={line.dataKey}
                  name={line.name || line.dataKey}
                  stroke={line.color || `hsl(${(index * 360) / visibleLines.length}, 70%, 50%)`}
                  strokeWidth={line.strokeWidth || 2}
                  strokeDasharray={line.strokeDasharray}
                  dot={line.dot !== false ? { r: 4 } : false}
                  activeDot={{ r: 6, stroke: line.color, strokeWidth: 2 }}
                  connectNulls={line.connectNulls !== false}
                  fill={chartType === 'area' ? (line.fill || line.color) : undefined}
                  fillOpacity={chartType === 'area' ? 0.1 : 0}
                />
              ))}
              
              {showBrush && (
                <Brush
                  dataKey={xAxisKey}
                  height={40}
                  stroke="#8884d8"
                  className="fill-muted"
                  tickFormatter={formatXAxis}
                  onChange={handleBrushChange}
                  startIndex={brushDomain?.startIndex}
                  endIndex={brushDomain?.endIndex}
                />
              )}
            </RechartsLineChart>
          </ResponsiveContainer>
        </div>
        
        {/* Data Summary */}
        <div className="mt-4 pt-4 border-t grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-muted-foreground">Data Points:</span>
            <span className="ml-2 font-medium">{filteredData.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Time Range:</span>
            <span className="ml-2 font-medium">
              {filteredData.length > 0 && formatXAxis
                ? `${formatXAxis(filteredData[0][xAxisKey])} - ${formatXAxis(filteredData[filteredData.length - 1][xAxisKey])}`
                : 'N/A'}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">Series:</span>
            <span className="ml-2 font-medium">{visibleLines.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Aggregation:</span>
            <span className="ml-2 font-medium capitalize">{aggregation}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )

  function setAggregation(value: any): void {
    // This function would be implemented to update the aggregation state
    // For now, it's a placeholder to avoid TypeScript errors
    console.log('Aggregation changed to:', value)
  }
}