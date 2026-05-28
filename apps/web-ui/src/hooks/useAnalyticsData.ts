'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { AnalyticsMetrics, AnalyticsFilter } from '@/types/analytics'

interface UseAnalyticsDataOptions {
  realTime?: boolean
  refreshInterval?: number // milliseconds
  retryAttempts?: number
  retryDelay?: number // milliseconds
}

interface UseAnalyticsDataReturn {
  metrics: AnalyticsMetrics | null
  loading: boolean
  error: string | null
  lastUpdated: Date | null
  refreshData: () => void
  setRealTime: (enabled: boolean) => void
}

const TELEMETRY_BASE =
  process.env.NEXT_PUBLIC_TELEMETRY_API ||
  '/api/telemetry'

async function fetchAnalyticsData(filter: AnalyticsFilter, signal?: AbortSignal): Promise<AnalyticsMetrics> {
  const payload = {
    start_time: filter.timeRange.start.toISOString(),
    end_time: filter.timeRange.end.toISOString(),
    granularity: 'day',
    services: ['web_ui', 'orchestrator', 'agent', 'kg'],
    metric_types: ['usage', 'performance', 'engagement', 'system', 'research'],
    dimensions: filter.customFilters || {},
  }

  const response = await fetch(`${TELEMETRY_BASE}/metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }

  const data = await response.json()

  // Expecting { metrics: AnalyticsMetrics } shape from telemetry API
  return data.metrics as AnalyticsMetrics
}

export function useAnalyticsData(
  filter: AnalyticsFilter,
  options: UseAnalyticsDataOptions = {}
): UseAnalyticsDataReturn {
  const {
    realTime = false,
    refreshInterval = 30000,
    retryAttempts = 3,
    retryDelay = 1000
  } = options

  const [metrics, setMetrics] = useState<AnalyticsMetrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [isRealTimeEnabled, setIsRealTimeEnabled] = useState(realTime)

  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async (retryCount = 0): Promise<void> => {
    // Cancel any pending requests
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    abortControllerRef.current = new AbortController()
    setLoading(true)
    setError(null)

    try {
      const data = await fetchAnalyticsData(filter, abortControllerRef.current.signal)
      
      // Check if request was aborted
      if (abortControllerRef.current.signal.aborted) {
        return
      }

      setMetrics(data)
      setLastUpdated(new Date())
      setError(null)
    } catch (err) {
      // Check if request was aborted
      if (abortControllerRef.current.signal.aborted) {
        return
      }

      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch analytics data'
      
      if (retryCount < retryAttempts) {
        // Retry with exponential backoff
        const delay = retryDelay * Math.pow(2, retryCount)
        retryTimeoutRef.current = setTimeout(() => {
          fetchData(retryCount + 1)
        }, delay)
      } else {
        setError(errorMessage)
      }
    } finally {
      setLoading(false)
    }
  }, [filter, retryAttempts, retryDelay])

  const refreshData = useCallback(() => {
    fetchData()
  }, [fetchData])

  const setRealTime = useCallback((enabled: boolean) => {
    setIsRealTimeEnabled(enabled)
  }, [])

  // Initial data fetch and filter change handling
  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Real-time data updates
  useEffect(() => {
    if (!isRealTimeEnabled) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    intervalRef.current = setInterval(() => {
      if (!loading) {
        fetchData()
      }
    }, refreshInterval)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [isRealTimeEnabled, refreshInterval, fetchData, loading])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current)
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])

  return {
    metrics,
    loading,
    error,
    lastUpdated,
    refreshData,
    setRealTime
  }
}
