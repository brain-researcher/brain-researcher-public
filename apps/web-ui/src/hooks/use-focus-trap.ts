'use client'

import { useCallback, useEffect, useRef } from 'react'

export interface UseFocusTrapOptions {
  /** Whether the focus trap is active */
  active: boolean
  /** Callback when trap should be deactivated */
  onDeactivate?: () => void
  /** Initial element to focus */
  initialFocus?: HTMLElement | string
  /** Element to return focus to when deactivated */
  returnFocus?: HTMLElement | string
  /** Allow clicking outside to deactivate */
  clickOutsideDeactivates?: boolean
  /** Allow escape key to deactivate */
  escapeDeactivates?: boolean
}

/**
 * Hook for managing focus traps in modals and overlays
 */
export function useFocusTrap(
  containerRef: React.RefObject<HTMLElement>,
  options: UseFocusTrapOptions
) {
  const {
    active,
    onDeactivate,
    initialFocus,
    returnFocus,
    clickOutsideDeactivates = true,
    escapeDeactivates = true
  } = options

  const previousFocusRef = useRef<HTMLElement | null>(null)

  const getFocusableElements = useCallback((): HTMLElement[] => {
    if (!containerRef.current) return []

    const focusableSelectors = [
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      'a[href]',
      'area[href]',
      'object',
      'embed',
      '[tabindex]:not([tabindex="-1"])',
      '[contenteditable="true"]',
      'audio[controls]',
      'video[controls]',
      'summary'
    ].join(', ')

    return Array.from(
      containerRef.current.querySelectorAll(focusableSelectors)
    ).filter((el) => {
      const element = el as HTMLElement
      return element.offsetParent !== null || element === document.activeElement
    }) as HTMLElement[]
  }, [containerRef])

  const focusFirst = useCallback(() => {
    const focusableElements = getFocusableElements()
    
    if (typeof initialFocus === 'string') {
      const element = containerRef.current?.querySelector(initialFocus) as HTMLElement
      if (element) {
        element.focus()
        return
      }
    } else if (initialFocus instanceof HTMLElement) {
      initialFocus.focus()
      return
    }

    // Focus first focusable element
    if (focusableElements.length > 0) {
      focusableElements[0].focus()
    }
  }, [containerRef, initialFocus, getFocusableElements])

  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (!active) return

    if (escapeDeactivates && event.key === 'Escape') {
      event.preventDefault()
      onDeactivate?.()
      return
    }

    if (event.key !== 'Tab') return

    const focusableElements = getFocusableElements()
    if (focusableElements.length === 0) return

    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]
    const currentElement = document.activeElement as HTMLElement

    if (event.shiftKey) {
      // Shift + Tab
      if (currentElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      }
    } else {
      // Tab
      if (currentElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }
  }, [active, escapeDeactivates, onDeactivate, getFocusableElements])

  const handleClickOutside = useCallback((event: MouseEvent) => {
    if (!active || !clickOutsideDeactivates) return
    
    const target = event.target as Node
    if (containerRef.current && !containerRef.current.contains(target)) {
      onDeactivate?.()
    }
  }, [active, clickOutsideDeactivates, containerRef, onDeactivate])

  // Activate trap
  useEffect(() => {
    if (!active) return

    // Store current focus
    previousFocusRef.current = document.activeElement as HTMLElement

    // Focus first element
    requestAnimationFrame(focusFirst)

    // Add event listeners
    document.addEventListener('keydown', handleKeyDown)
    if (clickOutsideDeactivates) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [active, focusFirst, handleKeyDown, handleClickOutside, clickOutsideDeactivates])

  // Restore focus when deactivated
  useEffect(() => {
    if (!active && previousFocusRef.current) {
      const elementToFocus = typeof returnFocus === 'string'
        ? document.querySelector(returnFocus) as HTMLElement
        : returnFocus || previousFocusRef.current

      if (elementToFocus && elementToFocus.focus) {
        elementToFocus.focus()
      }
    }
  }, [active, returnFocus])

  return {
    focusFirst,
    getFocusableElements
  }
}