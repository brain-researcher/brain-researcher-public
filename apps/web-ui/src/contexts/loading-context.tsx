'use client'

import React, { createContext, useContext, useReducer, useCallback, useEffect } from 'react'

// Types
interface LoadingState {
  id: string
  message?: string
  progress?: number
  stage?: string
  estimatedTimeRemaining?: number
  startTime: number
  canCancel?: boolean
  canPause?: boolean
  error?: string
  metadata?: Record<string, any>
}

interface GlobalLoadingState {
  loadings: Record<string, LoadingState>
  globalLoading: boolean
  pageLoading: boolean
  criticalLoading: boolean
}

type LoadingAction =
  | { type: 'START_LOADING'; payload: { id: string; options?: Partial<LoadingState> } }
  | { type: 'UPDATE_LOADING'; payload: { id: string; updates: Partial<LoadingState> } }
  | { type: 'FINISH_LOADING'; payload: { id: string } }
  | { type: 'SET_ERROR'; payload: { id: string; error: string } }
  | { type: 'CLEAR_ERROR'; payload: { id: string } }
  | { type: 'SET_PAGE_LOADING'; payload: { loading: boolean } }
  | { type: 'SET_CRITICAL_LOADING'; payload: { loading: boolean } }
  | { type: 'CLEAR_ALL_LOADING' }

// Initial state
const initialState: GlobalLoadingState = {
  loadings: {},
  globalLoading: false,
  pageLoading: false,
  criticalLoading: false
}

// Reducer
function loadingReducer(state: GlobalLoadingState, action: LoadingAction): GlobalLoadingState {
  switch (action.type) {
    case 'START_LOADING': {
      const { id, options = {} } = action.payload
      const newLoading: LoadingState = {
        id,
        startTime: Date.now(),
        ...options
      }

      const newLoadings = {
        ...state.loadings,
        [id]: newLoading
      }

      return {
        ...state,
        loadings: newLoadings,
        globalLoading: Object.keys(newLoadings).length > 0
      }
    }

    case 'UPDATE_LOADING': {
      const { id, updates } = action.payload
      if (!state.loadings[id]) return state

      const newLoadings = {
        ...state.loadings,
        [id]: { ...state.loadings[id], ...updates }
      }

      return {
        ...state,
        loadings: newLoadings
      }
    }

    case 'FINISH_LOADING': {
      const { id } = action.payload
      const { [id]: removed, ...remainingLoadings } = state.loadings

      return {
        ...state,
        loadings: remainingLoadings,
        globalLoading: Object.keys(remainingLoadings).length > 0
      }
    }

    case 'SET_ERROR': {
      const { id, error } = action.payload
      if (!state.loadings[id]) return state

      const newLoadings = {
        ...state.loadings,
        [id]: { ...state.loadings[id], error }
      }

      return {
        ...state,
        loadings: newLoadings
      }
    }

    case 'CLEAR_ERROR': {
      const { id } = action.payload
      if (!state.loadings[id]) return state

      const { error, ...loadingWithoutError } = state.loadings[id]
      const newLoadings = {
        ...state.loadings,
        [id]: loadingWithoutError
      }

      return {
        ...state,
        loadings: newLoadings
      }
    }

    case 'SET_PAGE_LOADING': {
      return {
        ...state,
        pageLoading: action.payload.loading
      }
    }

    case 'SET_CRITICAL_LOADING': {
      return {
        ...state,
        criticalLoading: action.payload.loading
      }
    }

    case 'CLEAR_ALL_LOADING': {
      return {
        ...initialState
      }
    }

    default:
      return state
  }
}

// Context
interface LoadingContextValue {
  // State
  state: GlobalLoadingState
  
  // Actions
  startLoading: (id: string, options?: Partial<LoadingState>) => void
  updateLoading: (id: string, updates: Partial<LoadingState>) => void
  finishLoading: (id: string) => void
  setError: (id: string, error: string) => void
  clearError: (id: string) => void
  setPageLoading: (loading: boolean) => void
  setCriticalLoading: (loading: boolean) => void
  clearAllLoading: () => void
  
  // Utilities
  isLoading: (id?: string) => boolean
  getLoadingState: (id: string) => LoadingState | undefined
  getElapsedTime: (id: string) => number
  getAllLoadings: () => LoadingState[]
  getLoadingCount: () => number
}

const LoadingContext = createContext<LoadingContextValue | undefined>(undefined)

// Provider component
export function LoadingProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(loadingReducer, initialState)

  // Actions
  const startLoading = useCallback((id: string, options?: Partial<LoadingState>) => {
    dispatch({ type: 'START_LOADING', payload: { id, options } })
  }, [])

  const updateLoading = useCallback((id: string, updates: Partial<LoadingState>) => {
    dispatch({ type: 'UPDATE_LOADING', payload: { id, updates } })
  }, [])

  const finishLoading = useCallback((id: string) => {
    dispatch({ type: 'FINISH_LOADING', payload: { id } })
  }, [])

  const setError = useCallback((id: string, error: string) => {
    dispatch({ type: 'SET_ERROR', payload: { id, error } })
  }, [])

  const clearError = useCallback((id: string) => {
    dispatch({ type: 'CLEAR_ERROR', payload: { id } })
  }, [])

  const setPageLoading = useCallback((loading: boolean) => {
    dispatch({ type: 'SET_PAGE_LOADING', payload: { loading } })
  }, [])

  const setCriticalLoading = useCallback((loading: boolean) => {
    dispatch({ type: 'SET_CRITICAL_LOADING', payload: { loading } })
  }, [])

  const clearAllLoading = useCallback(() => {
    dispatch({ type: 'CLEAR_ALL_LOADING' })
  }, [])

  // Utilities
  const isLoading = useCallback((id?: string) => {
    if (id) {
      return Boolean(state.loadings[id] && !state.loadings[id].error)
    }
    return state.globalLoading || state.pageLoading || state.criticalLoading
  }, [state])

  const getLoadingState = useCallback((id: string) => {
    return state.loadings[id]
  }, [state.loadings])

  const getElapsedTime = useCallback((id: string) => {
    const loading = state.loadings[id]
    return loading ? Date.now() - loading.startTime : 0
  }, [state.loadings])

  const getAllLoadings = useCallback(() => {
    return Object.values(state.loadings)
  }, [state.loadings])

  const getLoadingCount = useCallback(() => {
    return Object.keys(state.loadings).length
  }, [state.loadings])

  // Auto-cleanup long-running loadings (prevent memory leaks)
  useEffect(() => {
    const cleanup = setInterval(() => {
      const now = Date.now()
      const staleThreshold = 10 * 60 * 1000 // 10 minutes

      Object.entries(state.loadings).forEach(([id, loading]) => {
        if (now - loading.startTime > staleThreshold) {
          console.warn(`Auto-cleaning stale loading state: ${id}`)
          finishLoading(id)
        }
      })
    }, 60000) // Check every minute

    return () => clearInterval(cleanup)
  }, [state.loadings, finishLoading])

  const value: LoadingContextValue = {
    state,
    startLoading,
    updateLoading,
    finishLoading,
    setError,
    clearError,
    setPageLoading,
    setCriticalLoading,
    clearAllLoading,
    isLoading,
    getLoadingState,
    getElapsedTime,
    getAllLoadings,
    getLoadingCount
  }

  return (
    <LoadingContext.Provider value={value}>
      {children}
    </LoadingContext.Provider>
  )
}

// Hook to use loading context
export function useLoading() {
  const context = useContext(LoadingContext)
  if (!context) {
    throw new Error('useLoading must be used within a LoadingProvider')
  }
  return context
}

// Specific hooks for common loading patterns
export function useLoadingState(id: string) {
  const { 
    startLoading, 
    updateLoading, 
    finishLoading, 
    setError, 
    clearError,
    isLoading, 
    getLoadingState,
    getElapsedTime 
  } = useLoading()

  const loading = isLoading(id)
  const loadingState = getLoadingState(id)
  const elapsedTime = getElapsedTime(id)

  return {
    loading,
    loadingState,
    elapsedTime,
    startLoading: useCallback((options?: Partial<LoadingState>) => startLoading(id, options), [startLoading, id]),
    updateLoading: useCallback((updates: Partial<LoadingState>) => updateLoading(id, updates), [updateLoading, id]),
    finishLoading: useCallback(() => finishLoading(id), [finishLoading, id]),
    setError: useCallback((error: string) => setError(id, error), [setError, id]),
    clearError: useCallback(() => clearError(id), [clearError, id])
  }
}

// Hook for async operations with loading state
export function useAsyncLoading<T extends any[], R>(
  asyncFn: (...args: T) => Promise<R>,
  id?: string
) {
  const loadingId = id || `async-${Math.random().toString(36).substr(2, 9)}`
  const { loading, startLoading, finishLoading, setError, clearError } = useLoadingState(loadingId)

  const execute = useCallback(async (...args: T): Promise<R> => {
    try {
      clearError()
      startLoading({ message: 'Processing...' })
      const result = await asyncFn(...args)
      finishLoading()
      return result
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'An error occurred'
      setError(errorMessage)
      throw error
    }
  }, [asyncFn, startLoading, finishLoading, setError, clearError])

  return { execute, loading }
}

// Hook for page loading
export function usePageLoading() {
  const { state, setPageLoading } = useLoading()
  
  return {
    loading: state.pageLoading,
    setLoading: setPageLoading
  }
}

// Hook for critical loading (blocks all UI)
export function useCriticalLoading() {
  const { state, setCriticalLoading } = useLoading()
  
  return {
    loading: state.criticalLoading,
    setLoading: setCriticalLoading
  }
}

// Hook for loading with timeout
export function useLoadingWithTimeout(id: string, timeoutMs: number = 30000) {
  const loadingHook = useLoadingState(id)
  
  useEffect(() => {
    if (!loadingHook.loading) return
    
    const timeout = setTimeout(() => {
      if (loadingHook.loading) {
        loadingHook.updateLoading({ 
          message: 'This is taking longer than expected...' 
        })
      }
    }, timeoutMs)
    
    return () => clearTimeout(timeout)
  }, [loadingHook.loading, timeoutMs, loadingHook])
  
  return loadingHook
}

// Export types
export type { LoadingState, GlobalLoadingState, LoadingContextValue }