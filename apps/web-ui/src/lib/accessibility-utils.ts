/**
 * Accessibility utility functions for WCAG compliance
 */

/**
 * Generate unique ID for form elements and ARIA relationships
 */
export function generateId(prefix: string = 'id'): string {
  return `${prefix}-${Math.random().toString(36).substr(2, 9)}`
}

/**
 * Calculate color contrast ratio between two colors
 * Returns ratio as number (e.g., 4.5 for 4.5:1 ratio)
 */
export function getContrastRatio(color1: string, color2: string): number {
  const getLuminance = (color: string): number => {
    // Convert hex to RGB
    const hex = color.replace('#', '')
    const r = parseInt(hex.substr(0, 2), 16) / 255
    const g = parseInt(hex.substr(2, 2), 16) / 255
    const b = parseInt(hex.substr(4, 2), 16) / 255

    // Calculate relative luminance
    const getRGB = (c: number) => {
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    }

    return 0.2126 * getRGB(r) + 0.7152 * getRGB(g) + 0.0722 * getRGB(b)
  }

  const lum1 = getLuminance(color1)
  const lum2 = getLuminance(color2)
  
  const brightest = Math.max(lum1, lum2)
  const darkest = Math.min(lum1, lum2)
  
  return (brightest + 0.05) / (darkest + 0.05)
}

/**
 * Check if color contrast meets WCAG standards
 */
export function meetsContrastRequirement(
  foreground: string, 
  background: string, 
  level: 'AA' | 'AAA' = 'AA',
  size: 'normal' | 'large' = 'normal'
): boolean {
  const ratio = getContrastRatio(foreground, background)
  
  if (level === 'AAA') {
    return size === 'large' ? ratio >= 4.5 : ratio >= 7
  } else {
    return size === 'large' ? ratio >= 3 : ratio >= 4.5
  }
}

/**
 * Get all focusable elements within a container
 */
export function getFocusableElements(container: HTMLElement): HTMLElement[] {
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
    'summary',
    'details[open]'
  ].join(', ')

  return Array.from(container.querySelectorAll(focusableSelectors))
    .filter((el) => {
      const element = el as HTMLElement
      const style = window.getComputedStyle(element)
      
      return (
        element.offsetParent !== null && // Not hidden
        style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        !element.hasAttribute('inert')
      )
    }) as HTMLElement[]
}

/**
 * Check if element is visible to screen readers
 */
export function isVisibleToScreenReader(element: HTMLElement): boolean {
  const style = window.getComputedStyle(element)
  
  // Element is hidden if:
  return !(
    element.hasAttribute('aria-hidden') ||
    style.display === 'none' ||
    style.visibility === 'hidden' ||
    style.opacity === '0' ||
    element.hasAttribute('inert') ||
    (element.offsetWidth === 0 && element.offsetHeight === 0)
  )
}

/**
 * Announce text to screen readers
 */
export function announceToScreenReader(
  text: string, 
  priority: 'polite' | 'assertive' = 'polite'
): void {
  const announcement = document.createElement('div')
  announcement.setAttribute('aria-live', priority)
  announcement.setAttribute('aria-atomic', 'true')
  announcement.className = 'sr-only'
  announcement.textContent = text

  document.body.appendChild(announcement)

  // Remove after announcement
  setTimeout(() => {
    document.body.removeChild(announcement)
  }, 1000)
}

/**
 * Check if user prefers reduced motion
 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Check if user prefers high contrast
 */
export function prefersHighContrast(): boolean {
  return window.matchMedia('(prefers-contrast: more)').matches
}

/**
 * Create accessible button props
 */
export interface AccessibleButtonProps {
  label: string
  description?: string
  expanded?: boolean
  pressed?: boolean
  controls?: string
  describedBy?: string
}

export function createAccessibleButtonProps({
  label,
  description,
  expanded,
  pressed,
  controls,
  describedBy
}: AccessibleButtonProps) {
  const props: Record<string, any> = {
    'aria-label': label
  }

  if (description) {
    const id = generateId('desc')
    props['aria-describedby'] = describedBy ? `${describedBy} ${id}` : id
    props['data-description'] = description
    props['data-description-id'] = id
  }

  if (expanded !== undefined) {
    props['aria-expanded'] = expanded
  }

  if (pressed !== undefined) {
    props['aria-pressed'] = pressed
  }

  if (controls) {
    props['aria-controls'] = controls
  }

  return props
}

/**
 * Create accessible form field props
 */
export interface AccessibleFieldProps {
  label: string
  description?: string
  error?: string
  required?: boolean
  invalid?: boolean
}

export function createAccessibleFieldProps({
  label,
  description,
  error,
  required = false,
  invalid = false
}: AccessibleFieldProps) {
  const fieldId = generateId('field')
  const labelId = generateId('label')
  const descId = description ? generateId('desc') : undefined
  const errorId = error ? generateId('error') : undefined

  const describedBy = [descId, errorId].filter(Boolean).join(' ')

  return {
    field: {
      id: fieldId,
      'aria-labelledby': labelId,
      'aria-describedby': describedBy || undefined,
      'aria-required': required,
      'aria-invalid': invalid
    },
    label: {
      id: labelId,
      htmlFor: fieldId
    },
    description: description ? {
      id: descId,
      role: 'note'
    } : undefined,
    error: error ? {
      id: errorId,
      role: 'alert',
      'aria-live': 'assertive'
    } : undefined
  }
}

/**
 * Manage focus trap for modals and overlays
 */
export class FocusTrap {
  private container: HTMLElement
  private previousFocus: HTMLElement | null = null
  private isActive = false

  constructor(container: HTMLElement) {
    this.container = container
  }

  activate(initialFocus?: HTMLElement): void {
    if (this.isActive) return

    this.previousFocus = document.activeElement as HTMLElement
    this.isActive = true

    // Focus initial element or first focusable
    const focusTarget = initialFocus || getFocusableElements(this.container)[0]
    if (focusTarget) {
      focusTarget.focus()
    }

    document.addEventListener('keydown', this.handleKeyDown)
  }

  deactivate(): void {
    if (!this.isActive) return

    this.isActive = false
    document.removeEventListener('keydown', this.handleKeyDown)

    // Restore focus
    if (this.previousFocus && this.previousFocus.focus) {
      this.previousFocus.focus()
    }
  }

  private handleKeyDown = (event: KeyboardEvent): void => {
    if (!this.isActive || event.key !== 'Tab') return

    const focusableElements = getFocusableElements(this.container)
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
  }
}