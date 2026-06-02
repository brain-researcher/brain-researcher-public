'use client'

import { useCallback } from 'react'

// Advanced mode is always on. The basic/advanced toggle was removed; this hook
// is kept as a stable no-op so existing consumers keep working without changes.
export function useAdvancedMode() {
  const setEnabled = useCallback(() => {}, [])
  return { allowed: true, enabled: true, hydrated: true, setEnabled }
}
