'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

interface TouchPoint {
  x: number
  y: number
  id: number
  timestamp: number
}

interface SwipeGesture {
  direction: 'up' | 'down' | 'left' | 'right'
  distance: number
  velocity: number
  duration: number
  startPoint: { x: number; y: number }
  endPoint: { x: number; y: number }
}

interface PinchGesture {
  scale: number
  velocity: number
  center: { x: number; y: number }
  startDistance: number
  currentDistance: number
}

interface TapGesture {
  x: number
  y: number
  timestamp: number
  count: number
}

interface TouchGestureOptions {
  minSwipeDistance?: number
  maxSwipeTime?: number
  minSwipeVelocity?: number
  doubleTapDelay?: number
  longPressDelay?: number
  pinchThreshold?: number
  preventDefault?: boolean
  enableHaptic?: boolean
}

interface TouchGestureHandlers {
  onSwipe?: (gesture: SwipeGesture) => void
  onPinch?: (gesture: PinchGesture) => void
  onTap?: (gesture: TapGesture) => void
  onDoubleTap?: (gesture: TapGesture) => void
  onLongPress?: (point: TouchPoint) => void
  onTouchStart?: (points: TouchPoint[]) => void
  onTouchMove?: (points: TouchPoint[]) => void
  onTouchEnd?: (points: TouchPoint[]) => void
}

/**
 * Comprehensive touch gesture detection hook with accessibility support
 * Supports swipe, pinch, tap, double-tap, and long-press gestures
 */
export function useTouch(
  elementRef: React.RefObject<HTMLElement>,
  handlers: TouchGestureHandlers,
  options: TouchGestureOptions = {}
) {
  const {
    minSwipeDistance = 100,
    maxSwipeTime = 1000,
    minSwipeVelocity = 0.5,
    doubleTapDelay = 300,
    longPressDelay = 500,
    pinchThreshold = 10,
    preventDefault = true,
    enableHaptic = true
  } = options

  const touchStartRef = useRef<TouchPoint[]>([])
  const lastTapRef = useRef<TapGesture | null>(null)
  const longPressTimerRef = useRef<NodeJS.Timeout>()
  const isLongPressRef = useRef(false)

  // Haptic feedback helper
  const triggerHaptic = useCallback((type: 'light' | 'medium' | 'heavy' = 'light') => {
    if (!enableHaptic || typeof window === 'undefined') return

    // Modern Haptic API
    if ('vibrate' in navigator) {
      const patterns = {
        light: 10,
        medium: 50,
        heavy: 100
      }
      navigator.vibrate(patterns[type])
    }
  }, [enableHaptic])

  // Convert touch event to touch points
  const getTouchPoints = useCallback((event: TouchEvent): TouchPoint[] => {
    return Array.from(event.touches).map((touch, index) => ({
      x: touch.clientX,
      y: touch.clientY,
      id: touch.identifier,
      timestamp: Date.now()
    }))
  }, [])

  // Calculate distance between two points
  const getDistance = useCallback((point1: TouchPoint, point2: TouchPoint): number => {
    const dx = point2.x - point1.x
    const dy = point2.y - point1.y
    return Math.sqrt(dx * dx + dy * dy)
  }, [])

  // Calculate velocity
  const getVelocity = useCallback((distance: number, time: number): number => {
    return time > 0 ? distance / time : 0
  }, [])

  // Determine swipe direction
  const getSwipeDirection = useCallback((start: TouchPoint, end: TouchPoint): 'up' | 'down' | 'left' | 'right' => {
    const dx = end.x - start.x
    const dy = end.y - start.y

    if (Math.abs(dx) > Math.abs(dy)) {
      return dx > 0 ? 'right' : 'left'
    } else {
      return dy > 0 ? 'down' : 'up'
    }
  }, [])

  // Handle touch start
  const handleTouchStart = useCallback((event: TouchEvent) => {
    if (preventDefault) {
      event.preventDefault()
    }

    const touchPoints = getTouchPoints(event)
    touchStartRef.current = touchPoints

    // Clear any existing long press timer
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
    }
    isLongPressRef.current = false

    // Start long press detection for single touch
    if (touchPoints.length === 1 && handlers.onLongPress) {
      longPressTimerRef.current = setTimeout(() => {
        if (touchStartRef.current.length === 1) {
          isLongPressRef.current = true
          triggerHaptic('medium')
          handlers.onLongPress?.(touchPoints[0])
        }
      }, longPressDelay)
    }

    handlers.onTouchStart?.(touchPoints)
  }, [
    getTouchPoints,
    handlers,
    longPressDelay,
    preventDefault,
    triggerHaptic
  ])

  // Handle touch move
  const handleTouchMove = useCallback((event: TouchEvent) => {
    if (preventDefault) {
      event.preventDefault()
    }

    const touchPoints = getTouchPoints(event)

    // Cancel long press if touch moves significantly
    if (touchStartRef.current.length === 1 && touchPoints.length === 1) {
      const distance = getDistance(touchStartRef.current[0], touchPoints[0])
      if (distance > 10) {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current)
        }
        isLongPressRef.current = false
      }
    }

    // Handle pinch gesture
    if (touchPoints.length === 2 && touchStartRef.current.length === 2 && handlers.onPinch) {
      const startDistance = getDistance(touchStartRef.current[0], touchStartRef.current[1])
      const currentDistance = getDistance(touchPoints[0], touchPoints[1])
      
      if (Math.abs(currentDistance - startDistance) > pinchThreshold) {
        const scale = currentDistance / startDistance
        const center = {
          x: (touchPoints[0].x + touchPoints[1].x) / 2,
          y: (touchPoints[0].y + touchPoints[1].y) / 2
        }
        
        const velocity = getVelocity(
          Math.abs(currentDistance - startDistance),
          touchPoints[0].timestamp - touchStartRef.current[0].timestamp
        )

        handlers.onPinch({
          scale,
          velocity,
          center,
          startDistance,
          currentDistance
        })
      }
    }

    handlers.onTouchMove?.(touchPoints)
  }, [
    getTouchPoints,
    getDistance,
    getVelocity,
    handlers,
    pinchThreshold,
    preventDefault
  ])

  // Handle touch end
  const handleTouchEnd = useCallback((event: TouchEvent) => {
    if (preventDefault) {
      event.preventDefault()
    }

    const touchPoints = getTouchPoints(event.changedTouches as any)
    const endTime = Date.now()

    // Clear long press timer
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
    }

    // Handle swipe gesture (single touch)
    if (touchStartRef.current.length === 1 && !isLongPressRef.current && handlers.onSwipe) {
      const startPoint = touchStartRef.current[0]
      const endPoint = touchPoints[0] || startPoint
      
      const distance = getDistance(startPoint, endPoint)
      const duration = endTime - startPoint.timestamp
      const velocity = getVelocity(distance, duration)

      if (
        distance >= minSwipeDistance &&
        duration <= maxSwipeTime &&
        velocity >= minSwipeVelocity
      ) {
        const direction = getSwipeDirection(startPoint, endPoint)
        
        triggerHaptic('light')
        handlers.onSwipe({
          direction,
          distance,
          velocity,
          duration,
          startPoint: { x: startPoint.x, y: startPoint.y },
          endPoint: { x: endPoint.x, y: endPoint.y }
        })
      }
    }

    // Handle tap gesture (single touch, no long press)
    if (
      touchStartRef.current.length === 1 &&
      touchPoints.length === 1 &&
      !isLongPressRef.current &&
      (handlers.onTap || handlers.onDoubleTap)
    ) {
      const tapGesture: TapGesture = {
        x: touchPoints[0].x,
        y: touchPoints[0].y,
        timestamp: endTime,
        count: 1
      }

      // Check for double tap
      if (lastTapRef.current && handlers.onDoubleTap) {
        const timeDiff = endTime - lastTapRef.current.timestamp
        const distance = getDistance(
          { x: lastTapRef.current.x, y: lastTapRef.current.y, id: 0, timestamp: 0 },
          { x: tapGesture.x, y: tapGesture.y, id: 0, timestamp: 0 }
        )

        if (timeDiff <= doubleTapDelay && distance <= 50) {
          tapGesture.count = 2
          triggerHaptic('medium')
          handlers.onDoubleTap(tapGesture)
          lastTapRef.current = null
          return
        }
      }

      // Single tap
      if (handlers.onTap) {
        triggerHaptic('light')
        handlers.onTap(tapGesture)
      }

      lastTapRef.current = tapGesture
    }

    handlers.onTouchEnd?.(touchPoints)
    touchStartRef.current = []
  }, [
    getTouchPoints,
    getDistance,
    getVelocity,
    getSwipeDirection,
    handlers,
    minSwipeDistance,
    maxSwipeTime,
    minSwipeVelocity,
    doubleTapDelay,
    preventDefault,
    triggerHaptic
  ])

  // Set up event listeners
  useEffect(() => {
    const element = elementRef.current
    if (!element) return

    element.addEventListener('touchstart', handleTouchStart, { passive: !preventDefault })
    element.addEventListener('touchmove', handleTouchMove, { passive: !preventDefault })
    element.addEventListener('touchend', handleTouchEnd, { passive: !preventDefault })

    return () => {
      element.removeEventListener('touchstart', handleTouchStart)
      element.removeEventListener('touchmove', handleTouchMove)
      element.removeEventListener('touchend', handleTouchEnd)
      
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current)
      }
    }
  }, [elementRef, handleTouchStart, handleTouchMove, handleTouchEnd, preventDefault])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current)
      }
    }
  }, [])
}

/**
 * Simplified swipe-only hook
 */
export function useSwipe(
  elementRef: React.RefObject<HTMLElement>,
  onSwipe: (direction: 'up' | 'down' | 'left' | 'right') => void,
  options: { minDistance?: number; maxTime?: number } = {}
) {
  const { minDistance = 100, maxTime = 1000 } = options

  return useTouch(
    elementRef,
    {
      onSwipe: (gesture) => onSwipe(gesture.direction)
    },
    {
      minSwipeDistance: minDistance,
      maxSwipeTime: maxTime
    }
  )
}

/**
 * Pinch-to-zoom hook
 */
export function usePinchZoom(
  elementRef: React.RefObject<HTMLElement>,
  onZoom: (scale: number, center: { x: number; y: number }) => void
) {
  return useTouch(
    elementRef,
    {
      onPinch: (gesture) => onZoom(gesture.scale, gesture.center)
    },
    {
      pinchThreshold: 10
    }
  )
}

/**
 * Double-tap hook
 */
export function useDoubleTap(
  elementRef: React.RefObject<HTMLElement>,
  onDoubleTap: (point: { x: number; y: number }) => void,
  delay: number = 300
) {
  return useTouch(
    elementRef,
    {
      onDoubleTap: (gesture) => onDoubleTap({ x: gesture.x, y: gesture.y })
    },
    {
      doubleTapDelay: delay
    }
  )
}

/**
 * Long-press hook
 */
export function useLongPress(
  elementRef: React.RefObject<HTMLElement>,
  onLongPress: (point: { x: number; y: number }) => void,
  delay: number = 500
) {
  return useTouch(
    elementRef,
    {
      onLongPress: (point) => onLongPress({ x: point.x, y: point.y })
    },
    {
      longPressDelay: delay
    }
  )
}

/**
 * Drag gesture hook
 */
export function useDrag(
  elementRef: React.RefObject<HTMLElement>,
  handlers: {
    onDragStart?: (point: { x: number; y: number }) => void
    onDrag?: (point: { x: number; y: number }, delta: { x: number; y: number }) => void
    onDragEnd?: (point: { x: number; y: number }) => void
  }
) {
  const [isDragging, setIsDragging] = useState(false)
  const [startPoint, setStartPoint] = useState<{ x: number; y: number } | null>(null)

  return useTouch(
    elementRef,
    {
      onTouchStart: (points) => {
        if (points.length === 1) {
          const point = { x: points[0].x, y: points[0].y }
          setStartPoint(point)
          setIsDragging(true)
          handlers.onDragStart?.(point)
        }
      },
      onTouchMove: (points) => {
        if (isDragging && points.length === 1 && startPoint) {
          const currentPoint = { x: points[0].x, y: points[0].y }
          const delta = {
            x: currentPoint.x - startPoint.x,
            y: currentPoint.y - startPoint.y
          }
          handlers.onDrag?.(currentPoint, delta)
        }
      },
      onTouchEnd: (points) => {
        if (isDragging) {
          const point = points.length > 0 
            ? { x: points[0].x, y: points[0].y }
            : startPoint || { x: 0, y: 0 }
          
          handlers.onDragEnd?.(point)
          setIsDragging(false)
          setStartPoint(null)
        }
      }
    },
    { preventDefault: true }
  )
}

/**
 * Hook to detect if touch is available
 */
export function useTouchSupport(): boolean {
  const [hasTouch, setHasTouch] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return

    const checkTouch = () => {
      setHasTouch(
        'ontouchstart' in window ||
        navigator.maxTouchPoints > 0 ||
        // @ts-ignore
        navigator.msMaxTouchPoints > 0
      )
    }

    checkTouch()
    
    // Some devices may not report touch support immediately
    const timer = setTimeout(checkTouch, 100)
    
    return () => clearTimeout(timer)
  }, [])

  return hasTouch
}