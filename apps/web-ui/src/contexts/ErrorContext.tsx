'use client'

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { ErrorCode } from '@/components/error/error-recovery'
import { buildAuthLoginHref } from '@/lib/auth/login-redirect'
import { serviceEndpoints } from '@/lib/service-endpoints'

export interface AppError {
  id: string
  code: ErrorCode
  message: string
  details?: string
  timestamp: number
  retryable: boolean
  severity: 'low' | 'medium' | 'high' | 'critical'
  context?: Record<string, any>
  stack?: string
  componentStack?: string
  url?: string
  userId?: string
}

export interface ErrorRecoveryAction {
  label: string
  description: string
  action: () => void | Promise<void>
  icon?: React.ComponentType<{ className?: string }>
}

interface ErrorContextValue {
  // Error state
  errors: AppError[]
  currentError: AppError | null
  hasGlobalError: boolean
  
  // Error management
  addError: (error: Omit<AppError, 'id' | 'timestamp'>) => string
  clearError: (errorId: string) => void
  clearAllErrors: () => void
  clearErrorsByCode: (code: ErrorCode) => void
  
  // Recovery actions
  retry: (errorId: string) => Promise<void>
  getRecoveryActions: (error: AppError) => ErrorRecoveryAction[]
  
  // Error reporting
  reportError: (error: AppError) => Promise<void>
  
  // Settings
  maxErrors: number
  setMaxErrors: (max: number) => void
  enableAutoReport: boolean
  setEnableAutoReport: (enabled: boolean) => void
}

const ErrorContext = createContext<ErrorContextValue | null>(null)

export function useErrorHandler() {
  const context = useContext(ErrorContext)
  if (!context) {
    throw new Error('useErrorHandler must be used within ErrorProvider')
  }
  return context
}

interface ErrorProviderProps {
  children: React.ReactNode
  maxErrors?: number
  enableAutoReport?: boolean
  onGlobalError?: (error: AppError) => void
  onErrorClear?: (error: AppError) => void
}

export function ErrorProvider({ 
  children, 
  maxErrors: initialMaxErrors = 20,
  enableAutoReport: initialAutoReport = true,
  onGlobalError,
  onErrorClear
}: ErrorProviderProps) {
  const [errors, setErrors] = useState<AppError[]>([])
  const [currentError, setCurrentError] = useState<AppError | null>(null)
  const [maxErrors, setMaxErrors] = useState(initialMaxErrors)
  const [enableAutoReport, setEnableAutoReport] = useState(initialAutoReport)

  const reportError = useCallback(async (error: AppError): Promise<void> => {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/errors/report'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          // Flat structure matching backend ErrorReport schema
          message: error.message,
          code: error.code || 'UNKNOWN',
          details: error.componentStack || error.details || null,
          timestamp: error.timestamp, // Unix milliseconds (int)
          severity: error.severity || 'medium',
          url: error.url || (typeof window !== 'undefined' ? window.location.href : ''),
          userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'Unknown',
          stack: error.stack || null,
          context: error.context || {},
          userId: error.userId || null,
          sessionId: null
        })
      })

      if (!response.ok) {
        throw new Error(`Failed to report error: ${response.status}`)
      }
    } catch (reportingError) {
      console.error('Failed to report error:', reportingError)
    }
  }, [])

  // Determine if there's a global/critical error that should block the UI
  const hasGlobalError = errors.some(error => 
    error.severity === 'critical' || 
    error.code === ErrorCode.AUTH ||
    error.code === ErrorCode.SERVER
  )

  const generateErrorId = (): string => {
    return `error_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  const clearError = useCallback((errorId: string) => {
    setErrors(prev => {
      const errorToRemove = prev.find(e => e.id === errorId)
      const filtered = prev.filter(e => e.id !== errorId)
      
      if (errorToRemove && onErrorClear) {
        onErrorClear(errorToRemove)
      }
      
      return filtered
    })

    // Clear current error if it's the one being removed
    setCurrentError(prev => (prev?.id === errorId ? null : prev))
  }, [onErrorClear])

  const addError = useCallback((errorData: Omit<AppError, 'id' | 'timestamp'>) => {
    const error: AppError = {
      ...errorData,
      id: generateErrorId(),
      timestamp: Date.now(),
      url: typeof window !== 'undefined' ? window.location.href : undefined,
      userId: getUserId()
    }

    setErrors(prev => {
      // Remove duplicates (same code and message within 5 seconds)
      const filtered = prev.filter(existingError => {
        const isSimilar = existingError.code === error.code && 
                         existingError.message === error.message
        const isRecent = error.timestamp - existingError.timestamp < 5000
        return !(isSimilar && isRecent)
      })

      const newErrors = [error, ...filtered].slice(0, maxErrors)
      return newErrors
    })

    // Set as current error if it's high severity or no current error
    if (error.severity === 'critical' || error.severity === 'high' || !currentError) {
      setCurrentError(error)
    }

    // Auto-report if enabled
    if (enableAutoReport) {
      reportError(error).catch(console.error)
    }

    // Auto-dismiss low severity errors
    if (error.severity === 'low') {
      setTimeout(() => clearError(error.id), 5000)
    }

    // Notify global error handler
    if (onGlobalError && (error.severity === 'critical' || error.severity === 'high')) {
      onGlobalError(error)
    }

    return error.id
  }, [maxErrors, enableAutoReport, currentError, onGlobalError, clearError, reportError])

  const clearAllErrors = useCallback(() => {
    errors.forEach(error => {
      if (onErrorClear) {
        onErrorClear(error)
      }
    })
    setErrors([])
    setCurrentError(null)
  }, [errors, onErrorClear])

  const clearErrorsByCode = useCallback((code: ErrorCode) => {
    const errorsToRemove = errors.filter(e => e.code === code)
    
    setErrors(prev => prev.filter(e => e.code !== code))
    
    if (currentError?.code === code) {
      setCurrentError(null)
    }

    if (onErrorClear) {
      errorsToRemove.forEach(onErrorClear)
    }
  }, [errors, currentError, onErrorClear])

  const retry = useCallback(async (errorId: string) => {
    const error = errors.find(e => e.id === errorId)
    if (!error || !error.retryable) return

    // Clear the error and let the original operation retry
    clearError(errorId)
    
    // The actual retry logic should be handled by the component that triggered the error
    // This is just a placeholder that clears the error
  }, [errors, clearError])

  const getRecoveryActions = useCallback((error: AppError): ErrorRecoveryAction[] => {
    const actions: ErrorRecoveryAction[] = []
    const errorMessage = error.message.toLowerCase()

    // Network-specific actions
    if (error.code === ErrorCode.NETWORK || errorMessage.includes('network') || errorMessage.includes('fetch')) {
      actions.push({
        label: 'Check Connection',
        description: 'Verify your internet connection and try again',
        action: () => window.location.reload()
      })
    }

    // Timeout-specific actions
    if (error.code === ErrorCode.TIMEOUT) {
      actions.push({
        label: 'Retry with Timeout',
        description: 'Try the operation again with extended timeout',
        action: async () => retry(error.id)
      })
    }

    // Storage-specific actions
    if (error.code === ErrorCode.STORAGE || errorMessage.includes('storage') || errorMessage.includes('quota')) {
      actions.push({
        label: 'Clear Browser Data',
        description: 'Clear browser cache and storage',
        action: async () => {
          if ('storage' in navigator && 'estimate' in navigator.storage) {
            try {
              if ('caches' in window) {
                const cacheNames = await caches.keys()
                await Promise.all(cacheNames.map(name => caches.delete(name)))
              }
              localStorage.clear()
              sessionStorage.clear()
              window.location.reload()
            } catch (e) {
              console.error('Failed to clear storage:', e)
            }
          }
        }
      })
    }

    // Auth-specific actions
    if (error.code === ErrorCode.AUTH || errorMessage.includes('auth') || errorMessage.includes('unauthorized')) {
      actions.push({
        label: 'Re-authenticate',
        description: 'Sign in again to refresh your session',
        action: () => {
          localStorage.removeItem('token')
          const currentPath = window.location.pathname + window.location.search
          window.location.href = buildAuthLoginHref(currentPath)
        }
      })
    }

    // Chunk/loading errors
    if (errorMessage.includes('chunk') || errorMessage.includes('loading')) {
      actions.push({
        label: 'Hard Refresh',
        description: 'Force reload the application',
        action: () => window.location.reload()
      })
    }

    // Default actions for all errors
    if (error.retryable && error.code !== ErrorCode.RATE_LIMIT) {
      actions.push({
        label: 'Try Again',
        description: 'Retry the failed operation',
        action: async () => retry(error.id)
      })
    }

    actions.push({
      label: 'Reload Page',
      description: 'Refresh the page to reset application state',
      action: () => window.location.reload()
    })

    actions.push({
      label: 'Go to Dashboard',
      description: 'Return to the main dashboard',
      action: () => { window.location.href = '/' }
    })

    return actions
  }, [retry])

  const getUserId = (): string | null => {
    if (typeof window === 'undefined') return null
    
    try {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return user.id || null
    } catch {
      return null
    }
  }

  // Global error handler for unhandled errors
  useEffect(() => {
    const handleUnhandledError = (event: ErrorEvent) => {
      addError({
        code: ErrorCode.UNKNOWN,
        message: event.error?.message || event.message,
        details: `Unhandled error: ${event.filename}:${event.lineno}:${event.colno}`,
        stack: event.error?.stack,
        retryable: false,
        severity: 'high'
      })
    }

    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      const error = event.reason
      addError({
        code: ErrorCode.UNKNOWN,
        message: error?.message || 'Unhandled promise rejection',
        details: error?.stack || String(error),
        retryable: false,
        severity: 'medium'
      })
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('error', handleUnhandledError)
      window.addEventListener('unhandledrejection', handleUnhandledRejection)

      return () => {
        window.removeEventListener('error', handleUnhandledError)
        window.removeEventListener('unhandledrejection', handleUnhandledRejection)
      }
    }
  }, [addError])

  const value: ErrorContextValue = {
    // Error state
    errors,
    currentError,
    hasGlobalError,
    
    // Error management
    addError,
    clearError,
    clearAllErrors,
    clearErrorsByCode,
    
    // Recovery actions
    retry,
    getRecoveryActions,
    
    // Error reporting
    reportError,
    
    // Settings
    maxErrors,
    setMaxErrors,
    enableAutoReport,
    setEnableAutoReport
  }

  return (
    <ErrorContext.Provider value={value}>
      {children}
    </ErrorContext.Provider>
  )
}

// Hook for manual error reporting from components
export function useErrorReporting() {
  const { addError, reportError } = useErrorHandler()

  const reportManualError = useCallback(async (
    message: string,
    options: Partial<Omit<AppError, 'id' | 'timestamp' | 'message'>> = {}
  ) => {
    const errorId = addError({
      code: ErrorCode.UNKNOWN,
      message,
      retryable: false,
      severity: 'medium',
      context: { manual: true },
      ...options
    })

    return errorId
  }, [addError])

  return { reportError: reportManualError, reportErrorDirectly: reportError }
}

export { ErrorCode }
