'use client'

import React, { useRef, useCallback } from 'react'
import { toPng, toSvg } from 'html-to-image'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Download, MoreVertical } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface BaseChartProps {
  title?: string
  description?: string
  children: React.ReactNode
  className?: string
  exportFileName?: string
  onExportCSV?: () => void
  showExportMenu?: boolean
  height?: number | string
}

export function BaseChart({
  title,
  description,
  children,
  className,
  exportFileName = 'chart',
  onExportCSV,
  showExportMenu = true,
  height,
}: BaseChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)

  const handleExportPNG = useCallback(async () => {
    if (chartRef.current === null) return

    try {
      const dataUrl = await toPng(chartRef.current, {
        cacheBust: true,
        backgroundColor: '#ffffff',
      })
      const link = document.createElement('a')
      link.download = `${exportFileName}.png`
      link.href = dataUrl
      link.click()
    } catch (err) {
      console.error('Failed to export PNG:', err)
    }
  }, [exportFileName])

  const handleExportSVG = useCallback(async () => {
    if (chartRef.current === null) return

    try {
      const dataUrl = await toSvg(chartRef.current, {
        cacheBust: true,
      })
      const link = document.createElement('a')
      link.download = `${exportFileName}.svg`
      link.href = dataUrl
      link.click()
    } catch (err) {
      console.error('Failed to export SVG:', err)
    }
  }, [exportFileName])

  return (
    <div 
      className={cn('relative rounded-lg border bg-card p-4', className)}
    >
      {(title || showExportMenu) && (
        <div className="mb-4 flex items-start justify-between">
          <div>
            {title && (
              <h3 className="text-lg font-semibold">{title}</h3>
            )}
            {description && (
              <p className="text-sm text-muted-foreground mt-1">
                {description}
              </p>
            )}
          </div>
          {showExportMenu && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={handleExportPNG}>
                  <Download className="mr-2 h-4 w-4" />
                  Export as PNG
                </DropdownMenuItem>
                <DropdownMenuItem onClick={handleExportSVG}>
                  <Download className="mr-2 h-4 w-4" />
                  Export as SVG
                </DropdownMenuItem>
                {onExportCSV && (
                  <DropdownMenuItem onClick={onExportCSV}>
                    <Download className="mr-2 h-4 w-4" />
                    Export as CSV
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      )}
      <div
        ref={chartRef}
        className="w-full"
        style={{ height: height ? (typeof height === 'number' ? `${height}px` : height) : 'auto' }}
      >
        {children}
      </div>
    </div>
  )
}