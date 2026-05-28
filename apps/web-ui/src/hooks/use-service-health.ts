'use client'

import { useEffect, useState } from 'react'
import { serviceEndpoints } from '@/lib/service-endpoints'

type HealthState = 'unknown' | 'online' | 'offline'

export function useServiceHealth() {
  const [kg, setKg] = useState<HealthState>('unknown')

  useEffect(() => {
    let cancelled = false

    const check = async () => {
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 4000)
        const res = await fetch(serviceEndpoints.kg('/health'), { signal: controller.signal, cache: 'no-store' })
        clearTimeout(timeout)
        if (!cancelled) setKg(res.ok ? 'online' : 'offline')
      } catch {
        if (!cancelled) setKg('offline')
      }
    }

    check()
    const id = setInterval(check, 15000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return { kg }
}
