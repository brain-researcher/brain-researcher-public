'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useLoading, useLoadingState, useAsyncLoading } from '@/contexts/loading-context'

// Enhanced loading hook with progress tracking
export function useLoadingWithProgress(id: string) {
  const loadingState = useLoadingState(id)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState<string>()
  const intervalRef = useRef<NodeJS.Timeout>()

  const startLoadingWithProgress = useCallback((
    stages: Array<{ name: string; duration: number }>,
    options?: { message?: string }
  ) => {
    setProgress(0)
    setStage(stages[0]?.name)
    
    loadingState.startLoading({
      message: options?.message || 'Loading...',
      progress: 0,
      stage: stages[0]?.name,
      canCancel: true
    })

    // Simulate progress through stages
    let currentStageIndex = 0
    let stageProgress = 0
    const totalDuration = stages.reduce((sum, stage) => sum + stage.duration, 0)
    let elapsed = 0

    intervalRef.current = setInterval(() => {
      elapsed += 100
      const currentStage = stages[currentStageIndex]
      
      if (!currentStage) return

      stageProgress += 100
      const stagePercentage = (stageProgress / currentStage.duration) * 100
      
      // Calculate overall progress
      const completedStagesTime = stages
        .slice(0, currentStageIndex)
        .reduce((sum, stage) => sum + stage.duration, 0)
      
      const overallProgress = ((completedStagesTime + Math.min(stageProgress, currentStage.duration)) / totalDuration) * 100
      
      setProgress(Math.min(overallProgress, 100))
      
      // Update loading state
      loadingState.updateLoading({
        progress: Math.min(overallProgress, 100),
        stage: currentStage.name,
        estimatedTimeRemaining: Math.max(0, totalDuration - elapsed) / 1000
      })

      // Move to next stage
      if (stageProgress >= currentStage.duration && currentStageIndex < stages.length - 1) {
        currentStageIndex++
        stageProgress = 0
        setStage(stages[currentStageIndex]?.name)
      }

      // Complete when all stages done
      if (elapsed >= totalDuration) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current)
        }
        setProgress(100)
        loadingState.updateLoading({ progress: 100 })
        
        // Auto-finish after a short delay
        setTimeout(() => {
          loadingState.finishLoading()
        }, 500)
      }
    }, 100)
  }, [loadingState])

  const stopProgress = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
    }
    loadingState.finishLoading()
  }, [loadingState])

  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [])

  return {
    ...loadingState,
    progress,
    stage,
    startLoadingWithProgress,
    stopProgress
  }
}

// Hook for batch operations with individual progress tracking
export function useBatchLoading(batchId: string) {
  const [items, setItems] = useState<Array<{ id: string; status: 'pending' | 'loading' | 'completed' | 'error'; message?: string; error?: string }>>([])
  const { startLoading, updateLoading, finishLoading } = useLoading()

  const initializeBatch = useCallback((itemIds: string[], message = 'Processing batch...') => {
    const initialItems = itemIds.map(id => ({ id, status: 'pending' as const }))
    setItems(initialItems)
    startLoading(batchId, { message, progress: 0 })
  }, [batchId, startLoading])

  const updateItemStatus = useCallback((
    itemId: string, 
    status: 'loading' | 'completed' | 'error',
    message?: string,
    error?: string
  ) => {
    setItems(prev => {
      const updated = prev.map(item => 
        item.id === itemId 
          ? { ...item, status, message, error }
          : item
      )

      // Calculate overall progress
      const completed = updated.filter(item => item.status === 'completed').length
      const total = updated.length
      const progress = total > 0 ? (completed / total) * 100 : 0

      // Update loading state
      updateLoading(batchId, {
        progress,
        stage: `${completed}/${total} completed`,
        message: status === 'error' ? `Error processing ${itemId}` : message
      })

      // Finish when all items are done
      if (completed === total) {
        setTimeout(() => finishLoading(batchId), 500)
      }

      return updated
    })
  }, [batchId, updateLoading, finishLoading])

  const processBatch = useCallback(async <T>(
    itemIds: string[],
    processor: (itemId: string) => Promise<T>,
    options?: {
      message?: string
      concurrent?: boolean
      maxConcurrent?: number
    }
  ) => {
    const { message = 'Processing batch...', concurrent = false, maxConcurrent = 3 } = options || {}
    
    initializeBatch(itemIds, message)

    const results: Array<{ id: string; result?: T; error?: Error }> = []

    if (concurrent) {
      // Process items concurrently with limit
      const chunks: string[][] = []
      for (let i = 0; i < itemIds.length; i += maxConcurrent) {
        chunks.push(itemIds.slice(i, i + maxConcurrent))
      }

      for (const chunk of chunks) {
        await Promise.allSettled(
          chunk.map(async (itemId) => {
            try {
              updateItemStatus(itemId, 'loading', `Processing ${itemId}...`)
              const result = await processor(itemId)
              updateItemStatus(itemId, 'completed', `Completed ${itemId}`)
              results.push({ id: itemId, result })
            } catch (error) {
              const err = error instanceof Error ? error : new Error('Unknown error')
              updateItemStatus(itemId, 'error', undefined, err.message)
              results.push({ id: itemId, error: err })
            }
          })
        )
      }
    } else {
      // Process items sequentially
      for (const itemId of itemIds) {
        try {
          updateItemStatus(itemId, 'loading', `Processing ${itemId}...`)
          const result = await processor(itemId)
          updateItemStatus(itemId, 'completed', `Completed ${itemId}`)
          results.push({ id: itemId, result })
        } catch (error) {
          const err = error instanceof Error ? error : new Error('Unknown error')
          updateItemStatus(itemId, 'error', undefined, err.message)
          results.push({ id: itemId, error: err })
        }
      }
    }

    return results
  }, [initializeBatch, updateItemStatus])

  const completedCount = items.filter(item => item.status === 'completed').length
  const errorCount = items.filter(item => item.status === 'error').length
  const totalCount = items.length
  const isComplete = completedCount + errorCount === totalCount && totalCount > 0

  return {
    items,
    completedCount,
    errorCount,
    totalCount,
    isComplete,
    progress: totalCount > 0 ? (completedCount / totalCount) * 100 : 0,
    initializeBatch,
    updateItemStatus,
    processBatch
  }
}

// Hook for retry logic with exponential backoff
export function useRetryableLoading<T extends any[], R>(
  asyncFn: (...args: T) => Promise<R>,
  options?: {
    maxRetries?: number
    baseDelay?: number
    maxDelay?: number
    backoffMultiplier?: number
    id?: string
  }
) {
  const {
    maxRetries = 3,
    baseDelay = 1000,
    maxDelay = 10000,
    backoffMultiplier = 2,
    id
  } = options || {}

  const { execute: baseExecute, loading } = useAsyncLoading(asyncFn, id)
  const [retryCount, setRetryCount] = useState(0)
  const [lastError, setLastError] = useState<Error>()

  const calculateDelay = useCallback((attempt: number) => {
    return Math.min(baseDelay * Math.pow(backoffMultiplier, attempt), maxDelay)
  }, [baseDelay, backoffMultiplier, maxDelay])

  const executeWithRetry = useCallback(async (...args: T): Promise<R> => {
    let currentRetry = 0
    setRetryCount(0)
    setLastError(undefined)
    let lastErrorRef: Error | undefined

    while (currentRetry <= maxRetries) {
      try {
        const result = await baseExecute(...args)
        setRetryCount(currentRetry)
        return result
      } catch (error) {
        const err = error instanceof Error ? error : new Error('Unknown error')
        setLastError(err)
        lastErrorRef = err
        
        if (currentRetry === maxRetries) {
          setRetryCount(currentRetry)
          throw err
        }

        // Wait before retry
        const delay = calculateDelay(currentRetry)
        await new Promise(resolve => setTimeout(resolve, delay))
        currentRetry++
        setRetryCount(currentRetry)
      }
    }

    throw lastErrorRef ?? new Error('Unknown error')
  }, [baseExecute, calculateDelay, maxRetries])

  return {
    execute: executeWithRetry,
    loading,
    retryCount,
    lastError,
    canRetry: retryCount < maxRetries
  }
}

// Hook for polling with loading state
export function usePollingLoading<T>(
  pollingFn: () => Promise<T>,
  options?: {
    interval?: number
    maxAttempts?: number
    stopCondition?: (data: T) => boolean
    id?: string
  }
) {
  const {
    interval = 2000,
    maxAttempts = 50,
    stopCondition = () => false,
    id = 'polling'
  } = options || {}

  const [data, setData] = useState<T>()
  const [attemptCount, setAttemptCount] = useState(0)
  const [isPolling, setIsPolling] = useState(false)
  const loadingState = useLoadingState(id)
  const intervalRef = useRef<NodeJS.Timeout>()

  const stopPolling = useCallback(() => {
    setIsPolling(false)
    if (intervalRef.current) {
      clearTimeout(intervalRef.current)
    }
    loadingState.finishLoading()
  }, [loadingState])

  const startPolling = useCallback(async () => {
    if (isPolling) return

    setIsPolling(true)
    setAttemptCount(0)
    loadingState.startLoading({ message: 'Polling for updates...' })

    const poll = async () => {
      try {
        const result = await pollingFn()
        setData(result)
        setAttemptCount(prev => prev + 1)

        const progress = maxAttempts > 0 ? (attemptCount / maxAttempts) * 100 : undefined
        loadingState.updateLoading({ 
          progress,
          message: `Attempt ${attemptCount + 1}${maxAttempts > 0 ? ` of ${maxAttempts}` : ''}...`
        })

        // Check stop condition
        if (stopCondition(result)) {
          stopPolling()
          return
        }

        // Check max attempts
        if (maxAttempts > 0 && attemptCount >= maxAttempts) {
          stopPolling()
          loadingState.setError('Maximum polling attempts reached')
          return
        }

        // Schedule next poll
        intervalRef.current = setTimeout(poll, interval)
      } catch (error) {
        stopPolling()
        loadingState.setError(error instanceof Error ? error.message : 'Polling failed')
      }
    }

    await poll()
  }, [
    isPolling,
    pollingFn,
    stopCondition,
    maxAttempts,
    attemptCount,
    interval,
    loadingState,
    stopPolling
  ])

  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearTimeout(intervalRef.current)
      }
    }
  }, [])

  return {
    data,
    attemptCount,
    isPolling,
    loading: loadingState.loading,
    error: loadingState.loadingState?.error,
    startPolling,
    stopPolling
  }
}

// Hook for debounced loading
export function useDebouncedLoading<T extends any[], R>(
  asyncFn: (...args: T) => Promise<R>,
  delay: number = 300,
  id?: string
) {
  const { execute, loading } = useAsyncLoading(asyncFn, id)
  const timeoutRef = useRef<NodeJS.Timeout>()

  const debouncedExecute = useCallback((...args: T): Promise<R> => {
    return new Promise((resolve, reject) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }

      timeoutRef.current = setTimeout(async () => {
        try {
          const result = await execute(...args)
          resolve(result)
        } catch (error) {
          reject(error)
        }
      }, delay)
    })
  }, [execute, delay])

  const cancelPending = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  return {
    execute: debouncedExecute,
    loading,
    cancelPending
  }
}

// Export commonly used hooks
export {
  useLoading,
  useLoadingState,
  useAsyncLoading,
  usePageLoading,
  useCriticalLoading,
  useLoadingWithTimeout
} from '@/contexts/loading-context'
