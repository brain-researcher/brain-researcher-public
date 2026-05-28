'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

const PREFS_STORAGE_KEY = 'br:settings:preferences'

type StoredPreferences = {
  advancedMode?: boolean
}

function policyDisablesAdvancedMode(): boolean {
  const raw = process.env.NEXT_PUBLIC_DISABLE_ADVANCED_MODE
  if (!raw) return false
  const normalized = raw.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

function loadStoredAdvancedMode(): boolean {
  if (typeof window === 'undefined') return true
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY)
    if (!raw) return true
    const parsed = JSON.parse(raw) as StoredPreferences
    if (typeof parsed.advancedMode === 'undefined') return true
    return Boolean(parsed.advancedMode)
  } catch {
    return true
  }
}

function persistAdvancedMode(enabled: boolean) {
  if (typeof window === 'undefined') return
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    parsed.advancedMode = enabled
    window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(parsed))
  } catch {
    // ignore
  }
}

export function useAdvancedMode() {
  const allowed = useMemo(() => !policyDisablesAdvancedMode(), [])
  const [enabled, setEnabled] = useState(true)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    setHydrated(true)
    if (!allowed) {
      setEnabled(false)
      return
    }
    setEnabled(loadStoredAdvancedMode())
  }, [allowed])

  const update = useCallback(
    (next: boolean) => {
      if (!allowed) {
        setEnabled(false)
        persistAdvancedMode(false)
        return
      }
      setEnabled(next)
      persistAdvancedMode(next)
    },
    [allowed],
  )

  return { allowed, enabled, hydrated, setEnabled: update }
}
