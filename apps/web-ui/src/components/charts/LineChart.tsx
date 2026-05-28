'use client'

import React from 'react'
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
} from 'recharts'
import { BaseChart, BaseChartProps } from './BaseChart'
import { cn } from '@/lib/utils'

export interface LineChartProps extends Omit<BaseChartProps, 'children'> {
  data: Array<Record<string, any>>
  lines: Array<{
    dataKey: string
    name?: string
    color?: string
    strokeWidth?: number
    strokeDasharray?: string
    dot?: boolean
    activeDot?: boolean | object
  }>
  xAxisKey: string
  xAxisLabel?: string
  yAxisLabel?: string
  showGrid?: boolean
  showLegend?: boolean
  showTooltip?: boolean
  showBrush?: boolean
  referenceLines?: Array<{
    y?: number
    x?: string | number
    label?: string
    stroke?: string
    strokeDasharray?: string
  }>
  domain?: [number | 'auto', number | 'auto']
  formatXAxis?: (value: any) => string
  formatYAxis?: (value: any) => string
  formatTooltip?: (value: any, name: string) => string
  curveType?: 'basis' | 'basisClosed' | 'basisOpen' | 'linear' | 'linearClosed' | 'natural' | 'monotoneX' | 'monotoneY' | 'monotone' | 'step' | 'stepBefore' | 'stepAfter'
}

interface CustomTooltipProps {
  active?: boolean
  payload?: Array<{ name?: string; value?: any; color?: string }>
  label?: string
  formatter?: (value: any, name: string) => string
}

const CustomTooltip = ({ active, payload, label, formatter }: CustomTooltipProps) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg bg-background/95 p-3 shadow-lg border">
        <p className="text-sm font-medium mb-2">{label}</p>
        {payload.map((entry, index) => (
          <p key={index} className="text-sm" style={{ color: entry.color }}>
            {entry.name}: {formatter ? formatter(entry.value, entry.name || '') : entry.value}
          </p>
        ))}
      </div>
    )
  }
  return null
}

export function LineChart({
  data,
  lines,
  xAxisKey,
  xAxisLabel,
  yAxisLabel,
  showGrid = true,
  showLegend = true,
  showTooltip = true,
  showBrush = false,
  referenceLines = [],
  domain,
  formatXAxis,
  formatYAxis,
  formatTooltip,
  curveType = 'monotone',
  onExportCSV,
  ...baseChartProps
}: LineChartProps) {
  const handleExportCSV = () => {
    const headers = [xAxisKey, ...lines.map(l => l.name || l.dataKey)]
    const csv = [
      headers.join(','),
      ...data.map(row =>
        headers.map(h => row[h === xAxisKey ? xAxisKey : lines.find(l => (l.name || l.dataKey) === h)?.dataKey || ''] || '').join(',')
      ),
    ].join('\n')

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${baseChartProps.exportFileName || 'line-chart'}.csv`
    link.href = url
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <BaseChart {...baseChartProps} onExportCSV={onExportCSV || handleExportCSV}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsLineChart
          data={data}
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
          />
          <YAxis
            domain={domain}
            tickFormatter={formatYAxis}
            label={yAxisLabel ? { value: yAxisLabel, angle: -90, position: 'insideLeft' } : undefined}
            className="text-xs"
          />
          {showTooltip && (
            <Tooltip
              content={<CustomTooltip formatter={formatTooltip} />}
            />
          )}
          {showLegend && <Legend />}
          {showBrush && (
            <Brush
              dataKey={xAxisKey}
              height={30}
              stroke="#8884d8"
              className="fill-muted"
            />
          )}
          {referenceLines.map((refLine, index) => (
            <ReferenceLine
              key={index}
              {...refLine}
              strokeDasharray={refLine.strokeDasharray || "3 3"}
            />
          ))}
          {lines.map((line, index) => (
            <Line
              key={line.dataKey}
              type={curveType}
              dataKey={line.dataKey}
              name={line.name || line.dataKey}
              stroke={line.color || `hsl(${(index * 360) / lines.length}, 70%, 50%)`}
              strokeWidth={line.strokeWidth || 2}
              strokeDasharray={line.strokeDasharray}
              dot={line.dot !== false}
              activeDot={line.activeDot !== false ? (line.activeDot || { r: 8 }) : false}
            />
          ))}
        </RechartsLineChart>
      </ResponsiveContainer>
    </BaseChart>
  )
}