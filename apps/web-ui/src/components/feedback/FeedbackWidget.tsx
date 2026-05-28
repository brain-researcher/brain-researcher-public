'use client'

import React from 'react'
import { FeedbackDialog } from './FeedbackDialog'
import { FeedbackTrigger } from './FeedbackTrigger'
import { useFeedback } from '@/hooks/useFeedback'
import { FeedbackTriggerProps } from '@/types/feedback'

interface FeedbackWidgetProps extends Omit<FeedbackTriggerProps, 'onOpen'> {
  /**
   * Whether to auto-capture screenshots when feedback is opened
   */
  enableAutoCapture?: boolean
  
  /**
   * Whether to show the feedback trigger button
   */
  showTrigger?: boolean
  
  /**
   * Custom trigger component
   */
  customTrigger?: React.ReactNode
  
  /**
   * Additional context to include with feedback
   */
  context?: string
  
  /**
   * Callback when feedback is successfully submitted
   */
  onFeedbackSubmitted?: (feedbackId: string) => void
  
  /**
   * Callback when feedback dialog is opened
   */
  onFeedbackOpened?: () => void
  
  /**
   * Callback when feedback dialog is closed
   */
  onFeedbackClosed?: () => void
}

/**
 * Complete feedback widget that includes trigger button and dialog
 * 
 * Features:
 * - Floating action button (customizable position and style)
 * - Modal dialog with multi-step form
 * - Screenshot capture capability
 * - Multiple feedback categories
 * - Form validation and submission
 * - Success/error handling
 * - Accessibility support
 * 
 * @example
 * ```tsx
 * // Basic usage - floating button in bottom-right
 * <FeedbackWidget />
 * 
 * // Customized positioning and size
 * <FeedbackWidget 
 *   position="bottom-left" 
 *   size="lg" 
 *   variant="minimal"
 * />
 * 
 * // With callbacks and context
 * <FeedbackWidget
 *   context="User is viewing dataset analysis page"
 *   onFeedbackSubmitted={(id) => analytics.track('feedback_submitted', { id })}
 *   onFeedbackOpened={() => analytics.track('feedback_opened')}
 * />
 * 
 * // Custom trigger with inline variant
 * <FeedbackWidget
 *   variant="inline"
 *   customTrigger={<Button variant="outline">Send Feedback</Button>}
 * />
 * ```
 */
export function FeedbackWidget({
  position = 'bottom-right',
  size = 'md',
  variant = 'floating',
  disabled = false,
  customIcon,
  enableAutoCapture = true,
  showTrigger = true,
  customTrigger,
  context,
  onFeedbackSubmitted,
  onFeedbackOpened,
  onFeedbackClosed,
  ...triggerProps
}: FeedbackWidgetProps) {
  const {
    isOpen,
    isSubmitting,
    openFeedback,
    closeFeedback,
    submitFeedback,
    error,
    lastSubmission
  } = useFeedback({
    enableScreenshots: true,
    autoCapture: enableAutoCapture
  })

  const handleDialogOpenChange = (open: boolean) => {
    if (open) {
      onFeedbackOpened?.()
    } else {
      closeFeedback()
      onFeedbackClosed?.()
    }
  }

  const handleSubmit = async (data: any) => {
    try {
      await submitFeedback(data)
      onFeedbackSubmitted?.(lastSubmission?.id || 'unknown')
    } catch (error) {
      // Error is handled by the form component
      throw error
    }
  }

  return (
    <>
      {/* Trigger Button */}
      {showTrigger && (
        customTrigger ? (
          <div onClick={() => openFeedback()}>
            {customTrigger}
          </div>
        ) : (
          <FeedbackTrigger
            position={position}
            size={size}
            variant={variant}
            disabled={disabled}
            customIcon={customIcon}
            {...triggerProps}
          />
        )
      )}

      {/* Feedback Dialog */}
      <FeedbackDialog
        open={isOpen}
        onOpenChange={handleDialogOpenChange}
        onSubmit={handleSubmit}
        context={context}
      />
    </>
  )
}

// Export convenience components for specific use cases
export { FeedbackDialog, FeedbackTrigger, FeedbackWidget as default }