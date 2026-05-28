'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

// Mobile-first breakpoint system
export const BREAKPOINTS = {
  mobile: 320,   // Mobile phones
  tablet: 768,   // Tablets
  desktop: 1024, // Desktop computers
  wide: 1440     // Wide screens
} as const

export type BreakpointName = keyof typeof BREAKPOINTS
export type DeviceType = 'mobile' | 'tablet' | 'desktop' | 'wide'

interface ResponsiveState {
  width: number
  height: number
  breakpoint: BreakpointName
  deviceType: DeviceType
  isPortrait: boolean
  isTouchDevice: boolean
  isOnline: boolean
  pixelRatio: number
  isLowEndDevice: boolean
  reducedMotion: boolean
}

interface ResponsiveOptions {
  debounceMs?: number
  trackOrientation?: boolean
  trackConnection?: boolean
  trackPerformance?: boolean
}

/**
 * Custom hook for responsive design with mobile-first approach
 * Provides breakpoint detection, device information, and performance hints
 */
export function useResponsive({
  debounceMs = 100,
  trackOrientation = true,
  trackConnection = true,
  trackPerformance = true
}: ResponsiveOptions = {}): ResponsiveState {
  
  const [state, setState] = useState<ResponsiveState>({
    width: 0,
    height: 0,
    breakpoint: 'mobile',
    deviceType: 'mobile',
    isPortrait: true,
    isTouchDevice: false,
    isOnline: true,
    pixelRatio: 1,
    isLowEndDevice: false,
    reducedMotion: false
  })

  const timeoutRef = useRef<NodeJS.Timeout>()

  // Determine current breakpoint based on width
  const getBreakpoint = useCallback((width: number): BreakpointName => {
    if (width >= BREAKPOINTS.wide) return 'wide'
    if (width >= BREAKPOINTS.desktop) return 'desktop'
    if (width >= BREAKPOINTS.tablet) return 'tablet'
    return 'mobile'
  }, [])

  // Determine device type (more semantic than breakpoint)
  const getDeviceType = useCallback((width: number): DeviceType => {
    return getBreakpoint(width)
  }, [getBreakpoint])

  // Check if device is touch-enabled
  const getTouchSupport = useCallback((): boolean => {
    if (typeof window === 'undefined') return false
    
    return (
      'ontouchstart' in window ||
      navigator.maxTouchPoints > 0 ||
      // @ts-ignore - Legacy support
      navigator.msMaxTouchPoints > 0
    )
  }, [])

  // Detect low-end devices based on hardware concurrency
  const getIsLowEndDevice = useCallback((): boolean => {
    if (typeof window === 'undefined') return false
    
    return (
      navigator.hardwareConcurrency <= 2 ||
      // @ts-ignore - Check available memory if supported
      (navigator.deviceMemory && navigator.deviceMemory <= 4)
    )
  }, [])

  // Check reduced motion preference
  const getReducedMotion = useCallback((): boolean => {
    if (typeof window === 'undefined') return false
    
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  // Update responsive state
  const updateState = useCallback(() => {
    if (typeof window === 'undefined') return

    const width = window.innerWidth
    const height = window.innerHeight
    const breakpoint = getBreakpoint(width)
    const deviceType = getDeviceType(width)

    setState(prev => ({
      ...prev,
      width,
      height,
      breakpoint,
      deviceType,
      ...(trackOrientation && { isPortrait: height > width }),
      isTouchDevice: getTouchSupport(),
      ...(trackConnection && { isOnline: navigator.onLine }),
      pixelRatio: window.devicePixelRatio || 1,
      ...(trackPerformance && { 
        isLowEndDevice: getIsLowEndDevice(),
        reducedMotion: getReducedMotion()
      })
    }))
  }, [
    getBreakpoint,
    getDeviceType,
    getTouchSupport,
    getIsLowEndDevice,
    getReducedMotion,
    trackOrientation,
    trackConnection,
    trackPerformance
  ])

  // Debounced update function
  const debouncedUpdate = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
    
    timeoutRef.current = setTimeout(updateState, debounceMs)
  }, [updateState, debounceMs])

  // Set up event listeners
  useEffect(() => {
    if (typeof window === 'undefined') return

    // Initial state
    updateState()

    // Window resize listener
    window.addEventListener('resize', debouncedUpdate, { passive: true })
    
    // Orientation change listener
    if (trackOrientation) {
      window.addEventListener('orientationchange', debouncedUpdate, { passive: true })
    }

    // Online/offline listeners
    if (trackConnection) {
      window.addEventListener('online', updateState, { passive: true })
      window.addEventListener('offline', updateState, { passive: true })
    }

    // Reduced motion preference change
    if (trackPerformance) {
      const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
      const handleMotionChange = () => updateState()
      
      mediaQuery.addEventListener('change', handleMotionChange)
      
      return () => {
        window.removeEventListener('resize', debouncedUpdate)
        if (trackOrientation) {
          window.removeEventListener('orientationchange', debouncedUpdate)
        }
        if (trackConnection) {
          window.removeEventListener('online', updateState)
          window.removeEventListener('offline', updateState)
        }
        mediaQuery.removeEventListener('change', handleMotionChange)
        
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current)
        }
      }
    }

    return () => {
      window.removeEventListener('resize', debouncedUpdate)
      if (trackOrientation) {
        window.removeEventListener('orientationchange', debouncedUpdate)
      }
      if (trackConnection) {
        window.removeEventListener('online', updateState)
        window.removeEventListener('offline', updateState)
      }
      
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [debouncedUpdate, updateState, trackOrientation, trackConnection, trackPerformance])

  return state
}

/**
 * Hook for matching specific breakpoints
 */
export function useBreakpoint(breakpoint: BreakpointName): boolean {
  const { width } = useResponsive()
  
  return width >= BREAKPOINTS[breakpoint]
}

/**
 * Hook for matching device type
 */
export function useDeviceType(): DeviceType {
  const { deviceType } = useResponsive()
  return deviceType
}

/**
 * Hook for mobile detection
 */
export function useIsMobile(): boolean {
  const { deviceType } = useResponsive()
  return deviceType === 'mobile'
}

/**
 * Hook for tablet detection  
 */
export function useIsTablet(): boolean {
  const { deviceType } = useResponsive()
  return deviceType === 'tablet'
}

/**
 * Hook for desktop detection
 */
export function useIsDesktop(): boolean {
  const { deviceType } = useResponsive()
  return deviceType === 'desktop' || deviceType === 'wide'
}

/**
 * Hook for touch device detection
 */
export function useIsTouchDevice(): boolean {
  const { isTouchDevice } = useResponsive()
  return isTouchDevice
}

/**
 * Hook for orientation detection
 */
export function useOrientation(): {
  isPortrait: boolean
  isLandscape: boolean
  orientation: 'portrait' | 'landscape'
} {
  const { isPortrait } = useResponsive()
  
  return {
    isPortrait,
    isLandscape: !isPortrait,
    orientation: isPortrait ? 'portrait' : 'landscape'
  }
}

/**
 * Hook for viewport dimensions
 */
export function useViewport(): { width: number; height: number; aspectRatio: number } {
  const { width, height } = useResponsive()
  
  return {
    width,
    height,
    aspectRatio: width / height
  }
}

/**
 * Hook for performance hints
 */
export function usePerformanceHints(): {
  isLowEndDevice: boolean
  reducedMotion: boolean
  pixelRatio: number
  connectionType?: string
} {
  const { isLowEndDevice, reducedMotion, pixelRatio } = useResponsive({ trackPerformance: true })
  
  // @ts-ignore - Check network information if available
  const connectionType = navigator.connection?.effectiveType || undefined
  
  return {
    isLowEndDevice,
    reducedMotion,
    pixelRatio,
    connectionType
  }
}

/**
 * Hook for media queries
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return

    const mediaQuery = window.matchMedia(query)
    setMatches(mediaQuery.matches)

    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches)
    }

    mediaQuery.addEventListener('change', handleChange)
    
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [query])

  return matches
}

/**
 * Hook for safe area insets (iOS notch support)
 */
export function useSafeAreaInsets(): {
  top: number
  right: number
  bottom: number
  left: number
} {
  const [insets, setInsets] = useState({ top: 0, right: 0, bottom: 0, left: 0 })

  useEffect(() => {
    if (typeof window === 'undefined') return

    const updateInsets = () => {
      const computedStyle = getComputedStyle(document.documentElement)
      
      setInsets({
        top: parseInt(computedStyle.getPropertyValue('env(safe-area-inset-top)') || '0'),
        right: parseInt(computedStyle.getPropertyValue('env(safe-area-inset-right)') || '0'),
        bottom: parseInt(computedStyle.getPropertyValue('env(safe-area-inset-bottom)') || '0'),
        left: parseInt(computedStyle.getPropertyValue('env(safe-area-inset-left)') || '0')
      })
    }

    updateInsets()
    
    // Listen for orientation changes that might affect safe areas
    window.addEventListener('orientationchange', updateInsets, { passive: true })
    window.addEventListener('resize', updateInsets, { passive: true })

    return () => {
      window.removeEventListener('orientationchange', updateInsets)
      window.removeEventListener('resize', updateInsets)
    }
  }, [])

  return insets
}

/**
 * Hook for container queries (experimental)
 */
export function useContainerQuery(containerRef: React.RefObject<HTMLElement>, query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    if (!containerRef.current || typeof window === 'undefined') return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return

      const { width, height } = entry.contentRect
      
      // Parse simple width-based queries
      if (query.includes('min-width')) {
        const minWidth = parseInt(query.match(/min-width:\s*(\d+)px/)?.[1] || '0')
        setMatches(width >= minWidth)
      } else if (query.includes('max-width')) {
        const maxWidth = parseInt(query.match(/max-width:\s*(\d+)px/)?.[1] || '99999')
        setMatches(width <= maxWidth)
      }
    })

    observer.observe(containerRef.current)
    
    return () => observer.disconnect()
  }, [containerRef, query])

  return matches
}