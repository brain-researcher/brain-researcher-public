'use client'

import React, { createContext, useContext, useState, useCallback } from 'react'
import { FeedbackFormData, FeedbackSubmission, FeedbackContext as IFeedbackContext } from '@/types/feedback'
import { serviceEndpoints } from '@/lib/service-endpoints'

const FeedbackContext = createContext<IFeedbackContext | undefined>(undefined)

interface FeedbackProviderProps {
  children: React.ReactNode
  apiEndpoint?: string
  maxRetries?: number
}

export function FeedbackProvider({ 
  children, 
  apiEndpoint = '/api/feedback',
  maxRetries = 3 
}: FeedbackProviderProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastSubmission, setLastSubmission] = useState<FeedbackSubmission>()
  const [error, setError] = useState<string | null>(null)

  const submitFeedback = useCallback(async (data: FeedbackFormData) => {
    setIsSubmitting(true)
    setError(null)

    try {
      // Create submission record
      const submission: FeedbackSubmission = {
        ...data,
        id: `feedback-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        status: 'pending',
        retryCount: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
        url: window.location.href
      }

      // Handle screenshot upload if present
      let screenshotUrl: string | undefined
      if (data.screenshot) {
        const screenshotFormData = new FormData()
        screenshotFormData.append('screenshot', data.screenshot)
        screenshotFormData.append('feedbackId', submission.id)

        const screenshotResponse = await fetch(
          '/api/feedback/screenshot',
          {
            method: 'POST',
            body: screenshotFormData
          }
        )

        if (screenshotResponse.ok) {
          const screenshotResult = await screenshotResponse.json()
          screenshotUrl = screenshotResult.url
        } else {
          console.warn('Screenshot upload failed, continuing without it')
        }
      }

      // Submit feedback
      const submitData = {
        ...submission,
        screenshotUrl,
        screenshot: undefined // Don't include the File object in the submission
      }

      let lastError: Error | null = null
      let success = false
      const submitEndpoint = apiEndpoint.startsWith('http')
        ? apiEndpoint
        : apiEndpoint

      // Retry logic
      for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
          const response = await fetch(submitEndpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(submitData)
          })

          if (response.ok) {
            const result = await response.json()
            submission.status = 'submitted'
            submission.updatedAt = new Date().toISOString()
            setLastSubmission(submission)
            success = true
            break
          } else {
            const errorData = await response.json()
            throw new Error(errorData.error || `HTTP ${response.status}`)
          }
        } catch (err) {
          lastError = err as Error
          submission.retryCount = attempt + 1
          
          if (attempt < maxRetries - 1) {
            // Wait before retrying (exponential backoff)
            await new Promise(resolve => setTimeout(resolve, Math.pow(2, attempt) * 1000))
          }
        }
      }

      if (!success && lastError) {
        submission.status = 'error'
        submission.updatedAt = new Date().toISOString()
        setLastSubmission(submission)
        throw lastError
      }

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred'
      setError(errorMessage)
      throw err
    } finally {
      setIsSubmitting(false)
    }
  }, [apiEndpoint, maxRetries])

  const value: IFeedbackContext = {
    isOpen,
    setIsOpen,
    submitFeedback,
    isSubmitting,
    lastSubmission,
    error
  }

  return (
    <FeedbackContext.Provider value={value}>
      {children}
    </FeedbackContext.Provider>
  )
}

export function useFeedbackContext() {
  const context = useContext(FeedbackContext)
  if (context === undefined) {
    throw new Error('useFeedbackContext must be used within a FeedbackProvider')
  }
  return context
}

export { FeedbackContext }
