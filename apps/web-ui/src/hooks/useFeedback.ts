'use client'

import { useState, useCallback, useRef } from 'react'
import { useFeedbackContext } from '@/contexts/FeedbackContext'
import { FeedbackFormData, FeedbackCategory, UseFeedbackOptions } from '@/types/feedback'

export function useFeedback(options: UseFeedbackOptions = {}) {
  const {
    autoCapture = true,
    enableScreenshots = true,
    maxRetries = 3,
    submitTimeout = 30000
  } = options

  const context = useFeedbackContext()
  const timeoutRef = useRef<NodeJS.Timeout>()
  const [localError, setLocalError] = useState<string | null>(null)

  const openFeedback = useCallback((initialCategory?: FeedbackCategory, contextInfo?: string) => {
    context.setIsOpen(true)
  }, [context])

  const closeFeedback = useCallback(() => {
    context.setIsOpen(false)
    setLocalError(null)
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
  }, [context])

  const submitWithTimeout = useCallback(async (data: FeedbackFormData) => {
    return new Promise<void>((resolve, reject) => {
      let completed = false

      // Set up timeout
      timeoutRef.current = setTimeout(() => {
        if (!completed) {
          completed = true
          setLocalError('Submission timed out. Please try again.')
          reject(new Error('Submission timed out'))
        }
      }, submitTimeout)

      // Submit feedback
      context.submitFeedback(data)
        .then(() => {
          if (!completed) {
            completed = true
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current)
            }
            resolve()
          }
        })
        .catch((error) => {
          if (!completed) {
            completed = true
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current)
            }
            setLocalError(error.message)
            reject(error)
          }
        })
    })
  }, [context, submitTimeout])

  // Enhanced error handling
  const error = localError || context.error

  // Convenience methods for different feedback types
  const reportBug = useCallback((contextInfo?: string) => {
    openFeedback('bug-report', contextInfo)
  }, [openFeedback])

  const requestFeature = useCallback((contextInfo?: string) => {
    openFeedback('feature-request', contextInfo)
  }, [openFeedback])

  const reportUIIssue = useCallback((contextInfo?: string) => {
    openFeedback('ui-ux', contextInfo)
  }, [openFeedback])

  const reportPerformance = useCallback((contextInfo?: string) => {
    openFeedback('performance', contextInfo)
  }, [openFeedback])

  return {
    // State
    isOpen: context.isOpen,
    isSubmitting: context.isSubmitting,
    lastSubmission: context.lastSubmission,
    error,

    // Actions
    openFeedback,
    closeFeedback,
    submitFeedback: submitWithTimeout,

    // Convenience methods
    reportBug,
    requestFeature,
    reportUIIssue,
    reportPerformance,

    // Options
    enableScreenshots,
    autoCapture
  }
}