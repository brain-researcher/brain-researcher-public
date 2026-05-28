'use client'

import React from 'react'
import {
  BarChart as RechartsBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  TooltipProps,
  Cell,
  LabelList,
  ReferenceLine,
} from 'recharts'
import { BaseChart, BaseChartProps } from './BaseChart'

export interface BarChartProps extends Omit<BaseChartProps, 'children'> {
  data: Array<Record<string, any>>
  bars: Array<{
    dataKey: string
    name?: string
    color?: string | ((entry: any, index: number) => string)
    stackId?: string
    showLabel?: boolean
    labelPosition?: 'top' | 'center' | 'inside' | 'insideTop' | 'insideBottom'
  }>
  xAxisKey: string
  xAxisLabel?: string
  yAxisLabel?: string
  showGrid?: boolean
  showLegend?: boolean
  showTooltip?: boolean
  orientation?: 'horizontal' | 'vertical'
  barSize?: number
  barGap?: number
  categoryGap?: number | string
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
  formatLabel?: (value: any) => string
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

export function BarChart({
  data,
  bars,
  xAxisKey,
  xAxisLabel,
  yAxisLabel,
  showGrid = true,
  showLegend = true,
  showTooltip = true,
  orientation = 'vertical',
  barSize,
  barGap = 4,
  categoryGap = '20%',
  referenceLines = [],
  domain,
  formatXAxis,
  formatYAxis,
  formatTooltip,
  formatLabel,
  onExportCSV,
  ...baseChartProps
}: BarChartProps) {
  const handleExportCSV = () => {
    const headers = [xAxisKey, ...bars.map(b => b.name || b.dataKey)]
    const csv = [
      headers.join(','),
      ...data.map(row =>
        headers.map(h => row[h === xAxisKey ? xAxisKey : bars.find(b => (b.name || b.dataKey) === h)?.dataKey || ''] || '').join(',')
      ),
    ].join('\n')

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${baseChartProps.exportFileName || 'bar-chart'}.csv`
    link.href = url
    link.click()
    URL.revokeObjectURL(url)
  }

  const isHorizontal = orientation === 'horizontal'

  return (
    <BaseChart {...baseChartProps} onExportCSV={onExportCSV || handleExportCSV}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsBarChart
          data={data}
          layout={isHorizontal ? 'horizontal' : 'vertical'}
          margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          barGap={barGap}
          barCategoryGap={categoryGap}
        >
          {showGrid && (
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          )}
          {isHorizontal ? (
            <>
              <XAxis
                type="number"
                domain={domain}
                tickFormatter={formatXAxis}
                label={xAxisLabel ? { value: xAxisLabel, position: 'insideBottom', offset: -5 } : undefined}
                className="text-xs"
              />
              <YAxis
                type="category"
                dataKey={xAxisKey}
                tickFormatter={formatYAxis}
                label={yAxisLabel ? { value: yAxisLabel, angle: -90, position: 'insideLeft' } : undefined}
                className="text-xs"
              />
            </>
          ) : (
            <>
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
            </>
          )}
          {showTooltip && (
            <Tooltip
              content={<CustomTooltip formatter={formatTooltip} />}
            />
          )}
          {showLegend && <Legend />}
          {referenceLines.map((refLine, index) => (
            <ReferenceLine
              key={index}
              {...refLine}
              strokeDasharray={refLine.strokeDasharray || "3 3"}
            />
          ))}
          {bars.map((bar, barIndex) => (
            <Bar
              key={bar.dataKey}
              dataKey={bar.dataKey}
              name={bar.name || bar.dataKey}
              stackId={bar.stackId}
              maxBarSize={barSize}
              fill={typeof bar.color === 'string' ? bar.color : `hsl(${(barIndex * 360) / bars.length}, 70%, 50%)`}
            >
              {typeof bar.color === 'function' &&
                data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={(bar.color as (entry: any, index: number) => string)(entry, index)} />
                ))}
              {bar.showLabel && (
                <LabelList
                  dataKey={bar.dataKey}
                  position={bar.labelPosition || 'top'}
                  formatter={formatLabel}
                />
              )}
            </Bar>
          ))}
        </RechartsBarChart>
      </ResponsiveContainer>
    </BaseChart>
  )
}