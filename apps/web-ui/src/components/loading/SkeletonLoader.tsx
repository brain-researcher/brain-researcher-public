'use client'

import React from 'react'
import { cn } from '@/lib/utils'

interface SkeletonProps {
  className?: string
  variant?: 'text' | 'circular' | 'rectangular' | 'rounded'
  width?: string | number
  height?: string | number
  animation?: 'pulse' | 'wave' | 'none'
  'aria-label'?: string
}

export function Skeleton({
  className = '',
  variant = 'text',
  width,
  height,
  animation = 'pulse',
  'aria-label': ariaLabel = 'Loading content...'
}: SkeletonProps) {
  const getVariantClass = () => {
    switch (variant) {
      case 'circular':
        return 'rounded-full'
      case 'rounded':
        return 'rounded-lg'
      case 'rectangular':
        return 'rounded-none'
      case 'text':
      default:
        return 'rounded h-4'
    }
  }

  const getAnimationClass = () => {
    switch (animation) {
      case 'wave':
        return 'animate-shimmer bg-gradient-to-r from-muted via-muted/50 to-muted bg-[length:200%_100%]'
      case 'pulse':
        return 'animate-pulse bg-muted'
      case 'none':
      default:
        return 'bg-muted'
    }
  }

  const style: React.CSSProperties = {
    width: width || '100%',
    height: height || (variant === 'text' ? '1rem' : undefined)
  }

  return (
    <div 
      className={cn(getVariantClass(), getAnimationClass(), className)}
      style={style}
      aria-label={ariaLabel}
      role="status"
      aria-live="polite"
    />
  )
}

// Card Skeleton with enhanced accessibility
export function CardSkeleton({ 
  count = 1, 
  showImage = true,
  showActions = true,
  className = ''
}: { 
  count?: number
  showImage?: boolean
  showActions?: boolean
  className?: string
}) {
  return (
    <div className={cn("space-y-4", className)} role="status" aria-label={`Loading ${count} card${count === 1 ? '' : 's'}...`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-card rounded-lg shadow-sm border p-6">
          <div className="space-y-3">
            {showImage && (
              <Skeleton variant="rectangular" height={200} className="mb-4" aria-label="Loading image..." />
            )}
            <Skeleton variant="text" className="h-6 mb-2" width="75%" aria-label="Loading title..." />
            <Skeleton variant="text" className="h-4 mb-2" width="50%" aria-label="Loading subtitle..." />
            <div className="space-y-2">
              <Skeleton variant="text" className="h-3" aria-label="Loading description..." />
              <Skeleton variant="text" className="h-3" width="85%" />
              <Skeleton variant="text" className="h-3" width="60%" />
            </div>
            {showActions && (
              <div className="flex gap-2 pt-4">
                <Skeleton variant="rounded" width={80} height={32} aria-label="Loading action button..." />
                <Skeleton variant="rounded" width={80} height={32} aria-label="Loading action button..." />
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// Table Skeleton with accessibility
export function TableSkeleton({ 
  rows = 5, 
  columns = 4,
  showHeader = true,
  className = ''
}: { 
  rows?: number
  columns?: number
  showHeader?: boolean
  className?: string
}) {
  return (
    <div 
      className={cn("bg-card rounded-lg shadow-sm border overflow-hidden", className)}
      role="status" 
      aria-label={`Loading table with ${rows} rows and ${columns} columns...`}
    >
      {/* Header */}
      {showHeader && (
        <div className="bg-muted/50 px-6 py-3 border-b border-border">
          <div className="flex gap-4">
            {Array.from({ length: columns }).map((_, i) => (
              <Skeleton key={i} variant="text" width={100} className="h-5" aria-label={`Loading column ${i + 1} header...`} />
            ))}
          </div>
        </div>
      )}
      
      {/* Rows */}
      <div className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div key={rowIndex} className="px-6 py-4">
            <div className="flex gap-4">
              {Array.from({ length: columns }).map((_, colIndex) => (
                <Skeleton 
                  key={colIndex} 
                  variant="text" 
                  width={colIndex === 0 ? 150 : 100} 
                  className="h-4"
                  aria-label={`Loading row ${rowIndex + 1}, column ${colIndex + 1}...`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// List Skeleton
export function ListSkeleton({ 
  items = 3,
  showAvatar = true,
  variant = 'default',
  className = ''
}: { 
  items?: number
  showAvatar?: boolean
  variant?: 'default' | 'compact' | 'detailed'
  className?: string
}) {
  const getItemHeight = () => {
    switch (variant) {
      case 'compact': return 'py-2'
      case 'detailed': return 'py-6'
      default: return 'py-4'
    }
  }

  return (
    <div 
      className={cn("space-y-1", className)} 
      role="status" 
      aria-label={`Loading ${items} list item${items === 1 ? '' : 's'}...`}
    >
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className={cn("flex items-start gap-4", getItemHeight())}>
          {showAvatar && (
            <Skeleton variant="circular" width={variant === 'compact' ? 32 : 40} height={variant === 'compact' ? 32 : 40} />
          )}
          <div className="flex-1 space-y-2">
            <Skeleton variant="text" className="h-4" width={`${60 + Math.random() * 30}%`} />
            {variant !== 'compact' && (
              <Skeleton variant="text" className="h-3" width={`${40 + Math.random() * 40}%`} />
            )}
            {variant === 'detailed' && (
              <>
                <Skeleton variant="text" className="h-3" width="90%" />
                <Skeleton variant="text" className="h-3" width="70%" />
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// Chart Skeleton
export function ChartSkeleton({ 
  type = 'bar',
  showLegend = true,
  className = ''
}: { 
  type?: 'bar' | 'line' | 'pie' | 'area'
  showLegend?: boolean
  className?: string
}) {
  return (
    <div 
      className={cn("bg-card rounded-lg shadow-sm border p-6", className)}
      role="status" 
      aria-label={`Loading ${type} chart...`}
    >
      <div className="space-y-4">
        <Skeleton variant="text" className="h-6" width="40%" aria-label="Loading chart title..." />
        <div className="relative">
          {type === 'pie' ? (
            <Skeleton variant="circular" width={200} height={200} className="mx-auto" />
          ) : (
            <Skeleton variant="rectangular" height={250} className="mb-4" />
          )}
        </div>
        {showLegend && (
          <div className="flex justify-center gap-6">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-2">
                <Skeleton variant="rectangular" width={12} height={12} />
                <Skeleton variant="text" width={60} className="h-3" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Text Content Skeleton
export function TextSkeleton({ 
  lines = 5,
  variant = 'paragraph',
  className = ''
}: { 
  lines?: number
  variant?: 'paragraph' | 'article' | 'list'
  className?: string
}) {
  return (
    <div 
      className={cn("bg-card rounded-lg border p-6", className)}
      role="status" 
      aria-label={`Loading text content with ${lines} lines...`}
    >
      <div className="space-y-3">
        {variant === 'article' && (
          <Skeleton variant="text" className="h-8 mb-4" width="70%" aria-label="Loading article title..." />
        )}
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton
            key={i}
            variant="text"
            className="h-4"
            width={
              variant === 'list' 
                ? `${70 + Math.random() * 20}%`
                : i === lines - 1 
                  ? `${50 + Math.random() * 25}%` 
                  : `${85 + Math.random() * 15}%`
            }
          />
        ))}
      </div>
    </div>
  )
}

// Navigation Skeleton
export function NavigationSkeleton({ 
  items = 5,
  orientation = 'horizontal',
  className = ''
}: {
  items?: number
  orientation?: 'horizontal' | 'vertical'
  className?: string
}) {
  return (
    <div 
      className={cn(
        "space-y-2",
        orientation === 'horizontal' ? "flex space-y-0 space-x-4" : "",
        className
      )}
      role="status"
      aria-label={`Loading navigation with ${items} items...`}
    >
      {Array.from({ length: items }).map((_, i) => (
        <Skeleton 
          key={i} 
          variant="rounded" 
          width={orientation === 'horizontal' ? 80 : '100%'} 
          height={36} 
        />
      ))}
    </div>
  )
}

// Form Skeleton
export function FormSkeleton({ 
  fields = 4,
  showSubmitButton = true,
  className = ''
}: {
  fields?: number
  showSubmitButton?: boolean
  className?: string
}) {
  return (
    <div 
      className={cn("bg-card rounded-lg border p-6", className)}
      role="status"
      aria-label={`Loading form with ${fields} fields...`}
    >
      <div className="space-y-6">
        {Array.from({ length: fields }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton variant="text" width={120} className="h-4" />
            <Skeleton variant="rounded" height={40} />
          </div>
        ))}
        {showSubmitButton && (
          <div className="pt-4">
            <Skeleton variant="rounded" width={120} height={40} />
          </div>
        )}
      </div>
    </div>
  )
}

// Default export
export default Skeleton