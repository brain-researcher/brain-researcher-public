'use client'

import React from 'react'
import { cn } from '@/lib/utils'

interface ShimmerEffectProps {
  width?: string | number
  height?: string | number
  className?: string
  variant?: 'wave' | 'pulse' | 'shimmer' | 'skeleton'
  speed?: 'slow' | 'normal' | 'fast'
  direction?: 'left-to-right' | 'right-to-left' | 'top-to-bottom'
  intensity?: 'subtle' | 'medium' | 'strong'
  baseColor?: string
  highlightColor?: string
  borderRadius?: 'none' | 'sm' | 'md' | 'lg' | 'full'
  children?: React.ReactNode
}

export function ShimmerEffect({
  width = '100%',
  height = '1rem',
  className = '',
  variant = 'shimmer',
  speed = 'normal',
  direction = 'left-to-right',
  intensity = 'medium',
  baseColor,
  highlightColor,
  borderRadius = 'sm',
  children
}: ShimmerEffectProps) {
  const getVariantClasses = () => {
    const baseClasses = {
      'wave': 'bg-gradient-to-r animate-shimmer bg-[length:200%_100%]',
      'pulse': 'animate-pulse',
      'shimmer': 'bg-gradient-to-r animate-shimmer bg-[length:200%_100%]',
      'skeleton': 'animate-pulse'
    }

    return baseClasses[variant] || baseClasses.shimmer
  }

  const getSpeedClasses = () => {
    const speedMap = {
      'slow': 'animate-[shimmer_3s_linear_infinite]',
      'normal': 'animate-[shimmer_2s_linear_infinite]',
      'fast': 'animate-[shimmer_1s_linear_infinite]'
    }
    
    if (variant === 'pulse') {
      return {
        'slow': 'animate-[pulse_3s_ease-in-out_infinite]',
        'normal': 'animate-pulse',
        'fast': 'animate-[pulse_1s_ease-in-out_infinite]'
      }[speed] || 'animate-pulse'
    }

    return speedMap[speed] || speedMap.normal
  }

  const getDirectionClasses = () => {
    const directionMap = {
      'left-to-right': 'bg-gradient-to-r',
      'right-to-left': 'bg-gradient-to-l', 
      'top-to-bottom': 'bg-gradient-to-b'
    }
    
    return directionMap[direction] || directionMap['left-to-right']
  }

  const getIntensityColors = () => {
    const colors = {
      baseColors: {
        subtle: baseColor || 'from-muted/50 via-muted/30 to-muted/50',
        medium: baseColor || 'from-muted via-muted/50 to-muted',
        strong: baseColor || 'from-muted/80 via-muted/20 to-muted/80'
      },
      highlightColors: {
        subtle: highlightColor || 'via-background/80',
        medium: highlightColor || 'via-background',
        strong: highlightColor || 'via-background/60'
      }
    }

    if (variant === 'pulse') {
      return {
        subtle: 'bg-muted/50',
        medium: 'bg-muted',
        strong: 'bg-muted/80'
      }[intensity] || 'bg-muted'
    }

    return colors.baseColors[intensity] || colors.baseColors.medium
  }

  const getBorderRadiusClasses = () => {
    const radiusMap = {
      'none': 'rounded-none',
      'sm': 'rounded-sm',
      'md': 'rounded-md',
      'lg': 'rounded-lg',
      'full': 'rounded-full'
    }
    
    return radiusMap[borderRadius] || radiusMap.sm
  }

  const shimmerClasses = cn(
    getVariantClasses(),
    getSpeedClasses(),
    getDirectionClasses(),
    getIntensityColors(),
    getBorderRadiusClasses(),
    className
  )

  const style: React.CSSProperties = {
    width: typeof width === 'number' ? `${width}px` : width,
    height: typeof height === 'number' ? `${height}px` : height,
  }

  if (children) {
    return (
      <div className={cn("relative overflow-hidden", getBorderRadiusClasses())} style={style}>
        {children}
        <div 
          className={cn(
            "absolute inset-0",
            shimmerClasses
          )}
        />
      </div>
    )
  }

  return (
    <div
      className={shimmerClasses}
      style={style}
      role="status"
      aria-label="Loading content..."
    />
  )
}

// Shimmer Wrapper - wraps content with shimmer overlay
export function ShimmerWrapper({
  children,
  isLoading = true,
  className = '',
  shimmerProps = {}
}: {
  children: React.ReactNode
  isLoading?: boolean
  className?: string
  shimmerProps?: Partial<ShimmerEffectProps>
}) {
  if (!isLoading) {
    return <>{children}</>
  }

  return (
    <div className={cn("relative", className)}>
      <div className={isLoading ? "opacity-30" : "opacity-100"}>
        {children}
      </div>
      {isLoading && (
        <ShimmerEffect
          className="absolute inset-0"
          {...shimmerProps}
        />
      )}
    </div>
  )
}

// Pre-configured shimmer variants for common use cases
export function ShimmerCard({
  className = '',
  showImage = true,
  showActions = true,
  ...props
}: Partial<ShimmerEffectProps> & {
  showImage?: boolean
  showActions?: boolean
}) {
  return (
    <div className={cn("bg-card rounded-lg border p-6 space-y-4", className)}>
      {showImage && (
        <ShimmerEffect
          height="12rem"
          variant="shimmer"
          borderRadius="md"
          {...props}
        />
      )}
      <div className="space-y-2">
        <ShimmerEffect
          height="1.25rem"
          width="75%"
          variant="shimmer"
          {...props}
        />
        <ShimmerEffect
          height="1rem"
          width="50%"
          variant="shimmer"
          {...props}
        />
      </div>
      <div className="space-y-2">
        <ShimmerEffect height="0.75rem" variant="shimmer" {...props} />
        <ShimmerEffect height="0.75rem" width="90%" variant="shimmer" {...props} />
        <ShimmerEffect height="0.75rem" width="60%" variant="shimmer" {...props} />
      </div>
      {showActions && (
        <div className="flex gap-2 pt-2">
          <ShimmerEffect
            width="5rem"
            height="2rem"
            variant="shimmer"
            borderRadius="md"
            {...props}
          />
          <ShimmerEffect
            width="5rem"
            height="2rem"
            variant="shimmer"
            borderRadius="md"
            {...props}
          />
        </div>
      )}
    </div>
  )
}

export function ShimmerTable({
  rows = 5,
  columns = 4,
  showHeader = true,
  className = '',
  ...props
}: Partial<ShimmerEffectProps> & {
  rows?: number
  columns?: number
  showHeader?: boolean
}) {
  return (
    <div className={cn("bg-card rounded-lg border overflow-hidden", className)}>
      {showHeader && (
        <div className="bg-muted/50 px-6 py-3 border-b border-border">
          <div className="flex gap-4">
            {Array.from({ length: columns }).map((_, i) => (
              <ShimmerEffect
                key={i}
                width="6rem"
                height="1.25rem"
                variant="shimmer"
                {...props}
              />
            ))}
          </div>
        </div>
      )}
      <div className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div key={rowIndex} className="px-6 py-4">
            <div className="flex gap-4">
              {Array.from({ length: columns }).map((_, colIndex) => (
                <ShimmerEffect
                  key={colIndex}
                  width={colIndex === 0 ? "9rem" : "6rem"}
                  height="1rem"
                  variant="shimmer"
                  {...props}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function ShimmerList({
  items = 3,
  showAvatar = true,
  variant = 'default',
  className = '',
  ...props
}: Omit<Partial<ShimmerEffectProps>, 'variant'> & {
  items?: number
  showAvatar?: boolean
  variant?: 'default' | 'compact' | 'detailed'
}) {
  const getItemHeight = () => {
    switch (variant) {
      case 'compact': return 'py-2'
      case 'detailed': return 'py-6'
      default: return 'py-4'
    }
  }

  return (
    <div className={cn("space-y-1", className)}>
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className={cn("flex items-start gap-4", getItemHeight())}>
          {showAvatar && (
            <ShimmerEffect
              width={variant === 'compact' ? '2rem' : '2.5rem'}
              height={variant === 'compact' ? '2rem' : '2.5rem'}
              variant="shimmer"
              borderRadius="full"
              {...props}
            />
          )}
          <div className="flex-1 space-y-2">
            <ShimmerEffect
              height="1rem"
              width={`${60 + Math.random() * 30}%`}
              variant="shimmer"
              {...props}
            />
            {variant !== 'compact' && (
              <ShimmerEffect
                height="0.75rem"
                width={`${40 + Math.random() * 40}%`}
                variant="shimmer"
                {...props}
              />
            )}
            {variant === 'detailed' && (
              <>
                <ShimmerEffect height="0.75rem" width="90%" variant="shimmer" {...props} />
                <ShimmerEffect height="0.75rem" width="70%" variant="shimmer" {...props} />
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ShimmerChart({
  type = 'bar',
  showLegend = true,
  className = '',
  ...props
}: Partial<ShimmerEffectProps> & {
  type?: 'bar' | 'line' | 'pie' | 'area'
  showLegend?: boolean
}) {
  return (
    <div className={cn("bg-card rounded-lg border p-6", className)}>
      <div className="space-y-4">
        <ShimmerEffect
          height="1.5rem"
          width="40%"
          variant="shimmer"
          {...props}
        />
        <div className="relative">
          {type === 'pie' ? (
            <ShimmerEffect
              width="12.5rem"
              height="12.5rem"
              variant="shimmer"
              borderRadius="full"
              className="mx-auto"
              {...props}
            />
          ) : (
            <ShimmerEffect
              height="15.625rem"
              variant="shimmer"
              borderRadius="md"
              {...props}
            />
          )}
        </div>
        {showLegend && (
          <div className="flex justify-center gap-6">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-2">
                <ShimmerEffect
                  width="0.75rem"
                  height="0.75rem"
                  variant="shimmer"
                  borderRadius="sm"
                  {...props}
                />
                <ShimmerEffect
                  width="3.75rem"
                  height="0.75rem"
                  variant="shimmer"
                  {...props}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Shimmer Text Block
export function ShimmerText({
  lines = 3,
  className = '',
  ...props
}: Partial<ShimmerEffectProps> & {
  lines?: number
}) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <ShimmerEffect
          key={i}
          height="1rem"
          width={i === lines - 1 ? `${50 + Math.random() * 25}%` : `${85 + Math.random() * 15}%`}
          variant="shimmer"
          {...props}
        />
      ))}
    </div>
  )
}

// Default export
export default ShimmerEffect