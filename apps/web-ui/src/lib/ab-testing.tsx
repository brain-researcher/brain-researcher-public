// A/B Testing Client Library

import React from 'react'

interface ABTestVariant {
  test: string
  variant: string
  assignedAt: string
}

interface ABTestConfig {
  testName: string
  variants: string[]
  cookieName?: string
  cookieExpiry?: number // days
  apiEndpoint?: string
}

class ABTestingClient {
  private apiEndpoint: string
  private variants: Map<string, ABTestVariant> = new Map()
  
  constructor(apiEndpoint: string = '/api/ab') {
    this.apiEndpoint = apiEndpoint
    this.loadFromCookies()
  }

  /**
   * Get or assign a variant for a test
   */
  async getVariant(config: ABTestConfig): Promise<string> {
    const cookieName = config.cookieName || `ab_${config.testName}`
    
    // Check if already assigned
    const existing = this.variants.get(config.testName)
    if (existing) {
      return existing.variant
    }
    
    // Check cookies
    const cookieVariant = this.getCookie(cookieName)
    if (cookieVariant) {
      this.variants.set(config.testName, {
        test: config.testName,
        variant: cookieVariant,
        assignedAt: new Date().toISOString()
      })
      return cookieVariant
    }
    
    // Request assignment from backend
    try {
      const response = await fetch(`${this.apiEndpoint}/assign?test=${config.testName}`, {
        method: 'GET',
        credentials: 'include'
      })
      
      if (response.ok) {
        const data = await response.json()
        const variant = data.variant || this.randomVariant(config.variants)
        
        // Store in cookie
        this.setCookie(cookieName, variant, config.cookieExpiry || 30)
        
        // Store in memory
        this.variants.set(config.testName, {
          test: config.testName,
          variant,
          assignedAt: new Date().toISOString()
        })
        
        // Track assignment
        this.trackEvent('ab_test_assigned', {
          test: config.testName,
          variant
        })
        
        return variant
      }
    } catch (error) {
      console.error('Failed to get AB test assignment:', error)
    }
    
    // Fallback to random assignment
    const variant = this.randomVariant(config.variants)
    this.setCookie(cookieName, variant, config.cookieExpiry || 30)
    this.variants.set(config.testName, {
      test: config.testName,
      variant,
      assignedAt: new Date().toISOString()
    })
    
    return variant
  }

  /**
   * Track conversion for a test
   */
  async trackConversion(testName: string, conversionType: string = 'default') {
    const variant = this.variants.get(testName)
    if (!variant) {
      console.warn(`No variant found for test: ${testName}`)
      return
    }
    
    try {
      await fetch(`${this.apiEndpoint}/track`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          test: testName,
          variant: variant.variant,
          event: 'conversion',
          conversionType,
          timestamp: new Date().toISOString()
        }),
        credentials: 'include'
      })
      
      // Also track via analytics
      this.trackEvent('ab_test_conversion', {
        test: testName,
        variant: variant.variant,
        conversionType
      })
    } catch (error) {
      console.error('Failed to track AB test conversion:', error)
    }
  }

  /**
   * Track custom event for a test
   */
  async trackEvent(eventName: string, data: any) {
    // Add variant data to all events
    const enrichedData = {
      ...data,
      ab_variants: Object.fromEntries(this.variants)
    }
    
    // Use global analytics if available
    if (typeof window !== 'undefined' && (window as any).trackEvent) {
      (window as any).trackEvent(eventName, enrichedData)
    }
    
    // Also send to AB testing endpoint
    try {
      await fetch(`${this.apiEndpoint}/event`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event: eventName,
          data: enrichedData,
          timestamp: new Date().toISOString()
        }),
        credentials: 'include'
      })
    } catch (error) {
      console.error('Failed to track AB event:', error)
    }
  }

  /**
   * Check if user is in a specific variant
   */
  isVariant(testName: string, variantName: string): boolean {
    const variant = this.variants.get(testName)
    return variant?.variant === variantName
  }

  /**
   * Get all active variants
   */
  getAllVariants(): Record<string, string> {
    const result: Record<string, string> = {}
    this.variants.forEach((value, key) => {
      result[key] = value.variant
    })
    return result
  }

  // Cookie utilities
  private getCookie(name: string): string | null {
    if (typeof document === 'undefined') return null
    
    const value = `; ${document.cookie}`
    const parts = value.split(`; ${name}=`)
    
    if (parts.length === 2) {
      return parts.pop()?.split(';').shift() || null
    }
    
    return null
  }

  private setCookie(name: string, value: string, days: number) {
    if (typeof document === 'undefined') return
    
    const expires = new Date()
    expires.setTime(expires.getTime() + (days * 24 * 60 * 60 * 1000))
    
    document.cookie = `${name}=${value};expires=${expires.toUTCString()};path=/;SameSite=Lax`
  }

  private loadFromCookies() {
    if (typeof document === 'undefined') return
    
    // Look for AB test cookies
    const cookies = document.cookie.split(';')
    cookies.forEach(cookie => {
      const [name, value] = cookie.trim().split('=')
      if (name.startsWith('ab_')) {
        const testName = name.substring(3)
        this.variants.set(testName, {
          test: testName,
          variant: value,
          assignedAt: new Date().toISOString()
        })
      }
    })
  }

  private randomVariant(variants: string[]): string {
    return variants[Math.floor(Math.random() * variants.length)]
  }
}

// Singleton instance
let abTestingClient: ABTestingClient | null = null

/**
 * Get the AB testing client instance
 */
export function getABTestingClient(): ABTestingClient {
  if (!abTestingClient) {
    abTestingClient = new ABTestingClient()
  }
  return abTestingClient
}

/**
 * React hook for AB testing
 */
export function useABTest(config: ABTestConfig): {
  variant: string | null
  loading: boolean
  trackConversion: (conversionType?: string) => void
} {
  const [variant, setVariant] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  
  React.useEffect(() => {
    const client = getABTestingClient()
    
    client.getVariant(config).then(v => {
      setVariant(v)
      setLoading(false)
    })
  }, [config])
  
  const trackConversion = React.useCallback((conversionType?: string) => {
    const client = getABTestingClient()
    client.trackConversion(config.testName, conversionType || 'default')
  }, [config])
  
  return { variant, loading, trackConversion }
}

/**
 * React component for conditional rendering based on variant
 */
export function ABTestVariant({ 
  test, 
  variant, 
  children 
}: { 
  test: string
  variant: string
  children: React.ReactNode 
}) {
  const client = getABTestingClient()
  
  if (client.isVariant(test, variant)) {
    return <>{children}</>
  }
  
  return null
}

// Export types
type Variant = string
export type { Variant, ABTestConfig }

// Common test configurations
export const AB_TESTS = {
  LANDING_HERO: {
    testName: 'landing_hero_v1',
    variants: ['A', 'B'],
    cookieExpiry: 30
  },
  ONBOARDING_FLOW: {
    testName: 'onboarding_v1',
    variants: ['simple', 'guided', 'interactive'],
    cookieExpiry: 7
  }
} as const
