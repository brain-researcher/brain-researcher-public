'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { X, Loader2, AlertTriangle, Pause, Play, Square } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ProgressIndicator, CircularProgress } from './ProgressIndicator'
import { createPortal } from 'react-dom'

interface LoadingOverlayProps {
  visible: boolean
  message?: string
  description?: string
  progress?: number
  stage?: string
  variant?: 'spinner' | 'progress' | 'circular' | 'minimal'
  size?: 'sm' | 'md' | 'lg'
  blur?: boolean
  fullScreen?: boolean
  blocking?: boolean
  cancellable?: boolean
  pauseable?: boolean
  showElapsedTime?: boolean
  estimatedTimeRemaining?: number
  className?: string
  onCancel?: () => void
  onPause?: () => void
  onResume?: () => void
  children?: React.ReactNode
}

export function LoadingOverlay({
  visible,
  message = 'Loading...',
  description,
  progress,
  stage,
  variant = 'spinner',
  size = 'md',
  blur = true,
  fullScreen = false,
  blocking = true,
  cancellable = false,
  pauseable = false,
  showElapsedTime = false,
  estimatedTimeRemaining,
  className = '',
  onCancel,
  onPause,
  onResume,
  children
}: LoadingOverlayProps) {
  const [startTime] = useState(Date.now())
  const [elapsedTime, setElapsedTime] = useState(0)
  const [isPaused, setIsPaused] = useState(false)
  const [mounted, setMounted] = useState(false)

  // Track elapsed time
  useEffect(() => {
    if (!visible || isPaused) return

    const interval = setInterval(() => {
      setElapsedTime(Date.now() - startTime)
    }, 1000)

    return () => clearInterval(interval)
  }, [visible, isPaused, startTime])

  // Handle mount for portal
  useEffect(() => {
    setMounted(true)
  }, [])

  const handlePause = useCallback(() => {
    setIsPaused(true)
    onPause?.()
  }, [onPause])

  const handleResume = useCallback(() => {
    setIsPaused(false)
    onResume?.()
  }, [onResume])

  const handleCancel = useCallback(() => {
    onCancel?.()
  }, [onCancel])

  const getSizeClasses = () => {
    const sizes = {
      sm: { container: 'p-4', spinner: 'w-4 h-4', text: 'text-sm' },
      md: { container: 'p-6', spinner: 'w-6 h-6', text: 'text-base' },
      lg: { container: 'p-8', spinner: 'w-8 h-8', text: 'text-lg' }
    }
    return sizes[size] || sizes.md
  }

  const formatTime = (ms: number) => {
    const seconds = Math.floor(ms / 1000)
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const renderLoadingContent = () => {
    const sizeClasses = getSizeClasses()

    const loadingIcon = () => {
      switch (variant) {
        case 'circular':
          return (
            <CircularProgress
              value={progress}
              size={size === 'sm' ? 32 : size === 'lg' ? 64 : 48}
              indeterminate={progress === undefined}
              showPercentage={progress !== undefined}
            />
          )
        case 'minimal':
          return null
        default:
          return (
            <Loader2 
              className={cn(
                "animate-spin text-primary",
                isPaused && "animate-none",
                sizeClasses.spinner
              )} 
            />
          )
      }
    }

    return (
      <div className={cn(
        "bg-card border shadow-lg rounded-lg flex flex-col items-center max-w-md w-full mx-4",
        sizeClasses.container
      )}>
        {/* Header with controls */}
        <div className="flex items-center justify-between w-full mb-4">
          <div className="flex items-center gap-2">
            {loadingIcon()}
            <div className="text-left">
              <h3 className={cn("font-semibold text-card-foreground", sizeClasses.text)}>
                {isPaused ? 'Paused' : message}
              </h3>
              {stage && (
                <p className="text-sm text-muted-foreground">{stage}</p>
              )}
            </div>
          </div>

          {/* Control buttons */}
          <div className="flex items-center gap-1">
            {pauseable && (onPause || onResume) && (
              <button
                onClick={isPaused ? handleResume : handlePause}
                className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                title={isPaused ? 'Resume' : 'Pause'}
              >
                {isPaused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
              </button>
            )}

            {cancellable && onCancel && (
              <button
                onClick={handleCancel}
                className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md transition-colors"
                title="Cancel"
              >
                <Square className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Progress indicator */}
        {variant === 'progress' && (
          <div className="w-full mb-4">
            <ProgressIndicator
              value={progress}
              message={description}
              stage={stage}
              showPercentage
              estimatedTimeRemaining={estimatedTimeRemaining}
              indeterminate={progress === undefined}
            />
          </div>
        )}

        {/* Description */}
        {description && variant !== 'progress' && (
          <p className="text-sm text-muted-foreground text-center mb-4">
            {description}
          </p>
        )}

        {/* Time information */}
        {showElapsedTime && (
          <div className="text-xs text-muted-foreground">
            Elapsed: {formatTime(elapsedTime)}
          </div>
        )}

        {/* Custom children content */}
        {children && (
          <div className="mt-4 w-full">
            {children}
          </div>
        )}
      </div>
    )
  }

  if (!visible || !mounted) return null

  const overlayContent = (
    <div
      className={cn(
        "flex items-center justify-center z-50",
        fullScreen ? "fixed inset-0" : "absolute inset-0",
        blur ? "backdrop-blur-sm" : "",
        blocking ? "bg-background/80" : "bg-transparent pointer-events-none",
        className
      )}
      role={blocking ? "dialog" : undefined}
      aria-modal={blocking}
      aria-label={message}
      aria-live="polite"
    >
      <div className={blocking ? "" : "pointer-events-auto"}>
        {renderLoadingContent()}
      </div>
    </div>
  )

  // Use portal for full screen overlays
  if (fullScreen && typeof window !== 'undefined') {
    return createPortal(overlayContent, document.body)
  }

  return overlayContent
}

// Simple loading spinner
export function LoadingSpinner({
  size = 'md',
  variant = 'default',
  className = '',
  'aria-label': ariaLabel = 'Loading...'
}: {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  variant?: 'default' | 'primary' | 'muted' | 'destructive'
  className?: string
  'aria-label'?: string
}) {
  const sizeClasses = {
    xs: 'w-3 h-3',
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
    xl: 'w-12 h-12'
  }

  const variantClasses = {
    default: 'text-foreground',
    primary: 'text-primary',
    muted: 'text-muted-foreground',
    destructive: 'text-destructive'
  }

  return (
    <Loader2
      className={cn(
        'animate-spin',
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
      aria-label={ariaLabel}
      role="status"
    />
  )
}

// Button with loading state
export function LoadingButton({
  children,
  loading = false,
  disabled = false,
  loadingText,
  variant = 'default',
  size = 'md',
  className = '',
  onClick,
  ...props
}: {
  children: React.ReactNode
  loading?: boolean
  disabled?: boolean
  loadingText?: string
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
  size?: 'sm' | 'md' | 'lg'
  className?: string
  onClick?: () => void
  [key: string]: any
}) {
  const baseClasses = "inline-flex items-center justify-center rounded-md font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
  
  const variantClasses = {
    default: "bg-primary text-primary-foreground hover:bg-primary/90",
    destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
    outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
    secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
    ghost: "hover:bg-accent hover:text-accent-foreground",
    link: "text-primary underline-offset-4 hover:underline"
  }
  
  const sizeClasses = {
    sm: "h-9 rounded-md px-3 text-xs",
    md: "h-10 px-4 py-2",
    lg: "h-11 rounded-md px-8 text-base"
  }

  return (
    <button
      className={cn(
        baseClasses,
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      disabled={disabled || loading}
      onClick={onClick}
      {...props}
    >
      {loading && (
        <LoadingSpinner 
          size={size === 'sm' ? 'xs' : 'sm'} 
          variant="primary" 
          className="mr-2" 
        />
      )}
      {loading && loadingText ? loadingText : children}
    </button>
  )
}

// Page loading overlay
export function PageLoadingOverlay({
  visible,
  message = 'Loading page...',
  className = ''
}: {
  visible: boolean
  message?: string
  className?: string
}) {
  if (!visible) return null

  return (
    <LoadingOverlay
      visible={visible}
      message={message}
      variant="spinner"
      fullScreen
      blur
      blocking
      className={className}
    />
  )
}

// Section loading overlay
export function SectionLoadingOverlay({
  visible,
  message = 'Loading...',
  className = ''
}: {
  visible: boolean
  message?: string
  className?: string
}) {
  return (
    <LoadingOverlay
      visible={visible}
      message={message}
      variant="minimal"
      size="sm"
      blur={false}
      blocking={false}
      className={cn("bg-background/60", className)}
    />
  )
}

// Error overlay
export function ErrorOverlay({
  visible,
  title = 'Something went wrong',
  message,
  onRetry,
  onDismiss,
  className = ''
}: {
  visible: boolean
  title?: string
  message?: string
  onRetry?: () => void
  onDismiss?: () => void
  className?: string
}) {
  if (!visible) return null

  return (
    <div
      className={cn(
        "absolute inset-0 flex items-center justify-center z-50 bg-background/80 backdrop-blur-sm",
        className
      )}
      role="dialog"
      aria-modal
      aria-labelledby="error-title"
    >
      <div className="bg-card border border-destructive/50 shadow-lg rounded-lg p-6 max-w-md w-full mx-4">
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-destructive mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <h3 id="error-title" className="font-semibold text-card-foreground mb-1">
              {title}
            </h3>
            {message && (
              <p className="text-sm text-muted-foreground">
                {message}
              </p>
            )}
          </div>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="p-1 text-muted-foreground hover:text-foreground rounded-md"
              title="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {onRetry && (
          <div className="flex justify-end gap-2">
            <LoadingButton
              onClick={onRetry}
              variant="default"
              size="sm"
            >
              Try Again
            </LoadingButton>
          </div>
        )}
      </div>
    </div>
  )
}

// Default export
export default LoadingOverlay