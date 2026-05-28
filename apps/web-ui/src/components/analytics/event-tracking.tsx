'use client'

import React, { createContext, useContext, useEffect, useCallback, useRef } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'

// Event Types
type EventCategory = 'interaction' | 'navigation' | 'conversion' | 'error' | 'performance'

interface TrackingEvent {
  name: string
  category: EventCategory
  properties?: Record<string, any>
  timestamp: number
  sessionId: string
  userId?: string
  pageUrl: string
  userAgent: string
}

interface ConversionFunnel {
  name: string
  steps: FunnelStep[]
  currentStep: number
  startTime: number
  completionTime?: number
}

interface FunnelStep {
  name: string
  completed: boolean
  timestamp?: number
  properties?: Record<string, any>
}

interface AnalyticsConfig {
  apiEndpoint: string
  trackingId: string
  enableConsoleLog?: boolean
  enableLocalStorage?: boolean
  batchSize?: number
  flushInterval?: number
  sessionTimeout?: number
}

// Analytics Context
interface AnalyticsContextValue {
  track: (name: string, properties?: Record<string, any>, category?: EventCategory) => void
  trackClick: (element: string, properties?: Record<string, any>) => void
  trackPageView: (properties?: Record<string, any>) => void
  trackError: (error: Error, properties?: Record<string, any>) => void
  trackTiming: (name: string, duration: number, properties?: Record<string, any>) => void
  startFunnel: (name: string, steps: string[]) => void
  advanceFunnel: (funnelName: string, properties?: Record<string, any>) => void
  completeFunnel: (funnelName: string) => void
  identify: (userId: string, traits?: Record<string, any>) => void
  getSessionId: () => string
}

const AnalyticsContext = createContext<AnalyticsContextValue | null>(null)

export function useAnalytics() {
  const context = useContext(AnalyticsContext)
  if (!context) {
    throw new Error('useAnalytics must be used within AnalyticsProvider')
  }
  return context
}

// Analytics Provider
export function AnalyticsProvider({
  children,
  config
}: {
  children: React.ReactNode
  config: AnalyticsConfig
}) {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const eventQueue = useRef<TrackingEvent[]>([])
  const funnels = useRef<Map<string, ConversionFunnel>>(new Map())
  const sessionId = useRef<string>(generateSessionId())
  const userId = useRef<string | undefined>()
  const flushTimer = useRef<NodeJS.Timeout>()

  // Generate session ID
  function generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  // Send events to backend
  const flushEvents = useCallback(async () => {
    if (eventQueue.current.length === 0) return

    const events = [...eventQueue.current]
    eventQueue.current = []

    try {
      await fetch(`${config.apiEndpoint}/events`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tracking-Id': config.trackingId
        },
        body: JSON.stringify({ events })
      })

      if (config.enableConsoleLog) {
        console.log('Analytics: Flushed events', events)
      }
    } catch (error) {
      console.error('Analytics: Failed to flush events', error)
      // Re-queue events on failure
      eventQueue.current = [...events, ...eventQueue.current]
    }
  }, [config])

  // Queue event for sending
  const queueEvent = useCallback((event: TrackingEvent) => {
    eventQueue.current.push(event)

    if (config.enableLocalStorage) {
      try {
        const stored = localStorage.getItem('analytics_events') || '[]'
        const events = JSON.parse(stored)
        events.push(event)
        localStorage.setItem('analytics_events', JSON.stringify(events.slice(-100)))
      } catch (e) {
        console.error('Analytics: Failed to store event locally', e)
      }
    }

    if (eventQueue.current.length >= (config.batchSize || 10)) {
      flushEvents()
    }
  }, [config, flushEvents])

  // Track generic event
  const track = useCallback((
    name: string,
    properties?: Record<string, any>,
    category: EventCategory = 'interaction'
  ) => {
    const event: TrackingEvent = {
      name,
      category,
      properties,
      timestamp: Date.now(),
      sessionId: sessionId.current,
      userId: userId.current,
      pageUrl: window.location.href,
      userAgent: navigator.userAgent
    }

    queueEvent(event)

    if (config.enableConsoleLog) {
      console.log('Analytics: Track', name, properties)
    }
  }, [queueEvent, config])

  // Track click events
  const trackClick = useCallback((
    element: string,
    properties?: Record<string, any>
  ) => {
    track(`click_${element}`, {
      ...properties,
      element,
      pageTitle: document.title
    }, 'interaction')
  }, [track])

  // Track page views
  const trackPageView = useCallback((properties?: Record<string, any>) => {
    track('page_view', {
      ...properties,
      path: pathname,
      search: searchParams.toString(),
      referrer: document.referrer,
      title: document.title
    }, 'navigation')
  }, [track, pathname, searchParams])

  // Track errors
  const trackError = useCallback((
    error: Error,
    properties?: Record<string, any>
  ) => {
    track('error', {
      ...properties,
      message: error.message,
      stack: error.stack,
      name: error.name
    }, 'error')
  }, [track])

  // Track timing/performance
  const trackTiming = useCallback((
    name: string,
    duration: number,
    properties?: Record<string, any>
  ) => {
    track(`timing_${name}`, {
      ...properties,
      duration,
      unit: 'ms'
    }, 'performance')
  }, [track])

  // Funnel tracking
  const startFunnel = useCallback((name: string, steps: string[]) => {
    const funnel: ConversionFunnel = {
      name,
      steps: steps.map(step => ({ name: step, completed: false })),
      currentStep: 0,
      startTime: Date.now()
    }
    
    funnels.current.set(name, funnel)
    
    track('funnel_started', {
      funnel: name,
      steps: steps.length,
      firstStep: steps[0]
    }, 'conversion')
  }, [track])

  const advanceFunnel = useCallback((
    funnelName: string,
    properties?: Record<string, any>
  ) => {
    const funnel = funnels.current.get(funnelName)
    if (!funnel) return

    const currentStep = funnel.steps[funnel.currentStep]
    if (currentStep && !currentStep.completed) {
      currentStep.completed = true
      currentStep.timestamp = Date.now()
      currentStep.properties = properties

      track('funnel_step_completed', {
        funnel: funnelName,
        step: currentStep.name,
        stepNumber: funnel.currentStep + 1,
        totalSteps: funnel.steps.length,
        timeSpent: currentStep.timestamp - funnel.startTime,
        ...properties
      }, 'conversion')

      funnel.currentStep++
    }
  }, [track])

  const completeFunnel = useCallback((funnelName: string) => {
    const funnel = funnels.current.get(funnelName)
    if (!funnel) return

    funnel.completionTime = Date.now()
    const duration = funnel.completionTime - funnel.startTime

    track('funnel_completed', {
      funnel: funnelName,
      duration,
      steps: funnel.steps.length,
      completedSteps: funnel.steps.filter(s => s.completed).length
    }, 'conversion')

    funnels.current.delete(funnelName)
  }, [track])

  // User identification
  const identify = useCallback((
    newUserId: string,
    traits?: Record<string, any>
  ) => {
    userId.current = newUserId
    
    track('identify', {
      userId: newUserId,
      ...traits
    }, 'interaction')
  }, [track])

  // Get session ID
  const getSessionId = useCallback(() => sessionId.current, [])

  // Set up auto-flush
  useEffect(() => {
    flushTimer.current = setInterval(
      flushEvents,
      config.flushInterval || 30000
    )

    return () => {
      if (flushTimer.current) {
        clearInterval(flushTimer.current)
      }
      flushEvents()
    }
  }, [flushEvents, config.flushInterval])

  // Track page views on navigation
  useEffect(() => {
    trackPageView()
  }, [pathname, searchParams, trackPageView])

  // Track errors globally
  useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      trackError(new Error(event.message), {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno
      })
    }

    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      trackError(new Error(`Unhandled Promise Rejection: ${event.reason}`))
    }

    window.addEventListener('error', handleError)
    window.addEventListener('unhandledrejection', handleUnhandledRejection)

    return () => {
      window.removeEventListener('error', handleError)
      window.removeEventListener('unhandledrejection', handleUnhandledRejection)
    }
  }, [trackError])

  const value: AnalyticsContextValue = {
    track,
    trackClick,
    trackPageView,
    trackError,
    trackTiming,
    startFunnel,
    advanceFunnel,
    completeFunnel,
    identify,
    getSessionId
  }

  return (
    <AnalyticsContext.Provider value={value}>
      {children}
    </AnalyticsContext.Provider>
  )
}

// Common Event Tracking Hooks
export function useTrackClick(elementName: string) {
  const { trackClick } = useAnalytics()
  
  return useCallback((properties?: Record<string, any>) => {
    trackClick(elementName, properties)
  }, [trackClick, elementName])
}

export function useTrackTiming(name: string) {
  const { trackTiming } = useAnalytics()
  const startTime = useRef<number>()

  const start = useCallback(() => {
    startTime.current = Date.now()
  }, [])

  const end = useCallback((properties?: Record<string, any>) => {
    if (startTime.current) {
      const duration = Date.now() - startTime.current
      trackTiming(name, duration, properties)
      startTime.current = undefined
    }
  }, [trackTiming, name])

  return { start, end }
}

// Conversion Funnel Hook
export function useConversionFunnel(
  funnelName: string,
  steps: string[]
) {
  const { startFunnel, advanceFunnel, completeFunnel } = useAnalytics()
  const currentStep = useRef(0)

  useEffect(() => {
    startFunnel(funnelName, steps)
    return () => {
      // Clean up incomplete funnel on unmount
    }
  }, [startFunnel, funnelName, steps])

  const nextStep = useCallback((properties?: Record<string, any>) => {
    advanceFunnel(funnelName, properties)
    currentStep.current++
    
    if (currentStep.current >= steps.length) {
      completeFunnel(funnelName)
    }
  }, [advanceFunnel, completeFunnel, funnelName, steps.length])

  return { nextStep, currentStep: currentStep.current }
}

// Performance monitoring
export function usePerformanceMonitoring() {
  const { trackTiming } = useAnalytics()

  useEffect(() => {
    // Track page load performance
    if (typeof window !== 'undefined' && window.performance) {
      const perfData = window.performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
      
      if (perfData) {
        trackTiming('page_load', perfData.loadEventEnd - perfData.fetchStart, {
          domContentLoaded: perfData.domContentLoadedEventEnd - perfData.fetchStart,
          domInteractive: perfData.domInteractive - perfData.fetchStart
        })
      }
    }
  }, [trackTiming])
}

// Export everything
const analyticsExports = {
  AnalyticsProvider,
  useAnalytics,
  useTrackClick,
  useTrackTiming,
  useConversionFunnel,
  usePerformanceMonitoring
}

export default analyticsExports
