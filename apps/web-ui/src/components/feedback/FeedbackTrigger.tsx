'use client'

import React, { useState } from 'react'
import { MessageSquare, Plus, Zap, Bug, Lightbulb, Palette } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { FeedbackTriggerProps } from '@/types/feedback'
import { useFeedback } from '@/hooks/useFeedback'

export function FeedbackTrigger({
  position = 'bottom-right',
  size = 'md',
  variant = 'floating',
  disabled = false,
  customIcon
}: FeedbackTriggerProps) {
  const [isHovered, setIsHovered] = useState(false)
  const [showQuickActions, setShowQuickActions] = useState(false)
  const { openFeedback, reportBug, requestFeature, reportUIIssue } = useFeedback()

  const getPositionClasses = () => {
    switch (position) {
      case 'bottom-left':
        return 'bottom-6 left-6'
      case 'top-right':
        return 'top-6 right-6'
      case 'top-left':
        return 'top-6 left-6'
      default:
        return 'bottom-6 right-6'
    }
  }

  const getSizeClasses = () => {
    switch (size) {
      case 'sm':
        return 'w-12 h-12'
      case 'lg':
        return 'w-16 h-16'
      default:
        return 'w-14 h-14'
    }
  }

  const getVariantClasses = () => {
    switch (variant) {
      case 'inline':
        return 'relative'
      case 'minimal':
        return 'relative border-0 shadow-sm'
      default:
        return 'fixed z-50 shadow-lg'
    }
  }

  const handleMainClick = () => {
    if (variant === 'floating' && !showQuickActions) {
      setShowQuickActions(true)
      // Auto-hide quick actions after a delay
      setTimeout(() => setShowQuickActions(false), 5000)
    } else {
      openFeedback()
    }
  }

  const quickActions = [
    {
      icon: Bug,
      label: 'Report Bug',
      action: () => {
        reportBug()
        setShowQuickActions(false)
      },
      className: 'hover:bg-red-50 hover:border-red-200 dark:hover:bg-red-950'
    },
    {
      icon: Lightbulb,
      label: 'Feature Idea',
      action: () => {
        requestFeature()
        setShowQuickActions(false)
      },
      className: 'hover:bg-yellow-50 hover:border-yellow-200 dark:hover:bg-yellow-950'
    },
    {
      icon: Palette,
      label: 'UI Issue',
      action: () => {
        reportUIIssue()
        setShowQuickActions(false)
      },
      className: 'hover:bg-purple-50 hover:border-purple-200 dark:hover:bg-purple-950'
    }
  ]

  if (disabled) {
    return null
  }

  return (
    <div className={cn(getVariantClasses(), getPositionClasses())}>
      {/* Quick Actions Menu */}
      {showQuickActions && variant === 'floating' && (
        <div className="absolute bottom-full right-0 mb-4 space-y-2">
          {quickActions.map((action, index) => (
            <Button
              key={index}
              variant="outline"
              size="sm"
              onClick={action.action}
              className={cn(
                'flex items-center gap-2 whitespace-nowrap bg-background',
                'animate-in slide-in-from-bottom-2 duration-200',
                action.className
              )}
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <action.icon className="w-4 h-4" />
              {action.label}
            </Button>
          ))}
          
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              openFeedback()
              setShowQuickActions(false)
            }}
            className="flex items-center gap-2 whitespace-nowrap bg-background animate-in slide-in-from-bottom-2 duration-200"
            style={{ animationDelay: '150ms' }}
          >
            <MessageSquare className="w-4 h-4" />
            General Feedback
          </Button>
        </div>
      )}

      {/* Main Trigger Button */}
      <Button
        onClick={handleMainClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={cn(
          getSizeClasses(),
          'feedback-trigger rounded-full p-0 transition-all duration-300',
          'hover:scale-105 active:scale-95',
          'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
          variant === 'floating' && 'bg-primary hover:bg-primary/90',
          isHovered && variant === 'floating' && 'shadow-xl'
        )}
        aria-label={
          variant === 'floating' && !showQuickActions
            ? 'Open feedback menu'
            : 'Send feedback'
        }
      >
        <div className="relative flex items-center justify-center">
          {customIcon || (
            <>
              <MessageSquare
                className={cn(
                  'transition-all duration-200',
                  size === 'sm' ? 'w-5 h-5' : size === 'lg' ? 'w-7 h-7' : 'w-6 h-6',
                  showQuickActions ? 'rotate-180 opacity-0' : 'rotate-0 opacity-100'
                )}
              />
              <Plus
                className={cn(
                  'absolute transition-all duration-200',
                  size === 'sm' ? 'w-5 h-5' : size === 'lg' ? 'w-7 h-7' : 'w-6 h-6',
                  showQuickActions ? 'rotate-0 opacity-100' : 'rotate-180 opacity-0'
                )}
              />
            </>
          )}
        </div>
      </Button>

      {/* Tooltip for inline/minimal variants */}
      {variant !== 'floating' && isHovered && (
        <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 text-xs bg-foreground text-background rounded whitespace-nowrap">
          Send Feedback
          <div className="absolute top-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-2 border-r-2 border-t-2 border-transparent border-t-foreground" />
        </div>
      )}

      {/* Pulse animation was causing occasional click interception in sweeps; keep disabled for now */}
    </div>
  )
}
