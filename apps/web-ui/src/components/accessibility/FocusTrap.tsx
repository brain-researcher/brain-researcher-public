'use client'

import * as React from "react"

export interface FocusTrapProps {
  /** Whether the focus trap is active */
  active: boolean
  /** Children to wrap in the focus trap */
  children: React.ReactNode
  /** Callback when focus trap is disabled by user action */
  onDeactivate?: () => void
  /** Element to focus when trap is activated */
  initialFocus?: HTMLElement | null
  /** Element to focus when trap is deactivated */
  returnFocus?: HTMLElement | null
}

/**
 * Focus trap component for modals and other interactive overlays
 * Ensures focus stays within the trapped area for keyboard users
 */
export function FocusTrap({
  active,
  children,
  onDeactivate,
  initialFocus,
  returnFocus
}: FocusTrapProps) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const previousFocus = React.useRef<HTMLElement | null>(null)

  // Get all focusable elements
  const getFocusableElements = React.useCallback(() => {
    if (!containerRef.current) return []
    
    const focusableSelectors = [
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      'a[href]',
      '[tabindex]:not([tabindex="-1"])',
      '[contenteditable="true"]'
    ].join(', ')

    return Array.from(containerRef.current.querySelectorAll(focusableSelectors)) as HTMLElement[]
  }, [])

  // Handle keydown for focus management
  const handleKeyDown = React.useCallback((event: KeyboardEvent) => {
    if (!active) return

    const focusableElements = getFocusableElements()
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    if (event.key === 'Tab') {
      // Trap Tab key
      if (event.shiftKey) {
        // Shift + Tab
        if (document.activeElement === firstElement) {
          event.preventDefault()
          lastElement?.focus()
        }
      } else {
        // Tab
        if (document.activeElement === lastElement) {
          event.preventDefault()
          firstElement?.focus()
        }
      }
    } else if (event.key === 'Escape') {
      // Allow Escape to close
      event.preventDefault()
      onDeactivate?.()
    }
  }, [active, getFocusableElements, onDeactivate])

  // Activate focus trap
  React.useEffect(() => {
    if (!active) return

    // Store previous focus
    previousFocus.current = document.activeElement as HTMLElement

    // Set initial focus
    const focusTarget = initialFocus || getFocusableElements()[0]
    if (focusTarget) {
      focusTarget.focus()
    }

    // Add event listener
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [active, initialFocus, getFocusableElements, handleKeyDown])

  // Restore focus on deactivation
  React.useEffect(() => {
    return () => {
      if (!active && previousFocus.current && returnFocus !== null) {
        const focusTarget = returnFocus || previousFocus.current
        focusTarget?.focus()
      }
    }
  }, [active, returnFocus])

  if (!active) {
    return <>{children}</>
  }

  return (
    <div ref={containerRef} data-focus-trap>
      {children}
    </div>
  )
}