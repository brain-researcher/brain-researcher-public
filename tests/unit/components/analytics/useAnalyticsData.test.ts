/**
 * @jest-environment jsdom
 */
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAnalyticsData } from '@/hooks/useAnalyticsData'
import { AnalyticsFilter, TimeRange } from '@/types/analytics'

// Mock setTimeout and clearTimeout
jest.useFakeTimers()

describe('useAnalyticsData', () => {
  const mockTimeRange: TimeRange = {
    label: 'Last 7 Days',
    value: '7d',
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
    end: new Date()
  }

  const mockFilter: AnalyticsFilter = {
    timeRange: mockTimeRange,
    userSegment: undefined,
    dataSource: undefined,
    customFilters: {}
  }

  beforeEach(() => {
    jest.clearAllTimers()
    jest.clearAllMocks()
  })

  afterEach(() => {
    jest.runOnlyPendingTimers()
    jest.useRealTimers()
    jest.useFakeTimers()
  })

  describe('Initial State', () => {
    it('returns initial state correctly', () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter)
      )

      expect(result.current.metrics).toBeNull()
      expect(result.current.loading).toBe(false) // Will be set to true during fetch
      expect(result.current.error).toBeNull()
      expect(result.current.lastUpdated).toBeNull()
      expect(typeof result.current.refreshData).toBe('function')
      expect(typeof result.current.setRealTime).toBe('function')
    })
  })

  describe('Data Fetching', () => {
    it('fetches data on mount', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter)
      )

      // Initially loading
      expect(result.current.loading).toBe(false)

      // Wait for the async fetch to complete
      await act(async () => {
        jest.advanceTimersByTime(1500) // Wait longer than the mock API delay
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      }, { timeout: 3000 })

      expect(result.current.loading).toBe(false)
      expect(result.current.error).toBeNull()
      expect(result.current.lastUpdated).not.toBeNull()
    })

    it('handles API errors with retry logic', async () => {
      // Mock Math.random to force an error
      const originalRandom = Math.random
      Math.random = jest.fn().mockReturnValue(0.01) // Force error (< 0.05)

      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { retryAttempts: 2, retryDelay: 100 })
      )

      await act(async () => {
        jest.advanceTimersByTime(2000)
      })

      // Should have retried and eventually failed
      await waitFor(() => {
        expect(result.current.error).toContain('Network error')
      }, { timeout: 5000 })

      expect(result.current.metrics).toBeNull()
      expect(result.current.loading).toBe(false)

      // Restore Math.random
      Math.random = originalRandom
    })

    it('succeeds after retries', async () => {
      let callCount = 0
      const originalRandom = Math.random
      Math.random = jest.fn(() => {
        callCount++
        return callCount <= 2 ? 0.01 : 0.5 // Fail first 2 times, then succeed
      })

      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { retryAttempts: 3, retryDelay: 100 })
      )

      await act(async () => {
        jest.advanceTimersByTime(5000)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      }, { timeout: 6000 })

      expect(result.current.error).toBeNull()
      expect(result.current.loading).toBe(false)

      Math.random = originalRandom
    })
  })

  describe('Real-time Updates', () => {
    it('enables real-time updates when configured', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: true, 
          refreshInterval: 1000 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const initialLastUpdated = result.current.lastUpdated

      // Advance time to trigger refresh
      await act(async () => {
        jest.advanceTimersByTime(1000)
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBe(initialLastUpdated)
      }, { timeout: 3000 })
    })

    it('disables real-time updates when configured', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: false, 
          refreshInterval: 1000 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const initialLastUpdated = result.current.lastUpdated

      // Advance time - should not trigger refresh
      await act(async () => {
        jest.advanceTimersByTime(2000)
      })

      // Last updated should remain the same
      expect(result.current.lastUpdated).toBe(initialLastUpdated)
    })

    it('pauses real-time updates when loading', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: true, 
          refreshInterval: 500 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      // Trigger manual refresh to set loading state
      act(() => {
        result.current.refreshData()
      })

      expect(result.current.loading).toBe(true)

      // Advance time - should not trigger additional refresh while loading
      const callCount = jest.fn()
      const originalFetch = (global as any).fetch
      ;(global as any).fetch = callCount

      await act(async () => {
        jest.advanceTimersByTime(1000)
      })

      // Should not have made additional calls while loading
      expect(callCount).not.toHaveBeenCalled()

      ;(global as any).fetch = originalFetch
    })
  })

  describe('Manual Refresh', () => {
    it('refreshes data when refreshData is called', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter)
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const initialLastUpdated = result.current.lastUpdated

      // Wait a bit
      await act(async () => {
        jest.advanceTimersByTime(500)
      })

      // Manual refresh
      await act(async () => {
        result.current.refreshData()
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBe(initialLastUpdated)
      })
    })
  })

  describe('Filter Changes', () => {
    it('refetches data when filter changes', async () => {
      const { result, rerender } = renderHook(
        ({ filter }) => useAnalyticsData(filter),
        { initialProps: { filter: mockFilter } }
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const initialLastUpdated = result.current.lastUpdated

      // Change filter
      const newFilter = {
        ...mockFilter,
        userSegment: 'researchers'
      }

      rerender({ filter: newFilter })

      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBe(initialLastUpdated)
      })
    })
  })

  describe('Real-time Control', () => {
    it('enables real-time updates via setRealTime', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: false, 
          refreshInterval: 1000 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      // Enable real-time
      act(() => {
        result.current.setRealTime(true)
      })

      const initialLastUpdated = result.current.lastUpdated

      // Should now update automatically
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBe(initialLastUpdated)
      }, { timeout: 3000 })
    })

    it('disables real-time updates via setRealTime', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: true, 
          refreshInterval: 1000 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      // Disable real-time
      act(() => {
        result.current.setRealTime(false)
      })

      const initialLastUpdated = result.current.lastUpdated

      // Should not update automatically
      await act(async () => {
        jest.advanceTimersByTime(2000)
      })

      expect(result.current.lastUpdated).toBe(initialLastUpdated)
    })
  })

  describe('Cleanup', () => {
    it('cleans up intervals and timeouts on unmount', async () => {
      const clearIntervalSpy = jest.spyOn(global, 'clearInterval')
      const clearTimeoutSpy = jest.spyOn(global, 'clearTimeout')

      const { result, unmount } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: true, 
          refreshInterval: 1000 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      // Unmount
      unmount()

      // Should have cleaned up
      expect(clearIntervalSpy).toHaveBeenCalled()

      clearIntervalSpy.mockRestore()
      clearTimeoutSpy.mockRestore()
    })

    it('aborts pending requests on unmount', async () => {
      const abortSpy = jest.fn()
      const mockAbortController = {
        signal: { aborted: false },
        abort: abortSpy
      }

      ;(global as any).AbortController = jest.fn(() => mockAbortController)

      const { unmount } = renderHook(() => 
        useAnalyticsData(mockFilter)
      )

      // Unmount before request completes
      unmount()

      expect(abortSpy).toHaveBeenCalled()
    })
  })

  describe('Options Configuration', () => {
    it('uses custom retry configuration', async () => {
      const originalRandom = Math.random
      Math.random = jest.fn().mockReturnValue(0.01) // Force error

      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          retryAttempts: 1, 
          retryDelay: 50 
        })
      )

      await act(async () => {
        jest.advanceTimersByTime(200)
      })

      await waitFor(() => {
        expect(result.current.error).toContain('Network error')
      }, { timeout: 1000 })

      Math.random = originalRandom
    })

    it('uses custom refresh interval', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter, { 
          realTime: true, 
          refreshInterval: 500 
        })
      )

      // Initial fetch
      await act(async () => {
        jest.advanceTimersByTime(1000)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const initialLastUpdated = result.current.lastUpdated

      // Should refresh after 500ms
      await act(async () => {
        jest.advanceTimersByTime(500)
      })

      await waitFor(() => {
        expect(result.current.lastUpdated).not.toBe(initialLastUpdated)
      }, { timeout: 2000 })
    })
  })

  describe('Data Structure', () => {
    it('returns properly structured analytics metrics', async () => {
      const { result } = renderHook(() => 
        useAnalyticsData(mockFilter)
      )

      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const metrics = result.current.metrics!
      
      expect(metrics.usage).toBeDefined()
      expect(metrics.performance).toBeDefined()
      expect(metrics.research).toBeDefined()
      expect(metrics.system).toBeDefined()
      expect(metrics.engagement).toBeDefined()

      // Check usage metrics structure
      expect(typeof metrics.usage.totalUsers).toBe('number')
      expect(typeof metrics.usage.activeUsers).toBe('number')
      expect(Array.isArray(metrics.usage.topPages)).toBe(true)
      expect(Array.isArray(metrics.usage.userGrowth)).toBe(true)

      // Check performance metrics structure
      expect(typeof metrics.performance.avgResponseTime).toBe('number')
      expect(typeof metrics.performance.successRate).toBe('number')
      expect(Array.isArray(metrics.performance.responseTimeHistory)).toBe(true)

      // Check research metrics structure
      expect(typeof metrics.research.analysesRun).toBe('number')
      expect(metrics.research.datasetsUsed instanceof Map).toBe(true)
      expect(metrics.research.toolsUsed instanceof Map).toBe(true)

      // Check system metrics structure
      expect(typeof metrics.system.cpuUsage).toBe('number')
      expect(typeof metrics.system.memoryUsage).toBe('number')
      expect(Array.isArray(metrics.system.resourceHistory)).toBe(true)

      // Check engagement metrics structure
      expect(typeof metrics.engagement.dailyActiveUsers).toBe('number')
      expect(Array.isArray(metrics.engagement.conversionFunnels)).toBe(true)
      expect(Array.isArray(metrics.engagement.featureAdoption)).toBe(true)
    })

    it('generates time-based data correctly', async () => {
      const longTimeRange: TimeRange = {
        label: 'Last 30 Days',
        value: '30d',
        start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
        end: new Date()
      }

      const longFilter: AnalyticsFilter = {
        timeRange: longTimeRange,
        userSegment: undefined,
        dataSource: undefined,
        customFilters: {}
      }

      const { result } = renderHook(() => 
        useAnalyticsData(longFilter)
      )

      await act(async () => {
        jest.advanceTimersByTime(1500)
      })

      await waitFor(() => {
        expect(result.current.metrics).not.toBeNull()
      })

      const metrics = result.current.metrics!
      
      // Should have more data points for longer time range
      expect(metrics.usage.userGrowth.length).toBeGreaterThan(7)
      expect(metrics.performance.responseTimeHistory.length).toBeGreaterThan(0)
      expect(metrics.system.resourceHistory.length).toBeGreaterThan(0)
    })
  })
})