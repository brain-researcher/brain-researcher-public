'use client'

import React, { useEffect, useState } from 'react'
import { Clock, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ProgressIndicatorProps {
  value?: number
  max?: number
  label?: string
  message?: string
  stage?: string
  variant?: 'default' | 'success' | 'error' | 'warning'
  size?: 'sm' | 'md' | 'lg'
  showPercentage?: boolean
  showTimeEstimate?: boolean
  estimatedTimeRemaining?: number
  indeterminate?: boolean
  animated?: boolean
  className?: string
  'aria-label'?: string
}

export function ProgressIndicator({
  value = 0,
  max = 100,
  label,
  message,
  stage,
  variant = 'default',
  size = 'md',
  showPercentage = true,
  showTimeEstimate = false,
  estimatedTimeRemaining,
  indeterminate = false,
  animated = true,
  className = '',
  'aria-label': ariaLabel
}: ProgressIndicatorProps) {
  const [displayValue, setDisplayValue] = useState(0)
  
  // Smooth progress animation
  useEffect(() => {
    if (!indeterminate && animated) {
      const timer = setTimeout(() => {
        setDisplayValue(value)
      }, 50)
      return () => clearTimeout(timer)
    } else {
      setDisplayValue(value)
    }
  }, [value, indeterminate, animated])

  const percentage = Math.min(max, Math.max(0, (displayValue / max) * 100))
  
  const getSizeClasses = () => {
    switch (size) {
      case 'sm': return { bar: 'h-1', text: 'text-xs' }
      case 'lg': return { bar: 'h-4', text: 'text-base' }
      default: return { bar: 'h-2', text: 'text-sm' }
    }
  }

  const getVariantClasses = () => {
    switch (variant) {
      case 'success':
        return {
          bar: 'bg-green-500',
          track: 'bg-green-100 dark:bg-green-900/20',
          text: 'text-green-700 dark:text-green-300'
        }
      case 'error':
        return {
          bar: 'bg-red-500',
          track: 'bg-red-100 dark:bg-red-900/20',
          text: 'text-red-700 dark:text-red-300'
        }
      case 'warning':
        return {
          bar: 'bg-yellow-500',
          track: 'bg-yellow-100 dark:bg-yellow-900/20',
          text: 'text-yellow-700 dark:text-yellow-300'
        }
      default:
        return {
          bar: 'bg-primary',
          track: 'bg-muted',
          text: 'text-muted-foreground'
        }
    }
  }

  const formatTime = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.round(seconds % 60)
    return `${minutes}m ${remainingSeconds}s`
  }

  const sizeClasses = getSizeClasses()
  const variantClasses = getVariantClasses()

  const progressLabel = ariaLabel || 
    `${label || 'Progress'}: ${Math.round(percentage)}% ${stage ? `- ${stage}` : ''}`

  return (
    <div className={cn("w-full space-y-2", className)} role="progressbar" aria-label={progressLabel}>
      {/* Header with label and percentage */}
      {(label || showPercentage || stage) && (
        <div className="flex justify-between items-center">
          <div className="flex flex-col">
            {label && (
              <span className={cn("font-medium", variantClasses.text, sizeClasses.text)}>
                {label}
              </span>
            )}
            {stage && (
              <span className={cn("opacity-75", variantClasses.text, sizeClasses.text)}>
                {stage}
              </span>
            )}
          </div>
          {showPercentage && !indeterminate && (
            <span className={cn("font-mono tabular-nums", variantClasses.text, sizeClasses.text)}>
              {Math.round(percentage)}%
            </span>
          )}
        </div>
      )}

      {/* Progress bar */}
      <div className={cn("w-full rounded-full overflow-hidden", variantClasses.track, sizeClasses.bar)}>
        <div
          className={cn(
            "transition-all duration-300 ease-out rounded-full",
            variantClasses.bar,
            sizeClasses.bar,
            indeterminate && 'animate-pulse'
          )}
          style={{ 
            width: indeterminate ? '100%' : `${percentage}%`,
            transform: indeterminate ? 'translateX(-100%)' : 'none',
            animation: indeterminate 
              ? 'indeterminate-progress 1.5s cubic-bezier(0.65, 0.815, 0.735, 0.395) infinite' 
              : undefined
          }}
        />
      </div>

      {/* Message */}
      {message && (
        <p className={cn("leading-5", variantClasses.text, sizeClasses.text)}>
          {message}
        </p>
      )}

      {/* Time estimate */}
      {showTimeEstimate && estimatedTimeRemaining && !indeterminate && (
        <div className={cn("flex items-center gap-1", variantClasses.text, sizeClasses.text)}>
          <Clock className="w-3 h-3" />
          <span>About {formatTime(estimatedTimeRemaining)} remaining</span>
        </div>
      )}
    </div>
  )
}

// Circular Progress Indicator
export function CircularProgress({
  value = 0,
  max = 100,
  size = 64,
  strokeWidth = 4,
  variant = 'default',
  showPercentage = true,
  indeterminate = false,
  className = ''
}: {
  value?: number
  max?: number
  size?: number
  strokeWidth?: number
  variant?: 'default' | 'success' | 'error' | 'warning'
  showPercentage?: boolean
  indeterminate?: boolean
  className?: string
}) {
  const percentage = Math.min(max, Math.max(0, (value / max) * 100))
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const strokeDasharray = circumference
  const strokeDashoffset = indeterminate ? 0 : circumference - (percentage / 100) * circumference

  const getVariantColor = () => {
    switch (variant) {
      case 'success': return 'stroke-green-500'
      case 'error': return 'stroke-red-500'
      case 'warning': return 'stroke-yellow-500'
      default: return 'stroke-primary'
    }
  }

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="transform -rotate-90"
      >
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="none"
          className="text-muted opacity-20"
        />
        
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={strokeDasharray}
          strokeDashoffset={strokeDashoffset}
          className={cn(
            "transition-all duration-300 ease-out",
            getVariantColor(),
            indeterminate && "animate-spin"
          )}
          style={{
            strokeDasharray: indeterminate ? `${circumference * 0.25} ${circumference}` : strokeDasharray
          }}
        />
      </svg>
      
      {/* Center content */}
      {showPercentage && !indeterminate && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-semibold">
            {Math.round(percentage)}%
          </span>
        </div>
      )}
      
      {indeterminate && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="w-4 h-4 animate-spin" />
        </div>
      )}
    </div>
  )
}

// Multi-step Progress Indicator
export function StepProgress({
  steps,
  currentStep,
  variant = 'default',
  orientation = 'horizontal',
  showLabels = true,
  className = ''
}: {
  steps: Array<{ label: string; description?: string }>
  currentStep: number
  variant?: 'default' | 'success' | 'error' | 'warning'
  orientation?: 'horizontal' | 'vertical'
  showLabels?: boolean
  className?: string
}) {
  const getStepStatus = (stepIndex: number) => {
    if (stepIndex < currentStep) return 'completed'
    if (stepIndex === currentStep) return 'current'
    return 'pending'
  }

  const getVariantClasses = () => {
    switch (variant) {
      case 'success': return { active: 'bg-green-500 border-green-500 text-white', inactive: 'bg-green-100 border-green-200' }
      case 'error': return { active: 'bg-red-500 border-red-500 text-white', inactive: 'bg-red-100 border-red-200' }
      case 'warning': return { active: 'bg-yellow-500 border-yellow-500 text-white', inactive: 'bg-yellow-100 border-yellow-200' }
      default: return { active: 'bg-primary border-primary text-primary-foreground', inactive: 'bg-muted border-border' }
    }
  }

  const variantClasses = getVariantClasses()

  return (
    <div
      className={cn(
        "flex",
        orientation === 'vertical' ? "flex-col space-y-4" : "items-center space-x-4",
        className
      )}
    >
      {steps.map((step, index) => {
        const status = getStepStatus(index)
        const isCompleted = status === 'completed'
        const isCurrent = status === 'current'

        return (
          <div
            key={index}
            className={cn(
              "flex items-center",
              orientation === 'vertical' ? "w-full" : "flex-col"
            )}
          >
            {/* Step circle */}
            <div className="relative flex items-center">
              <div
                className={cn(
                  "w-8 h-8 rounded-full border-2 flex items-center justify-center text-sm font-medium transition-colors",
                  isCompleted || isCurrent 
                    ? variantClasses.active 
                    : variantClasses.inactive
                )}
              >
                {isCompleted ? (
                  <CheckCircle className="w-4 h-4" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              
              {/* Connector line */}
              {index < steps.length - 1 && (
                <div
                  className={cn(
                    "flex-1 h-0.5",
                    orientation === 'vertical' 
                      ? "absolute top-8 left-4 w-0.5 h-8 -translate-x-0.5" 
                      : "w-16 ml-2",
                    isCompleted ? variantClasses.active : variantClasses.inactive
                  )}
                />
              )}
            </div>

            {/* Step label */}
            {showLabels && (
              <div className={cn(
                "text-center",
                orientation === 'vertical' ? "ml-4 text-left flex-1" : "mt-2"
              )}>
                <div className={cn(
                  "text-sm font-medium",
                  isCurrent ? "text-foreground" : "text-muted-foreground"
                )}>
                  {step.label}
                </div>
                {step.description && (
                  <div className="text-xs text-muted-foreground mt-1">
                    {step.description}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Progress with stages
export function StagedProgress({
  stages,
  currentStage,
  progress,
  showOverallProgress = true,
  className = ''
}: {
  stages: Array<{ name: string; weight: number }>
  currentStage: number
  progress: number
  showOverallProgress?: boolean
  className?: string
}) {
  const totalWeight = stages.reduce((sum, stage) => sum + stage.weight, 0)
  const completedWeight = stages.slice(0, currentStage).reduce((sum, stage) => sum + stage.weight, 0)
  const currentStageWeight = stages[currentStage]?.weight || 0
  const overallProgress = ((completedWeight + (progress * currentStageWeight / 100)) / totalWeight) * 100

  return (
    <div className={cn("space-y-4", className)}>
      {showOverallProgress && (
        <ProgressIndicator
          value={overallProgress}
          label="Overall Progress"
          showPercentage
        />
      )}
      
      <div className="space-y-2">
        {stages.map((stage, index) => {
          const isCompleted = index < currentStage
          const isCurrent = index === currentStage
          const stageProgress = isCompleted ? 100 : isCurrent ? progress : 0

          return (
            <div key={index} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span className={cn(
                  isCurrent ? "font-medium text-foreground" : "text-muted-foreground"
                )}>
                  {stage.name}
                </span>
                <span className="text-muted-foreground">
                  {Math.round(stageProgress)}%
                </span>
              </div>
              <div className="w-full bg-muted rounded-full h-1">
                <div
                  className={cn(
                    "h-1 rounded-full transition-all duration-300",
                    isCompleted ? "bg-green-500" : isCurrent ? "bg-primary" : "bg-muted"
                  )}
                  style={{ width: `${stageProgress}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Add indeterminate animation keyframes to global CSS
const indeterminateKeyframes = `
@keyframes indeterminate-progress {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}
`

// Default export
export default ProgressIndicator