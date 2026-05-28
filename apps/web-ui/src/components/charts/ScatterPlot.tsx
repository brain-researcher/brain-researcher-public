'use client'

import React from 'react'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  TooltipProps,
  Cell,
  ReferenceLine,
  ReferenceArea,
  ZAxis,
} from 'recharts'
import { BaseChart, BaseChartProps } from './BaseChart'

export interface ScatterPlotProps extends Omit<BaseChartProps, 'children'> {
  data: Array<Record<string, any>> | Array<{ name: string; data: Array<Record<string, any>> }>
  scatters?: Array<{
    name: string
    dataKey?: string
    color?: string | ((entry: any, index: number) => string)
    shape?: 'circle' | 'cross' | 'diamond' | 'square' | 'star' | 'triangle' | 'wye'
    size?: number | ((entry: any) => number)
  }>
  xKey: string
  yKey: string
  zKey?: string // For bubble charts
  xAxisLabel?: string
  yAxisLabel?: string
  zAxisLabel?: string
  showGrid?: boolean
  showLegend?: boolean
  showTooltip?: boolean
  xDomain?: [number | 'auto', number | 'auto']
  yDomain?: [number | 'auto', number | 'auto']
  zDomain?: [number | 'auto', number | 'auto']
  formatXAxis?: (value: any) => string
  formatYAxis?: (value: any) => string
  formatTooltip?: (value: any, name: string) => string
  referenceLines?: Array<{
    y?: number
    x?: number
    label?: string
    stroke?: string
    strokeDasharray?: string
  }>
  referenceAreas?: Array<{
    x1?: number
    x2?: number
    y1?: number
    y2?: number
    fill?: string
    fillOpacity?: number
    label?: string
  }>
  trendline?: boolean | {
    stroke?: string
    strokeWidth?: number
    strokeDasharray?: string
  }
}

interface CustomScatterTooltipProps {
  active?: boolean
  payload?: Array<{ name?: string; payload?: any }>
  formatter?: (value: any, name: string) => string
  xKey: string
  yKey: string
  zKey?: string
  xAxisLabel?: string
  yAxisLabel?: string
  zAxisLabel?: string
}

const CustomTooltip = ({
  active,
  payload,
  formatter,
  xKey,
  yKey,
  zKey,
  xAxisLabel,
  yAxisLabel,
  zAxisLabel
}: CustomScatterTooltipProps) => {
  if (active && payload && payload.length > 0) {
    const data = payload[0].payload
    return (
      <div className="rounded-lg bg-background/95 p-3 shadow-lg border">
        {payload[0].name && (
          <p className="text-sm font-medium mb-2">{payload[0].name}</p>
        )}
        <p className="text-sm">
          {xAxisLabel || 'X'}: {formatter ? formatter(data[xKey], xKey) : data[xKey]}
        </p>
        <p className="text-sm">
          {yAxisLabel || 'Y'}: {formatter ? formatter(data[yKey], yKey) : data[yKey]}
        </p>
        {zKey && data[zKey] !== undefined && (
          <p className="text-sm">
            {zAxisLabel || 'Size'}: {formatter ? formatter(data[zKey], zKey) : data[zKey]}
          </p>
        )}
      </div>
    )
  }
  return null
}

function calculateTrendline(data: any[], xKey: string, yKey: string) {
  const n = data.length
  if (n < 2) return null

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0
  
  data.forEach(point => {
    const x = point[xKey]
    const y = point[yKey]
    sumX += x
    sumY += y
    sumXY += x * y
    sumX2 += x * x
  })

  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
  const intercept = (sumY - slope * sumX) / n

  const xMin = Math.min(...data.map(d => d[xKey]))
  const xMax = Math.max(...data.map(d => d[xKey]))

  return [
    { [xKey]: xMin, trendline: slope * xMin + intercept },
    { [xKey]: xMax, trendline: slope * xMax + intercept }
  ]
}

export function ScatterPlot({
  data,
  scatters = [],
  xKey,
  yKey,
  zKey,
  xAxisLabel,
  yAxisLabel,
  zAxisLabel,
  showGrid = true,
  showLegend = true,
  showTooltip = true,
  xDomain,
  yDomain,
  zDomain,
  formatXAxis,
  formatYAxis,
  formatTooltip,
  referenceLines = [],
  referenceAreas = [],
  trendline = false,
  onExportCSV,
  ...baseChartProps
}: ScatterPlotProps) {
  // Check if data is grouped or flat
  const isGrouped = Array.isArray(data) && data.length > 0 && 'name' in data[0] && 'data' in data[0]
  
  const handleExportCSV = () => {
    let csvData: string[][] = []
    
    if (isGrouped) {
      // For grouped data
      const headers = ['Group', xKey, yKey]
      if (zKey) headers.push(zKey)
      csvData.push(headers)
      
      ;(data as Array<{ name: string; data: Array<Record<string, any>> }>).forEach(group => {
        group.data.forEach(point => {
          const row = [group.name, point[xKey], point[yKey]]
          if (zKey) row.push(point[zKey])
          csvData.push(row)
        })
      })
    } else {
      // For flat data
      const headers = [xKey, yKey]
      if (zKey) headers.push(zKey)
      csvData.push(headers)
      
      ;(data as Array<Record<string, any>>).forEach(point => {
        const row = [point[xKey], point[yKey]]
        if (zKey) row.push(point[zKey])
        csvData.push(row)
      })
    }

    const csv = csvData.map(row => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${baseChartProps.exportFileName || 'scatter-plot'}.csv`
    link.href = url
    link.click()
    URL.revokeObjectURL(url)
  }

  // Calculate trendline data if needed
  const trendlineData = trendline && !isGrouped ? calculateTrendline(data as any[], xKey, yKey) : null

  return (
    <BaseChart {...baseChartProps} onExportCSV={onExportCSV || handleExportCSV}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 20, right: 30, left: 20, bottom: 20 }}>
          {showGrid && (
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          )}
          <XAxis
            type="number"
            dataKey={xKey}
            name={xAxisLabel || xKey}
            domain={xDomain}
            tickFormatter={formatXAxis}
            label={xAxisLabel ? { value: xAxisLabel, position: 'insideBottom', offset: -5 } : undefined}
            className="text-xs"
          />
          <YAxis
            type="number"
            dataKey={yKey}
            name={yAxisLabel || yKey}
            domain={yDomain}
            tickFormatter={formatYAxis}
            label={yAxisLabel ? { value: yAxisLabel, angle: -90, position: 'insideLeft' } : undefined}
            className="text-xs"
          />
          {zKey && (
            <ZAxis
              type="number"
              dataKey={zKey}
              domain={zDomain}
              name={zAxisLabel || zKey}
            />
          )}
          {showTooltip && (
            <Tooltip
              content={
                <CustomTooltip 
                  formatter={formatTooltip}
                  xKey={xKey}
                  yKey={yKey}
                  zKey={zKey}
                  xAxisLabel={xAxisLabel}
                  yAxisLabel={yAxisLabel}
                  zAxisLabel={zAxisLabel}
                />
              }
            />
          )}
          {showLegend && <Legend />}
          
          {referenceAreas.map((area, index) => (
            <ReferenceArea
              key={index}
              {...area}
            />
          ))}
          
          {referenceLines.map((refLine, index) => (
            <ReferenceLine
              key={index}
              {...refLine}
              strokeDasharray={refLine.strokeDasharray || "3 3"}
            />
          ))}
          
          {isGrouped ? (
            // Render grouped scatter plots
            (data as Array<{ name: string; data: Array<Record<string, any>> }>).map((group, index) => {
              const scatter = scatters[index] || {} as Partial<NonNullable<ScatterPlotProps['scatters']>[number]>
              return (
                <Scatter
                  key={group.name}
                  name={group.name}
                  data={group.data}
                  fill={typeof scatter.color === 'string' ? scatter.color : `hsl(${(index * 360) / (data as any[]).length}, 70%, 50%)`}
                  shape={scatter.shape}
                >
                  {typeof scatter.color === 'function' &&
                    group.data.map((entry, idx) => (
                      <Cell key={`cell-${idx}`} fill={(scatter.color as (entry: any, index: number) => string)(entry, idx)} />
                    ))}
                </Scatter>
              )
            })
          ) : (
            // Render single scatter plot
            <>
              <Scatter
                name={scatters[0]?.name || 'Data'}
                data={data as Array<Record<string, any>>}
                fill={typeof scatters[0]?.color === 'string' ? scatters[0].color : '#8884d8'}
                shape={scatters[0]?.shape}
              >
                {typeof scatters[0]?.color === 'function' &&
                  (data as Array<Record<string, any>>).map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={(scatters[0].color as (entry: any, index: number) => string)(entry, index)} />
                  ))}
              </Scatter>
              
              {trendline && trendlineData && (
                <Scatter
                  name="Trendline"
                  data={trendlineData}
                  fill="none"
                  line={{ 
                    stroke: typeof trendline === 'object' ? trendline.stroke : '#ff7300',
                    strokeWidth: typeof trendline === 'object' ? trendline.strokeWidth : 2,
                    strokeDasharray: typeof trendline === 'object' ? trendline.strokeDasharray : undefined
                  }}
                  shape={() => null}
                />
              )}
            </>
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </BaseChart>
  )
}