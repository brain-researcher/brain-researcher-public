'use client'

import React from 'react'
import { Loader2 } from 'lucide-react'

// Skeleton Loader Component
interface SkeletonProps {
  className?: string
  variant?: 'text' | 'circular' | 'rectangular' | 'rounded'
  width?: string | number
  height?: string | number
  animation?: 'pulse' | 'wave' | 'none'
}

export function Skeleton({
  className = '',
  variant = 'text',
  width,
  height,
  animation = 'pulse'
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
        return 'animate-shimmer bg-gradient-to-r from-gray-200 via-gray-100 to-gray-200 dark:from-gray-800 dark:via-gray-700 dark:to-gray-800 bg-[length:200%_100%]'
      case 'pulse':
        return 'animate-pulse bg-gray-200 dark:bg-gray-700'
      case 'none':
      default:
        return 'bg-gray-200 dark:bg-gray-700'
    }
  }

  const style: React.CSSProperties = {
    width: width || '100%',
    height: height || (variant === 'text' ? '1rem' : undefined)
  }

  return (
    <div 
      className={`${getVariantClass()} ${getAnimationClass()} ${className}`}
      style={style}
    />
  )
}

// Card Skeleton
export function CardSkeleton() {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6">
      <Skeleton variant="rectangular" height={200} className="mb-4" />
      <Skeleton variant="text" className="mb-2" />
      <Skeleton variant="text" width="60%" className="mb-4" />
      <div className="flex gap-2">
        <Skeleton variant="rounded" width={80} height={32} />
        <Skeleton variant="rounded" width={80} height={32} />
      </div>
    </div>
  )
}

// Table Skeleton
export function TableSkeleton({ rows = 5, columns = 4 }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex gap-4">
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={i} variant="text" width={100} />
          ))}
        </div>
      </div>
      <div className="divide-y divide-gray-200 dark:divide-gray-700">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div key={rowIndex} className="px-6 py-4">
            <div className="flex gap-4">
              {Array.from({ length: columns }).map((_, colIndex) => (
                <Skeleton 
                  key={colIndex} 
                  variant="text" 
                  width={colIndex === 0 ? 150 : 100} 
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
export function ListSkeleton({ items = 3 }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="flex items-start gap-4">
          <Skeleton variant="circular" width={40} height={40} />
          <div className="flex-1">
            <Skeleton variant="text" className="mb-2" />
            <Skeleton variant="text" width="80%" />
          </div>
        </div>
      ))}
    </div>
  )
}

// Spinner Component
interface SpinnerProps {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  color?: 'primary' | 'secondary' | 'white' | 'current'
  className?: string
}

export function Spinner({ 
  size = 'md', 
  color = 'primary',
  className = '' 
}: SpinnerProps) {
  const sizeClasses = {
    xs: 'h-3 w-3',
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
    xl: 'h-12 w-12'
  }

  const colorClasses = {
    primary: 'text-blue-500',
    secondary: 'text-gray-500',
    white: 'text-white',
    current: 'text-current'
  }

  return (
    <Loader2 
      className={`animate-spin ${sizeClasses[size]} ${colorClasses[color]} ${className}`} 
    />
  )
}

// Loading Overlay
interface LoadingOverlayProps {
  visible: boolean
  message?: string
  blur?: boolean
  fullScreen?: boolean
}

export function LoadingOverlay({ 
  visible, 
  message = 'Loading...', 
  blur = true,
  fullScreen = false 
}: LoadingOverlayProps) {
  if (!visible) return null

  return (
    <div className={`${fullScreen ? 'fixed' : 'absolute'} inset-0 z-50 flex items-center justify-center ${blur ? 'backdrop-blur-sm' : ''} bg-black/20`}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 flex flex-col items-center">
        <Spinner size="lg" />
        {message && (
          <p className="mt-4 text-gray-700 dark:text-gray-300 font-medium">
            {message}
          </p>
        )}
      </div>
    </div>
  )
}

// Progress Bar
interface ProgressBarProps {
  value: number
  max?: number
  label?: string
  showPercentage?: boolean
  color?: 'blue' | 'green' | 'red' | 'yellow'
  size?: 'sm' | 'md' | 'lg'
  animated?: boolean
}

export function ProgressBar({
  value,
  max = 100,
  label,
  showPercentage = true,
  color = 'blue',
  size = 'md',
  animated = true
}: ProgressBarProps) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100))
  
  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    red: 'bg-red-500',
    yellow: 'bg-yellow-500'
  }
  
  const sizeClasses = {
    sm: 'h-1',
    md: 'h-2',
    lg: 'h-4'
  }

  return (
    <div className="w-full">
      {(label || showPercentage) && (
        <div className="flex justify-between mb-1">
          {label && (
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {label}
            </span>
          )}
          {showPercentage && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {Math.round(percentage)}%
            </span>
          )}
        </div>
      )}
      <div className={`w-full bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden ${sizeClasses[size]}`}>
        <div
          className={`${colorClasses[color]} ${sizeClasses[size]} transition-all duration-300 ${animated ? 'animate-pulse' : ''}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
}

// Dots Loader
export function DotsLoader({ color = 'primary' }: { color?: 'primary' | 'white' }) {
  const dotColor = color === 'white' ? 'bg-white' : 'bg-blue-500'
  
  return (
    <div className="flex space-x-1">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={`w-2 h-2 ${dotColor} rounded-full animate-bounce`}
          style={{ animationDelay: `${i * 0.1}s` }}
        />
      ))}
    </div>
  )
}

// Content Loader (for lazy loading)
interface ContentLoaderProps {
  isLoading: boolean
  error?: Error | null
  children: React.ReactNode
  loader?: React.ReactNode
  errorFallback?: React.ReactNode
  retry?: () => void
}

export function ContentLoader({
  isLoading,
  error,
  children,
  loader,
  errorFallback,
  retry
}: ContentLoaderProps) {
  if (error) {
    return (
      <>
        {errorFallback || (
          <div className="flex flex-col items-center justify-center p-8">
            <p className="text-red-600 mb-4">Failed to load content</p>
            {retry && (
              <button
                onClick={retry}
                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </>
    )
  }

  if (isLoading) {
    return <>{loader || <Spinner size="lg" />}</>
  }

  return <>{children}</>
}

// Add shimmer animation to tailwind (add to global CSS)
const shimmerStyle = `
@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

.animate-shimmer {
  animation: shimmer 2s linear infinite;
}
`

// Export all components
const loadingStatesExports = {
  Skeleton,
  CardSkeleton,
  TableSkeleton,
  ListSkeleton,
  Spinner,
  LoadingOverlay,
  ProgressBar,
  DotsLoader,
  ContentLoader
}

export default loadingStatesExports
