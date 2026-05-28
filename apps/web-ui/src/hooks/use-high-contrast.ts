'use client'

import { useEffect, useState, useCallback } from 'react'
import { useAccessibility } from '@/components/accessibility'

/**
 * Hook for managing high contrast mode and color preferences
 */
export function useHighContrast() {
  const { settings, updateSettings } = useAccessibility()
  const [systemPreference, setSystemPreference] = useState(false)

  // Detect system preference for high contrast
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-contrast: more)')
    
    const handleChange = (e: MediaQueryListEvent) => {
      setSystemPreference(e.matches)
    }

    setSystemPreference(mediaQuery.matches)
    mediaQuery.addEventListener('change', handleChange)

    return () => {
      mediaQuery.removeEventListener('change', handleChange)
    }
  }, [])

  const toggle = useCallback(() => {
    updateSettings({ highContrast: !settings.highContrast })
  }, [settings.highContrast, updateSettings])

  const enable = useCallback(() => {
    updateSettings({ highContrast: true })
  }, [updateSettings])

  const disable = useCallback(() => {
    updateSettings({ highContrast: false })
  }, [updateSettings])

  const isEnabled = settings.highContrast || systemPreference

  return {
    isEnabled,
    isEnabledManually: settings.highContrast,
    systemPreference,
    toggle,
    enable,
    disable
  }
}

/**
 * Hook for managing reduced motion preferences
 */
export function useReducedMotion() {
  const { settings, updateSettings } = useAccessibility()
  const [systemPreference, setSystemPreference] = useState(false)

  // Detect system preference for reduced motion
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    
    const handleChange = (e: MediaQueryListEvent) => {
      setSystemPreference(e.matches)
    }

    setSystemPreference(mediaQuery.matches)
    mediaQuery.addEventListener('change', handleChange)

    return () => {
      mediaQuery.removeEventListener('change', handleChange)
    }
  }, [])

  const toggle = useCallback(() => {
    updateSettings({ reducedMotion: !settings.reducedMotion })
  }, [settings.reducedMotion, updateSettings])

  const enable = useCallback(() => {
    updateSettings({ reducedMotion: true })
  }, [updateSettings])

  const disable = useCallback(() => {
    updateSettings({ reducedMotion: false })
  }, [updateSettings])

  const isEnabled = settings.reducedMotion || systemPreference

  return {
    isEnabled,
    isEnabledManually: settings.reducedMotion,
    systemPreference,
    toggle,
    enable,
    disable
  }
}

/**
 * Hook for managing font size scaling
 */
export function useFontSize() {
  const { settings, updateSettings } = useAccessibility()

  const increase = useCallback(() => {
    const newSize = Math.min(settings.fontSize + 0.1, 2.0)
    updateSettings({ fontSize: newSize })
  }, [settings.fontSize, updateSettings])

  const decrease = useCallback(() => {
    const newSize = Math.max(settings.fontSize - 0.1, 0.8)
    updateSettings({ fontSize: newSize })
  }, [settings.fontSize, updateSettings])

  const reset = useCallback(() => {
    updateSettings({ fontSize: 1.0 })
  }, [updateSettings])

  const setSize = useCallback((size: number) => {
    const clampedSize = Math.max(0.8, Math.min(2.0, size))
    updateSettings({ fontSize: clampedSize })
  }, [updateSettings])

  return {
    fontSize: settings.fontSize,
    increase,
    decrease,
    reset,
    setSize,
    isDefault: settings.fontSize === 1.0,
    percentage: Math.round(settings.fontSize * 100)
  }
}