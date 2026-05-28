'use client'

import { useState, useEffect, useCallback } from 'react'
import { 
  AnalyticsMetrics, 
  AnalyticsFilter, 
  AnalyticsDashboardState, 
  TimeRange,
  CustomReport,
  AlertConfig,
  ResearchMetrics
} from '@/types/analytics'
import { serviceEndpoints } from '@/lib/service-endpoints'

// Default time ranges
export const DEFAULT_TIME_RANGES: TimeRange[] = [
  {
    label: 'Last 24 hours',
    value: '24h',
    start: new Date(Date.now() - 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 7 days',
    value: '7d',
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 30 days',
    value: '30d',
    start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
    end: new Date()
  },
  {
    label: 'Last 90 days',
    value: '90d',
    start: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000),
    end: new Date()
  }
]

const DEFAULT_FILTER: AnalyticsFilter = {
  timeRange: DEFAULT_TIME_RANGES[1], // Last 7 days
}

const coerceMap = (value: unknown): Map<string, number> => {
  if (value instanceof Map) return value
  if (Array.isArray(value)) {
    return new Map(value as Array<[string, number]>)
  }
  if (value && typeof value === 'object') {
    return new Map(Object.entries(value as Record<string, number>))
  }
  return new Map()
}

const normalizeResearchMetrics = (raw: ResearchMetrics): ResearchMetrics => ({
  ...raw,
  datasetsUsed: coerceMap(raw.datasetsUsed),
  toolsUsed: coerceMap(raw.toolsUsed)
})

export function useAnalytics() {
  const [state, setState] = useState<AnalyticsDashboardState>({
    metrics: null,
    loading: false,
    error: null,
    filter: DEFAULT_FILTER,
    realTimeEnabled: false,
    customReports: [],
    alerts: [],
    lastUpdated: null
  })

  // Fetch analytics data
  const fetchMetrics = useCallback(async (filter: AnalyticsFilter) => {
    setState(prev => ({ ...prev, loading: true, error: null }))
    
    try {
      const params = new URLSearchParams({
        start: filter.timeRange.start.toISOString(),
        end: filter.timeRange.end.toISOString(),
        ...(filter.userSegment && { segment: filter.userSegment }),
        ...(filter.dataSource && { source: filter.dataSource })
      })

      const paramsString = params.toString()
      const withQuery = (path: string) =>
        serviceEndpoints.orchestrator(paramsString ? `${path}?${paramsString}` : path)

      const [usageRes, performanceRes, researchRes, systemRes] = await Promise.all([
        fetch(withQuery('/api/analytics/usage')),
        fetch(withQuery('/api/analytics/performance')),
        fetch(withQuery('/api/analytics/research')),
        fetch(withQuery('/api/analytics/system'))
      ])

      if (!usageRes.ok || !performanceRes.ok || !researchRes.ok || !systemRes.ok) {
        throw new Error('Failed to fetch analytics data')
      }

      const [usage, performance, research, system] = await Promise.all([
        usageRes.json(),
        performanceRes.json(),
        researchRes.json(),
        systemRes.json()
      ])

      // Fetch engagement metrics
      const engagementRes = await fetch(withQuery('/api/analytics/engagement'))
      const engagement = engagementRes.ok ? await engagementRes.json() : {}

      const metrics: AnalyticsMetrics = {
        usage,
        performance,
        research: normalizeResearchMetrics(research),
        system,
        engagement
      }

      setState(prev => ({
        ...prev,
        metrics,
        loading: false,
        lastUpdated: new Date()
      }))
    } catch (error) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch analytics data',
        metrics: null,
        lastUpdated: null
      }))
    }
  }, [])

  // Update filter and fetch data
  const updateFilter = useCallback((newFilter: Partial<AnalyticsFilter>) => {
    const updatedFilter = { ...state.filter, ...newFilter }
    setState(prev => ({ ...prev, filter: updatedFilter }))
    fetchMetrics(updatedFilter)
  }, [state.filter, fetchMetrics])

  // Set time range
  const setTimeRange = useCallback((timeRange: TimeRange) => {
    updateFilter({ timeRange })
  }, [updateFilter])

  // Toggle real-time updates
  const toggleRealTime = useCallback(() => {
    setState(prev => ({ ...prev, realTimeEnabled: !prev.realTimeEnabled }))
  }, [])

  // Refresh data
  const refresh = useCallback(() => {
    fetchMetrics(state.filter)
  }, [fetchMetrics, state.filter])

  // Export data
  const exportData = useCallback(async (format: 'csv' | 'pdf' | 'json' | 'png', options?: any) => {
    try {
      const params = new URLSearchParams({
        format,
        start: state.filter.timeRange.start.toISOString(),
        end: state.filter.timeRange.end.toISOString()
      })

      const paramsString = params.toString()
      const exportUrl = serviceEndpoints.orchestrator(
        paramsString ? `/api/analytics/export?${paramsString}` : '/api/analytics/export'
      )
      const response = await fetch(exportUrl)
      
      if (!response.ok) {
        throw new Error('Export failed')
      }

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `analytics-${Date.now()}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Export failed:', error)
    }
  }, [state.filter])

  // Manage custom reports
  const createReport = useCallback(async (report: Omit<CustomReport, 'id' | 'createdAt' | 'updatedAt'>) => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/analytics/reports'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(report)
      })

      if (!response.ok) throw new Error('Failed to create report')
      
      const newReport = await response.json()
      setState(prev => ({
        ...prev,
        customReports: [...prev.customReports, newReport]
      }))
      
      return newReport
    } catch (error) {
      console.error('Create report failed:', error)
      throw error
    }
  }, [])

  const updateReport = useCallback(async (id: string, updates: Partial<CustomReport>) => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator(`/api/analytics/reports/${id}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })

      if (!response.ok) throw new Error('Failed to update report')
      
      const updatedReport = await response.json()
      setState(prev => ({
        ...prev,
        customReports: prev.customReports.map(r => 
          r.id === id ? updatedReport : r
        )
      }))
    } catch (error) {
      console.error('Update report failed:', error)
      throw error
    }
  }, [])

  const deleteReport = useCallback(async (id: string) => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator(`/api/analytics/reports/${id}`), {
        method: 'DELETE'
      })

      if (!response.ok) throw new Error('Failed to delete report')
      
      setState(prev => ({
        ...prev,
        customReports: prev.customReports.filter(r => r.id !== id)
      }))
    } catch (error) {
      console.error('Delete report failed:', error)
      throw error
    }
  }, [])

  // Manage alerts
  const createAlert = useCallback(async (alert: Omit<AlertConfig, 'id'>) => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/analytics/alerts'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(alert)
      })

      if (!response.ok) throw new Error('Failed to create alert')
      
      const newAlert = await response.json()
      setState(prev => ({
        ...prev,
        alerts: [...prev.alerts, newAlert]
      }))
      
      return newAlert
    } catch (error) {
      console.error('Create alert failed:', error)
      throw error
    }
  }, [])

  const updateAlert = useCallback(async (id: string, updates: Partial<AlertConfig>) => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator(`/api/analytics/alerts/${id}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })

      if (!response.ok) throw new Error('Failed to update alert')
      
      const updatedAlert = await response.json()
      setState(prev => ({
        ...prev,
        alerts: prev.alerts.map(a => 
          a.id === id ? updatedAlert : a
        )
      }))
    } catch (error) {
      console.error('Update alert failed:', error)
      throw error
    }
  }, [])

  // Real-time updates via polling
  useEffect(() => {
    if (!state.realTimeEnabled) return

    let cancelled = false
    const endpoint = serviceEndpoints.orchestrator('/api/analytics/realtime')

    const poll = async () => {
      try {
        const response = await fetch(endpoint)
        if (!response.ok) throw new Error(`Realtime fetch failed: ${response.status}`)
        const update = await response.json()
        if (cancelled) return
        setState(prev => {
          if (!prev.metrics) return prev
          const nextErrorRate = typeof update.errorRate === 'number'
            ? update.errorRate
            : prev.metrics.performance.errorRate
          return {
            ...prev,
            metrics: {
              ...prev.metrics,
              usage: {
                ...prev.metrics.usage,
                activeUsers: update.activeUsers ?? prev.metrics.usage.activeUsers
              },
              performance: {
                ...prev.metrics.performance,
                avgResponseTime: update.responseTime ?? prev.metrics.performance.avgResponseTime,
                throughput: update.requestsPerSecond ?? prev.metrics.performance.throughput,
                errorRate: nextErrorRate,
                successRate: Math.max(0, 100 - nextErrorRate)
              },
              system: {
                ...prev.metrics.system,
                cpuUsage: update.cpuUsage ?? prev.metrics.system.cpuUsage,
                memoryUsage: update.memoryUsage ?? prev.metrics.system.memoryUsage
              }
            },
            lastUpdated: new Date()
          }
        })
      } catch (error) {
        console.error('Realtime analytics polling failed', error)
      }
    }

    poll()
    const interval = setInterval(poll, 5000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [state.realTimeEnabled])

  // Initial data fetch
  useEffect(() => {
    fetchMetrics(state.filter)
  }, [fetchMetrics, state.filter])

  // Fetch reports and alerts on mount
  useEffect(() => {
    const fetchReportsAndAlerts = async () => {
      try {
        const [reportsRes, alertsRes] = await Promise.all([
          fetch(serviceEndpoints.orchestrator('/api/analytics/reports')),
          fetch(serviceEndpoints.orchestrator('/api/analytics/alerts'))
        ])

        if (reportsRes.ok) {
          const reports = await reportsRes.json()
          setState(prev => ({ ...prev, customReports: reports }))
        }

        if (alertsRes.ok) {
          const alerts = await alertsRes.json()
          setState(prev => ({ ...prev, alerts }))
        }
      } catch (error) {
        console.error('Failed to fetch reports and alerts:', error)
      }
    }

    fetchReportsAndAlerts()
  }, [])

  return {
    ...state,
    updateFilter,
    setTimeRange,
    toggleRealTime,
    refresh,
    exportData,
    createReport,
    updateReport,
    deleteReport,
    createAlert,
    updateAlert,
    timeRanges: DEFAULT_TIME_RANGES
  }
}
