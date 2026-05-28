/**
 * Hook for fetching and caching RunCard data from the Evidence Rail API.
 *
 * This hook provides a clean interface for components to fetch run cards
 * with proper loading states, error handling, and caching.
 */

import { useState, useEffect, useCallback } from 'react'
import { ChatRunCard } from '@/types/chat'
import { EvidenceRailIntegration } from '@/lib/evidence-rail-integration'

interface UseRunCardOptions {
  /** Whether to fetch immediately on mount (default: true) */
  fetchOnMount?: boolean
  /** Polling interval in ms for auto-refresh (0 = disabled, default: 0) */
  pollInterval?: number
  /** Callback when fetch completes successfully */
  onSuccess?: (runCard: ChatRunCard) => void
  /** Callback when fetch fails */
  onError?: (error: Error) => void
}

interface UseRunCardReturn {
  /** The fetched RunCard data */
  runCard: ChatRunCard | undefined
  /** Whether the data is currently being fetched */
  isLoading: boolean
  /** Error that occurred during fetch */
  error: Error | null
  /** Manually trigger a refetch */
  refetch: () => Promise<void>
  /** Clear the cached data */
  clear: () => void
}

// Module-level cache for run cards (simple in-memory cache)
const runCardCache = new Map<string, { data: ChatRunCard; timestamp: number }>()
const CACHE_TTL_MS = 60 * 1000 // 1 minute cache TTL

/**
 * Hook to fetch a RunCard by job ID
 *
 * @param jobId - The job ID to fetch the run card for
 * @param options - Configuration options
 * @returns Run card data with loading/error states
 *
 * @example
 * ```tsx
 * const { runCard, isLoading, error, refetch } = useRunCard(jobId)
 *
 * if (isLoading) return <Skeleton />
 * if (error) return <ErrorMessage error={error} />
 * if (!runCard) return <EmptyState />
 *
 * return <RunCardDisplay runCard={runCard} />
 * ```
 */
export function useRunCard(
  jobId: string | null | undefined,
  options: UseRunCardOptions = {}
): UseRunCardReturn {
  const {
    fetchOnMount = true,
    pollInterval = 0,
    onSuccess,
    onError,
  } = options

  const [runCard, setRunCard] = useState<ChatRunCard | undefined>(() => {
    // Initialize from cache if available
    if (jobId) {
      const cached = runCardCache.get(jobId)
      if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
        return cached.data
      }
    }
    return undefined
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const fetchRunCard = useCallback(async () => {
    if (!jobId) {
      setRunCard(undefined)
      setError(null)
      return
    }

    // Check cache first
    const cached = runCardCache.get(jobId)
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      setRunCard(cached.data)
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const integration = new EvidenceRailIntegration()
      const data = await integration.getMappedRunCard(jobId)

      // Update cache
      runCardCache.set(jobId, { data, timestamp: Date.now() })

      setRunCard(data)
      onSuccess?.(data)
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to fetch run card')
      setError(error)
      onError?.(error)

      // Clear stale cache entry on error
      runCardCache.delete(jobId)
    } finally {
      setIsLoading(false)
    }
  }, [jobId, onSuccess, onError])

  // Fetch on mount if enabled
  useEffect(() => {
    if (fetchOnMount && jobId) {
      fetchRunCard()
    }
  }, [fetchOnMount, jobId, fetchRunCard])

  // Set up polling if enabled
  useEffect(() => {
    if (pollInterval <= 0 || !jobId) {
      return
    }

    const intervalId = setInterval(fetchRunCard, pollInterval)
    return () => clearInterval(intervalId)
  }, [pollInterval, jobId, fetchRunCard])

  const clear = useCallback(() => {
    setRunCard(undefined)
    setError(null)
    if (jobId) {
      runCardCache.delete(jobId)
    }
  }, [jobId])

  return {
    runCard,
    isLoading,
    error,
    refetch: fetchRunCard,
    clear,
  }
}

/**
 * Invalidate cached run card for a specific job
 */
export function invalidateRunCardCache(jobId: string): void {
  runCardCache.delete(jobId)
}

/**
 * Clear all cached run cards
 */
export function clearRunCardCache(): void {
  runCardCache.clear()
}

export default useRunCard
