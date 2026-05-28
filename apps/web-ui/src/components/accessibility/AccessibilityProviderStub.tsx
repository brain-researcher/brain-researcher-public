'use client'

import React, { createContext, useContext, useState, useCallback } from 'react'

interface AccessibilitySettings {
  announcements: boolean
  highContrast: boolean
  reducedMotion: boolean
  fontSize: number
}

interface AccessibilityContextType {
  settings: AccessibilitySettings
  announce: (message: string, priority?: 'polite' | 'assertive') => void
  updateSettings: (settings: Partial<AccessibilitySettings>) => void
}

const defaultSettings: AccessibilitySettings = {
  announcements: true,
  highContrast: false,
  reducedMotion: false,
  fontSize: 1.0
}

const AccessibilityContext = createContext<AccessibilityContextType>({
  settings: defaultSettings,
  announce: () => {},
  updateSettings: () => {}
})

export function AccessibilityProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AccessibilitySettings>(defaultSettings)

  const announce = useCallback((message: string, priority: 'polite' | 'assertive' = 'polite') => {
    // Stub implementation - just log for now
    if (settings.announcements) {
      console.log(`[Accessibility ${priority}]:`, message)
    }
  }, [settings.announcements])

  const updateSettings = useCallback((newSettings: Partial<AccessibilitySettings>) => {
    setSettings(prev => ({ ...prev, ...newSettings }))
  }, [])

  return (
    <AccessibilityContext.Provider value={{ settings, announce, updateSettings }}>
      {children}
    </AccessibilityContext.Provider>
  )
}

export function useAccessibility() {
  const context = useContext(AccessibilityContext)
  if (!context) {
    // Return safe defaults instead of throwing
    return {
      settings: defaultSettings,
      announce: () => {},
      updateSettings: () => {}
    }
  }
  return context
}

// Export stub components that won't break
export function LiveRegion({ children }: { children: React.ReactNode }) {
  return <div aria-live="polite" aria-atomic="true" className="sr-only">{children}</div>
}

export function ScreenReaderOnly({ children }: { children: React.ReactNode }) {
  return <span className="sr-only">{children}</span>
}