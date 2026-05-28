'use client'

import { useCallback, useRef } from 'react'
import { useAccessibility } from '@/components/accessibility'

/**
 * Hook for managing ARIA live regions and announcements
 */
export function useAriaLive() {
  const { announce, settings } = useAccessibility()
  const timeoutRef = useRef<NodeJS.Timeout>()

  const announceMessage = useCallback((
    message: string,
    options?: {
      priority?: 'polite' | 'assertive'
      delay?: number
      clearPrevious?: boolean
    }
  ) => {
    const { priority = 'polite', delay = 0, clearPrevious = false } = options || {}

    if (!settings.announcements || !message.trim()) return

    if (clearPrevious && timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }

    if (delay > 0) {
      timeoutRef.current = setTimeout(() => {
        announce(message, priority)
      }, delay)
    } else {
      announce(message, priority)
    }
  }, [announce, settings.announcements])

  const announceStatus = useCallback((message: string, delay?: number) => {
    announceMessage(message, { priority: 'polite', delay })
  }, [announceMessage])

  const announceAlert = useCallback((message: string, delay?: number) => {
    announceMessage(message, { priority: 'assertive', delay })
  }, [announceMessage])

  const announceLoading = useCallback((action: string) => {
    announceMessage(`Loading ${action}...`, { priority: 'polite' })
  }, [announceMessage])

  const announceComplete = useCallback((action: string, result?: string) => {
    const message = result 
      ? `${action} completed. ${result}` 
      : `${action} completed.`
    announceMessage(message, { priority: 'polite', delay: 500 })
  }, [announceMessage])

  const announceError = useCallback((action: string, error?: string) => {
    const message = error
      ? `Error: ${action} failed. ${error}`
      : `Error: ${action} failed.`
    announceMessage(message, { priority: 'assertive' })
  }, [announceMessage])

  const announceNavigation = useCallback((location: string) => {
    announceMessage(`Navigated to ${location}`, { 
      priority: 'polite', 
      delay: 100,
      clearPrevious: true 
    })
  }, [announceMessage])

  return {
    announce: announceMessage,
    announceStatus,
    announceAlert,
    announceLoading,
    announceComplete,
    announceError,
    announceNavigation
  }
}