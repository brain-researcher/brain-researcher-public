'use client'

import React, { useEffect, useRef, useMemo } from 'react'
import * as d3 from 'd3'
import { BaseChart, BaseChartProps } from './BaseChart'

export interface HeatmapProps extends Omit<BaseChartProps, 'children'> {
  data: Array<{
    x: string | number
    y: string | number
    value: number
  }>
  xLabels?: (string | number)[]
  yLabels?: (string | number)[]
  xAxisLabel?: string
  yAxisLabel?: string
  valueLabel?: string
  colorScheme?: 'blues' | 'reds' | 'greens' | 'purples' | 'oranges' | 'greys' | 'viridis' | 'plasma' | 'inferno' | 'magma' | 'cividis' | 'warm' | 'cool' | 'rainbow'
  showValues?: boolean
  formatValue?: (value: number) => string
  formatTooltip?: (d: { x: string | number; y: string | number; value: number }) => string
  minValue?: number
  maxValue?: number
  cellBorderColor?: string
  cellBorderWidth?: number
  margin?: { top: number; right: number; bottom: number; left: number }
}

export function Heatmap({
  data,
  xLabels,
  yLabels,
  xAxisLabel,
  yAxisLabel,
  valueLabel = 'Value',
  colorScheme = 'blues',
  showValues = false,
  formatValue = (v) => v.toFixed(2),
  formatTooltip,
  minValue,
  maxValue,
  cellBorderColor = '#fff',
  cellBorderWidth = 1,
  margin = { top: 50, right: 80, bottom: 80, left: 80 },
  height = 400,
  onExportCSV,
  ...baseChartProps
}: HeatmapProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  const xDomain = useMemo(() => {
    if (xLabels) return xLabels
    return Array.from(new Set(data.map(d => d.x))).sort()
  }, [data, xLabels])

  const yDomain = useMemo(() => {
    if (yLabels) return yLabels
    return Array.from(new Set(data.map(d => d.y))).sort()
  }, [data, yLabels])

  const handleExportCSV = () => {
    const headers = ['', ...xDomain]
    const rows = yDomain.map(y => {
      const row = [y]
      xDomain.forEach(x => {
        const cell = data.find(d => d.x === x && d.y === y)
        row.push(cell ? cell.value.toString() : '')
      })
      return row.join(',')
    })
    const csv = [headers.join(','), ...rows].join('\n')

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `${baseChartProps.exportFileName || 'heatmap'}.csv`
    link.href = url
    link.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    if (!svgRef.current) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth
    const effectiveHeight = typeof height === 'number' ? height : 400
    const innerWidth = width - margin.left - margin.right
    const innerHeight = effectiveHeight - margin.top - margin.bottom

    const g = svg
      .attr('width', width)
      .attr('height', effectiveHeight)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    // Create scales
    const xScale = d3.scaleBand()
      .domain(xDomain.map(String))
      .range([0, innerWidth])
      .padding(0.05)

    const yScale = d3.scaleBand()
      .domain(yDomain.map(String))
      .range([0, innerHeight])
      .padding(0.05)

    // Color scale
    const dataMin = minValue ?? d3.min(data, d => d.value) ?? 0
    const dataMax = maxValue ?? d3.max(data, d => d.value) ?? 1

    let colorScale: d3.ScaleSequential<string>
    switch (colorScheme) {
      case 'reds': colorScale = d3.scaleSequential(d3.interpolateReds); break
      case 'greens': colorScale = d3.scaleSequential(d3.interpolateGreens); break
      case 'purples': colorScale = d3.scaleSequential(d3.interpolatePurples); break
      case 'oranges': colorScale = d3.scaleSequential(d3.interpolateOranges); break
      case 'greys': colorScale = d3.scaleSequential(d3.interpolateGreys); break
      case 'viridis': colorScale = d3.scaleSequential(d3.interpolateViridis); break
      case 'plasma': colorScale = d3.scaleSequential(d3.interpolatePlasma); break
      case 'inferno': colorScale = d3.scaleSequential(d3.interpolateInferno); break
      case 'magma': colorScale = d3.scaleSequential(d3.interpolateMagma); break
      case 'cividis': colorScale = d3.scaleSequential(d3.interpolateCividis); break
      case 'warm': colorScale = d3.scaleSequential(d3.interpolateWarm); break
      case 'cool': colorScale = d3.scaleSequential(d3.interpolateCool); break
      case 'rainbow': colorScale = d3.scaleSequential(d3.interpolateRainbow); break
      default: colorScale = d3.scaleSequential(d3.interpolateBlues); break
    }
    colorScale.domain([dataMin, dataMax])

    // Create tooltip
    const tooltip = d3.select(tooltipRef.current)
      .style('position', 'absolute')
      .style('visibility', 'hidden')
      .style('background-color', 'hsl(var(--background))')
      .style('border', '1px solid hsl(var(--border))')
      .style('border-radius', '6px')
      .style('padding', '8px')
      .style('font-size', '12px')
      .style('pointer-events', 'none')
      .style('z-index', '10')

    // Draw cells
    const cells = g.selectAll('rect')
      .data(data)
      .enter()
      .append('rect')
      .attr('x', d => xScale(String(d.x)) ?? 0)
      .attr('y', d => yScale(String(d.y)) ?? 0)
      .attr('width', xScale.bandwidth())
      .attr('height', yScale.bandwidth())
      .style('fill', d => colorScale(d.value))
      .style('stroke', cellBorderColor)
      .style('stroke-width', cellBorderWidth)
      .on('mouseover', function(event, d) {
        tooltip.style('visibility', 'visible')
        const content = formatTooltip 
          ? formatTooltip(d)
          : `${xAxisLabel || 'X'}: ${d.x}<br/>${yAxisLabel || 'Y'}: ${d.y}<br/>${valueLabel}: ${formatValue(d.value)}`
        tooltip.html(content)
      })
      .on('mousemove', function(event) {
        tooltip
          .style('left', (event.pageX + 10) + 'px')
          .style('top', (event.pageY - 10) + 'px')
      })
      .on('mouseout', function() {
        tooltip.style('visibility', 'hidden')
      })

    // Add value labels if requested
    if (showValues) {
      g.selectAll('text.value')
        .data(data)
        .enter()
        .append('text')
        .attr('class', 'value')
        .attr('x', d => (xScale(String(d.x)) ?? 0) + xScale.bandwidth() / 2)
        .attr('y', d => (yScale(String(d.y)) ?? 0) + yScale.bandwidth() / 2)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .style('fill', d => {
          const luminance = d3.rgb(colorScale(d.value)).darker(2)
          return luminance.formatHex()
        })
        .style('font-size', '10px')
        .text(d => formatValue(d.value))
    }

    // Add X axis
    const xAxis = g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(xScale))

    xAxis.selectAll('text')
      .style('text-anchor', 'end')
      .attr('dx', '-.8em')
      .attr('dy', '.15em')
      .attr('transform', 'rotate(-45)')

    if (xAxisLabel) {
      xAxis.append('text')
        .attr('x', innerWidth / 2)
        .attr('y', 60)
        .attr('fill', 'currentColor')
        .style('text-anchor', 'middle')
        .text(xAxisLabel)
    }

    // Add Y axis
    const yAxis = g.append('g')
      .call(d3.axisLeft(yScale))

    if (yAxisLabel) {
      yAxis.append('text')
        .attr('transform', 'rotate(-90)')
        .attr('y', -50)
        .attr('x', -innerHeight / 2)
        .attr('fill', 'currentColor')
        .style('text-anchor', 'middle')
        .text(yAxisLabel)
    }

    // Add color legend
    const legendWidth = 20
    const legendHeight = innerHeight

    const legendScale = d3.scaleLinear()
      .domain([dataMax, dataMin])
      .range([0, legendHeight])

    const legendAxis = d3.axisRight(legendScale)
      .ticks(5)
      .tickFormat(d => formatValue(d as number))

    const legend = g.append('g')
      .attr('transform', `translate(${innerWidth + 20}, 0)`)

    // Create gradient for legend
    const gradientId = `gradient-${Math.random().toString(36).substr(2, 9)}`
    const gradient = svg.append('defs')
      .append('linearGradient')
      .attr('id', gradientId)
      .attr('x1', '0%')
      .attr('x2', '0%')
      .attr('y1', '0%')
      .attr('y2', '100%')

    const nStops = 20
    for (let i = 0; i <= nStops; i++) {
      const offset = i / nStops
      const value = dataMax - (dataMax - dataMin) * offset
      gradient.append('stop')
        .attr('offset', `${offset * 100}%`)
        .attr('stop-color', colorScale(value))
    }

    legend.append('rect')
      .attr('width', legendWidth)
      .attr('height', legendHeight)
      .style('fill', `url(#${gradientId})`)

    legend.append('g')
      .attr('transform', `translate(${legendWidth}, 0)`)
      .call(legendAxis)

  }, [data, xDomain, yDomain, colorScheme, showValues, formatValue, formatTooltip, minValue, maxValue, cellBorderColor, cellBorderWidth, margin, height, xAxisLabel, yAxisLabel, valueLabel])

  return (
    <BaseChart {...baseChartProps} onExportCSV={onExportCSV || handleExportCSV} height={height}>
      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
        <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
        <div ref={tooltipRef} />
      </div>
    </BaseChart>
  )
}