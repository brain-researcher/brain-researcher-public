'use client'

import * as React from "react"

export interface AccessibilitySettings {
  /** High contrast mode enabled */
  highContrast: boolean
  /** Reduced motion preference */
  reduceMotion: boolean
  /** Font size scale (1.0 = default, 1.2 = 120%, etc.) */
  fontSize: number
  /** Focus indicator style */
  focusIndicator: 'default' | 'high-visibility' | 'custom'
  /** Screen reader announcements enabled */
  announcements: boolean
}

export interface AccessibilityContextType {
  settings: AccessibilitySettings
  updateSettings: (settings: Partial<AccessibilitySettings>) => void
  announce: (message: string, priority?: 'polite' | 'assertive') => void
}

const defaultSettings: AccessibilitySettings = {
  highContrast: false,
  reduceMotion: false,
  fontSize: 1.0,
  focusIndicator: 'default',
  announcements: true
}

const AccessibilityContext = React.createContext<AccessibilityContextType | null>(null)

export interface AccessibilityProviderProps {
  children: React.ReactNode
  /** Initial settings */
  initialSettings?: Partial<AccessibilitySettings>
}

/**
 * Provider for accessibility settings and utilities
 * Manages global accessibility state and provides announcement functions
 */
export function AccessibilityProvider({ 
  children, 
  initialSettings = {} 
}: AccessibilityProviderProps) {
  const [settings, setSettings] = React.useState<AccessibilitySettings>({
    ...defaultSettings,
    ...initialSettings
  })

  const [announceQueue, setAnnounceQueue] = React.useState<{
    message: string
    priority: 'polite' | 'assertive'
    id: string
  }[]>([])

  // Load settings from localStorage on mount
  React.useEffect(() => {
    try {
      const saved = localStorage.getItem('accessibility-settings')
      if (saved) {
        const parsedSettings = JSON.parse(saved)
        setSettings(prev => ({ ...prev, ...parsedSettings }))
      }
    } catch (error) {
      console.warn('Failed to load accessibility settings:', error)
    }
  }, [])

  // Save settings to localStorage when changed
  const updateSettings = React.useCallback((newSettings: Partial<AccessibilitySettings>) => {
    setSettings(prev => {
      const updated = { ...prev, ...newSettings }
      try {
        localStorage.setItem('accessibility-settings', JSON.stringify(updated))
      } catch (error) {
        console.warn('Failed to save accessibility settings:', error)
      }
      return updated
    })
  }, [])

  // Announce messages to screen readers
  const announce = React.useCallback((message: string, priority: 'polite' | 'assertive' = 'polite') => {
    if (!settings.announcements || !message.trim()) return

    const id = Math.random().toString(36).substr(2, 9)
    setAnnounceQueue(prev => [...prev, { message, priority, id }])

    // Auto-remove after announcement
    setTimeout(() => {
      setAnnounceQueue(prev => prev.filter(item => item.id !== id))
    }, 1000)
  }, [settings.announcements])

  // Apply settings to document
  React.useEffect(() => {
    const root = document.documentElement

    // High contrast
    root.classList.toggle('high-contrast', settings.highContrast)
    
    // Reduced motion
    root.classList.toggle('reduce-motion', settings.reduceMotion)
    
    // Font size
    root.style.setProperty('--font-size-scale', settings.fontSize.toString())
    
    // Focus indicator
    root.setAttribute('data-focus-indicator', settings.focusIndicator)

    // Media query overrides
    if (settings.reduceMotion) {
      root.style.setProperty('--animation-duration', '0.01ms')
      root.style.setProperty('--transition-duration', '0.01ms')
    } else {
      root.style.removeProperty('--animation-duration')
      root.style.removeProperty('--transition-duration')
    }
  }, [settings])

  // Detect user preferences
  React.useEffect(() => {
    const mediaQueries = {
      highContrast: window.matchMedia('(prefers-contrast: more)'),
      reduceMotion: window.matchMedia('(prefers-reduced-motion: reduce)')
    }

    const handleHighContrastChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem('accessibility-settings')) {
        updateSettings({ highContrast: e.matches })
      }
    }

    const handleReduceMotionChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem('accessibility-settings')) {
        updateSettings({ reduceMotion: e.matches })
      }
    }

    mediaQueries.highContrast.addEventListener('change', handleHighContrastChange)
    mediaQueries.reduceMotion.addEventListener('change', handleReduceMotionChange)

    // Set initial values if no saved settings
    if (!localStorage.getItem('accessibility-settings')) {
      updateSettings({
        highContrast: mediaQueries.highContrast.matches,
        reduceMotion: mediaQueries.reduceMotion.matches
      })
    }

    return () => {
      mediaQueries.highContrast.removeEventListener('change', handleHighContrastChange)
      mediaQueries.reduceMotion.removeEventListener('change', handleReduceMotionChange)
    }
  }, [updateSettings])

  const contextValue = React.useMemo(() => ({
    settings,
    updateSettings,
    announce
  }), [settings, updateSettings, announce])

  return (
    <AccessibilityContext.Provider value={contextValue}>
      {children}
      
      {/* Live regions for announcements */}
      {announceQueue.map(({ message, priority, id }) => (
        <div
          key={id}
          role="status"
          aria-live={priority}
          aria-atomic="true"
          className="sr-only"
        >
          {message}
        </div>
      ))}
    </AccessibilityContext.Provider>
  )
}

/**
 * Hook to access accessibility context
 */
export function useAccessibility() {
  const context = React.useContext(AccessibilityContext)
  if (!context) {
    throw new Error('useAccessibility must be used within an AccessibilityProvider')
  }
  return context
}