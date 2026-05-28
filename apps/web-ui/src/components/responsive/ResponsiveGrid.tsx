'use client'

import React from 'react'
import { cn } from '@/lib/utils'

// Mobile-first breakpoint system as specified
export const MOBILE_FIRST_BREAKPOINTS = {
  mobile: 320,   // Mobile phones
  tablet: 768,   // Tablets
  desktop: 1024, // Desktop
  wide: 1440     // Wide screens
} as const

export type BreakpointName = keyof typeof MOBILE_FIRST_BREAKPOINTS

interface GridBreakpoints {
  mobile?: number
  tablet?: number  
  desktop?: number
  wide?: number
}

interface ResponsiveGridProps {
  cols?: GridBreakpoints
  gap?: number | string | GridBreakpoints
  children: React.ReactNode
  className?: string
  autoFit?: boolean
  minItemWidth?: string
  aspectRatio?: string
}

/**
 * Responsive Grid System with mobile-first approach
 * Breakpoints: 320px (mobile), 768px (tablet), 1024px (desktop), 1440px (wide)
 */
export function ResponsiveGrid({
  cols = { mobile: 1, tablet: 2, desktop: 3, wide: 4 },
  gap = 16,
  children,
  className,
  autoFit = false,
  minItemWidth = '300px',
  aspectRatio
}: ResponsiveGridProps) {
  
  // Generate responsive grid template columns
  const getGridTemplateColumns = () => {
    if (autoFit) {
      return `repeat(auto-fit, minmax(${minItemWidth}, 1fr))`
    }
    
    // Mobile-first responsive columns
    let styles = ''
    
    if (cols.mobile) {
      styles += `repeat(${cols.mobile}, 1fr)`
    }
    
    return styles
  }

  // Generate responsive gap styles
  const getGapStyles = () => {
    if (typeof gap === 'object') {
      return {
        gap: gap.mobile ? `${gap.mobile}px` : '16px'
      }
    }
    return {
      gap: typeof gap === 'number' ? `${gap}px` : gap
    }
  }

  // Generate responsive CSS classes for breakpoints
  const getResponsiveClasses = () => {
    const classes: string[] = []
    
    // Base mobile styles
    if (cols.mobile) {
      classes.push(`grid-cols-${cols.mobile}`)
    }
    
    // Tablet styles
    if (cols.tablet) {
      classes.push(`md:grid-cols-${cols.tablet}`)
    }
    
    // Desktop styles  
    if (cols.desktop) {
      classes.push(`lg:grid-cols-${cols.desktop}`)
    }
    
    // Wide screen styles
    if (cols.wide) {
      classes.push(`xl:grid-cols-${cols.wide}`)
    }
    
    return classes.join(' ')
  }

  const gridStyles: React.CSSProperties = {
    display: 'grid',
    ...getGapStyles(),
    ...(aspectRatio && { gridAutoRows: `minmax(0, 1fr)` }),
    ...(autoFit && { gridTemplateColumns: getGridTemplateColumns() })
  }

  const baseClasses = cn(
    'responsive-grid',
    !autoFit && getResponsiveClasses(),
    aspectRatio && 'grid-auto-rows-fr',
    className
  )

  return (
    <div
      className={baseClasses}
      style={gridStyles}
      data-testid="responsive-grid"
    >
      {aspectRatio 
        ? React.Children.map(children, (child, index) => (
            <div key={index} style={{ aspectRatio }} className="overflow-hidden">
              {child}
            </div>
          ))
        : children
      }
    </div>
  )
}

/**
 * Auto-fit grid that creates responsive columns based on item width
 */
export function AutoFitGrid({
  minItemWidth = '280px',
  maxItemWidth = '400px', 
  gap = 16,
  children,
  className,
  aspectRatio
}: {
  minItemWidth?: string
  maxItemWidth?: string
  gap?: number | string
  children: React.ReactNode
  className?: string
  aspectRatio?: string
}) {
  return (
    <ResponsiveGrid
      gap={gap}
      autoFit
      minItemWidth={`min(${minItemWidth}, 100%)`}
      aspectRatio={aspectRatio}
      className={className}
    >
      {children}
    </ResponsiveGrid>
  )
}

/**
 * Masonry-style grid for variable height content
 */
export function MasonryGrid({
  columns = { mobile: 1, tablet: 2, desktop: 3, wide: 4 },
  gap = 16,
  children,
  className
}: {
  columns?: GridBreakpoints
  gap?: number
  children: React.ReactNode
  className?: string
}) {
  const childArray = React.Children.toArray(children)
  
  const getColumnCount = () => {
    // Default to mobile column count, will be overridden by CSS
    return columns.mobile || 1
  }

  const distributeItems = (columnCount: number) => {
    const columnsArray: React.ReactNode[][] = Array.from({ length: columnCount }, () => [])
    
    childArray.forEach((child, index) => {
      const columnIndex = index % columnCount
      columnsArray[columnIndex].push(child)
    })
    
    return columnsArray
  }

  const baseColumnCount = getColumnCount()
  const distributedItems = distributeItems(baseColumnCount)

  const masonryStyles: React.CSSProperties = {
    columnCount: baseColumnCount,
    columnGap: `${gap}px`,
    columnFill: 'balance'
  }

  return (
    <div
      className={cn(
        'masonry-grid',
        // Responsive column counts using CSS
        columns.mobile && `columns-${columns.mobile}`,
        columns.tablet && `md:columns-${columns.tablet}`,
        columns.desktop && `lg:columns-${columns.desktop}`,
        columns.wide && `xl:columns-${columns.wide}`,
        className
      )}
      style={masonryStyles}
      data-testid="masonry-grid"
    >
      {childArray.map((child, index) => (
        <div
          key={index}
          className="break-inside-avoid mb-4"
          style={{ breakInside: 'avoid', pageBreakInside: 'avoid' }}
        >
          {child}
        </div>
      ))}
    </div>
  )
}

/**
 * Flex-based responsive grid alternative
 */
export function FlexGrid({
  minItemWidth = '300px',
  gap = 16,
  children,
  className,
  justify = 'start'
}: {
  minItemWidth?: string
  gap?: number
  children: React.ReactNode
  className?: string
  justify?: 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly'
}) {
  const flexStyles: React.CSSProperties = {
    display: 'flex',
    flexWrap: 'wrap',
    gap: `${gap}px`,
    justifyContent: justify === 'start' ? 'flex-start' : 
                   justify === 'end' ? 'flex-end' :
                   justify === 'between' ? 'space-between' :
                   justify === 'around' ? 'space-around' :
                   justify === 'evenly' ? 'space-evenly' : 'center'
  }

  return (
    <div 
      className={cn('flex-grid', className)}
      style={flexStyles}
      data-testid="flex-grid"
    >
      {React.Children.map(children, (child, index) => (
        <div
          key={index}
          style={{ 
            flex: `1 1 ${minItemWidth}`,
            minWidth: minItemWidth,
            maxWidth: '100%'
          }}
        >
          {child}
        </div>
      ))}
    </div>
  )
}

// Export grid variants for convenience
export const GridVariants = {
  ResponsiveGrid,
  AutoFitGrid,
  MasonryGrid,
  FlexGrid
}

export default ResponsiveGrid