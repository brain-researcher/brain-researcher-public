// Event Tracking and Analytics Library

import React from 'react'

interface EventData {
  [key: string]: any
}

interface ConversionFunnel {
  name: string
  steps: string[]
  currentStep: number
}

interface UserSession {
  sessionId: string
  userId?: string
  startTime: number
  lastActivity: number
  pageViews: number
  events: Array<{
    name: string
    timestamp: number
    data?: EventData
  }>
}

class AnalyticsClient {
  private apiEndpoint: string
  private session: UserSession | null = null
  private funnels: Map<string, ConversionFunnel> = new Map()
  private eventQueue: Array<{ event: string; data: EventData; timestamp: number }> = []
  private flushInterval: NodeJS.Timeout | null = null
  private debug: boolean = false
  
  constructor(apiEndpoint: string = '/api/events', debug: boolean = false) {
    this.apiEndpoint = apiEndpoint
    this.debug = debug
    this.initializeSession()
    this.startFlushInterval()
    
    // Attach to window for global access
    if (typeof window !== 'undefined') {
      (window as any).trackEvent = this.trackEvent.bind(this)
      (window as any).analytics = this
    }
  }

  /**
   * Initialize or restore session
   */
  private initializeSession() {
    const storedSession = this.getSessionFromStorage()
    
    if (storedSession && Date.now() - storedSession.lastActivity < 30 * 60 * 1000) {
      // Resume existing session if less than 30 minutes old
      this.session = storedSession
      this.session.lastActivity = Date.now()
    } else {
      // Create new session
      this.session = {
        sessionId: this.generateSessionId(),
        startTime: Date.now(),
        lastActivity: Date.now(),
        pageViews: 0,
        events: []
      }
    }
    
    this.saveSessionToStorage()
  }

  /**
   * Track a custom event
   */
  trackEvent(eventName: string, data?: EventData) {
    if (!this.session) return
    
    const event = {
      event: eventName,
      data: {
        ...data,
        sessionId: this.session.sessionId,
        userId: this.session.userId,
        timestamp: new Date().toISOString(),
        pageUrl: typeof window !== 'undefined' ? window.location.href : undefined,
        userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined
      },
      timestamp: Date.now()
    }
    
    // Add to session
    this.session.events.push({
      name: eventName,
      timestamp: Date.now(),
      data
    })
    this.session.lastActivity = Date.now()
    
    // Add to queue
    this.eventQueue.push(event)
    
    // Log in debug mode
    if (this.debug) {
      console.log('[Analytics] Event tracked:', eventName, data)
    }
    
    // Flush if queue is getting large
    if (this.eventQueue.length >= 10) {
      this.flush()
    }
    
    this.saveSessionToStorage()
  }

  /**
   * Track page view
   */
  trackPageView(pageName?: string, properties?: EventData) {
    if (!this.session) return
    
    this.session.pageViews++
    
    this.trackEvent('page_view', {
      page_name: pageName || document.title,
      page_path: window.location.pathname,
      referrer: document.referrer,
      ...properties
    })
  }

  /**
   * Track CTA clicks
   */
  trackCTA(ctaName: string, properties?: EventData) {
    this.trackEvent('cta_clicked', {
      cta_name: ctaName,
      ...properties
    })
  }

  /**
   * Track errors
   */
  trackError(error: Error | string, context?: EventData) {
    const errorData = typeof error === 'string' 
      ? { message: error }
      : {
          message: error.message,
          stack: error.stack,
          name: error.name
        }
    
    this.trackEvent('error', {
      ...errorData,
      ...context,
      severity: context?.severity || 'error'
    })
  }

  /**
   * Start tracking a conversion funnel
   */
  startFunnel(funnelName: string, steps: string[]) {
    this.funnels.set(funnelName, {
      name: funnelName,
      steps,
      currentStep: 0
    })
    
    this.trackEvent('funnel_started', {
      funnel_name: funnelName,
      total_steps: steps.length,
      first_step: steps[0]
    })
  }

  /**
   * Advance funnel to next step
   */
  advanceFunnel(funnelName: string, stepName?: string) {
    const funnel = this.funnels.get(funnelName)
    if (!funnel) return
    
    const nextStep = stepName 
      ? funnel.steps.indexOf(stepName)
      : funnel.currentStep + 1
    
    if (nextStep >= 0 && nextStep < funnel.steps.length) {
      const previousStep = funnel.currentStep
      funnel.currentStep = nextStep
      
      this.trackEvent('funnel_step_completed', {
        funnel_name: funnelName,
        step_name: funnel.steps[previousStep],
        next_step: funnel.steps[nextStep],
        step_number: nextStep + 1,
        total_steps: funnel.steps.length
      })
      
      // Check if funnel completed
      if (nextStep === funnel.steps.length - 1) {
        this.completeFunnel(funnelName)
      }
    }
  }

  /**
   * Mark funnel as completed
   */
  completeFunnel(funnelName: string) {
    const funnel = this.funnels.get(funnelName)
    if (!funnel) return
    
    this.trackEvent('funnel_completed', {
      funnel_name: funnelName,
      total_steps: funnel.steps.length,
      completion_time: Date.now() - (this.session?.startTime || Date.now())
    })
    
    this.funnels.delete(funnelName)
  }

  /**
   * Track First Successful Execution (FSE)
   */
  trackFSE(properties?: EventData) {
    this.trackEvent('first_successful_execution', {
      time_to_fse: Date.now() - (this.session?.startTime || Date.now()),
      session_events: this.session?.events.length || 0,
      ...properties
    })
  }

  /**
   * Set user ID for tracking
   */
  setUserId(userId: string) {
    if (this.session) {
      this.session.userId = userId
      this.saveSessionToStorage()
      
      this.trackEvent('user_identified', { userId })
    }
  }

  /**
   * Get current session info
   */
  getSession(): UserSession | null {
    return this.session
  }

  /**
   * Flush event queue to backend
   */
  private async flush() {
    if (this.eventQueue.length === 0) return
    
    const events = [...this.eventQueue]
    this.eventQueue = []
    
    try {
      const response = await fetch(this.apiEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events }),
        credentials: 'include'
      })
      
      if (!response.ok) {
        // Re-queue events if failed
        this.eventQueue.unshift(...events)
        console.error('Failed to send analytics events:', response.status)
      } else if (this.debug) {
        console.log(`[Analytics] Flushed ${events.length} events`)
      }
    } catch (error) {
      // Re-queue events if failed
      this.eventQueue.unshift(...events)
      console.error('Failed to send analytics events:', error)
    }
  }

  /**
   * Start automatic flush interval
   */
  private startFlushInterval() {
    // Flush every 30 seconds
    this.flushInterval = setInterval(() => {
      this.flush()
    }, 30000)
    
    // Also flush on page unload
    if (typeof window !== 'undefined') {
      window.addEventListener('beforeunload', () => {
        this.flush()
      })
      
      // Flush on visibility change (mobile)
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          this.flush()
        }
      })
    }
  }

  /**
   * Generate unique session ID
   */
  private generateSessionId(): string {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * Save session to localStorage
   */
  private saveSessionToStorage() {
    if (typeof localStorage === 'undefined' || !this.session) return
    
    try {
      localStorage.setItem('analytics_session', JSON.stringify(this.session))
    } catch (error) {
      console.warn('Failed to save analytics session:', error)
    }
  }

  /**
   * Get session from localStorage
   */
  private getSessionFromStorage(): UserSession | null {
    if (typeof localStorage === 'undefined') return null
    
    try {
      const stored = localStorage.getItem('analytics_session')
      return stored ? JSON.parse(stored) : null
    } catch (error) {
      console.warn('Failed to load analytics session:', error)
      return null
    }
  }

  /**
   * Clean up resources
   */
  destroy() {
    if (this.flushInterval) {
      clearInterval(this.flushInterval)
    }
    
    this.flush()
    
    if (typeof window !== 'undefined') {
      delete (window as any).trackEvent
      delete (window as any).analytics
    }
  }
}

// Singleton instance
let analyticsClient: AnalyticsClient | null = null

/**
 * Initialize analytics
 */
export function initializeAnalytics(apiEndpoint?: string, debug?: boolean): AnalyticsClient {
  if (!analyticsClient) {
    analyticsClient = new AnalyticsClient(apiEndpoint, debug)
  }
  return analyticsClient
}

/**
 * Get analytics client instance
 */
export function getAnalytics(): AnalyticsClient | null {
  return analyticsClient
}

/**
 * React hook for analytics
 */
export function useAnalytics() {
  const [client, setClient] = React.useState<AnalyticsClient | null>(null)
  
  React.useEffect(() => {
    const analytics = getAnalytics() || initializeAnalytics()
    setClient(analytics)
    
    return () => {
      // Don't destroy on unmount as it's a singleton
    }
  }, [])
  
  return {
    trackEvent: (name: string, data?: EventData) => client?.trackEvent(name, data),
    trackPageView: (pageName?: string, properties?: EventData) => client?.trackPageView(pageName, properties),
    trackCTA: (ctaName: string, properties?: EventData) => client?.trackCTA(ctaName, properties),
    trackError: (error: Error | string, context?: EventData) => client?.trackError(error, context),
    trackFSE: (properties?: EventData) => client?.trackFSE(properties),
    startFunnel: (name: string, steps: string[]) => client?.startFunnel(name, steps),
    advanceFunnel: (name: string, step?: string) => client?.advanceFunnel(name, step),
    setUserId: (userId: string) => client?.setUserId(userId)
  }
}

// Pre-defined events for consistency
export const ANALYTICS_EVENTS = {
  // Conversion events
  RUN_SUBMITTED: 'run_submitted',
  FIRST_ARTIFACT_SHOWN: 'first_artifact_shown',
  FIRST_SUCCESSFUL_EXECUTION: 'first_successful_execution',
  
  // User actions
  SIGNUP_STARTED: 'signup_started',
  SIGNUP_COMPLETED: 'signup_completed',
  LOGIN_COMPLETED: 'login_completed',
  
  // Navigation
  PAGE_VIEW: 'page_view',
  TAB_SWITCHED: 'tab_switched',
  FILTER_APPLIED: 'filter_applied',
  SEARCH_PERFORMED: 'search_performed',
  
  // Errors
  ERROR_OCCURRED: 'error_occurred',
  API_ERROR: 'api_error',
  TIMEOUT_ERROR: 'timeout_error'
} as const

// Export types
export type { EventData, ConversionFunnel, UserSession }
