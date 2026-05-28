'use client'

import React, { useState, useEffect, useCallback, useRef, createContext, useContext } from 'react'
import { 
  AlertTriangle, RefreshCw, WifiOff, Clock, 
  AlertCircle, X, ChevronDown, ChevronUp,
  Home, ArrowLeft, Bug, Send
} from 'lucide-react'
import { serviceEndpoints } from '@/lib/service-endpoints'

// Error types and codes
export enum ErrorCode {
  DEMO_UNAVAILABLE = 'E_DEMO_UNAVAILABLE',
  TIMEOUT = 'E_TIMEOUT',
  TOOL_ERROR = 'E_TOOL_ERROR',
  STORAGE = 'E_STORAGE',
  NETWORK = 'E_NETWORK',
  AUTH = 'E_AUTH',
  VALIDATION = 'E_VALIDATION',
  RATE_LIMIT = 'E_RATE_LIMIT',
  SERVER = 'E_SERVER',
  UNKNOWN = 'E_UNKNOWN'
}

export interface AppError {
  code: ErrorCode
  message: string
  details?: string
  timestamp: number
  retryable: boolean
  severity: 'low' | 'medium' | 'high' | 'critical'
  context?: Record<string, any>
  stack?: string
}

interface ErrorRecoveryStrategy {
  maxRetries: number
  retryDelay: number
  backoffMultiplier: number
  timeout: number
}

// Error Context
interface ErrorContextValue {
  errors: AppError[]
  currentError: AppError | null
  addError: (error: AppError) => void
  clearError: (code?: ErrorCode) => void
  clearAllErrors: () => void
  retry: (error: AppError) => Promise<void>
  reportError: (error: AppError) => void
}

const ErrorContext = createContext<ErrorContextValue | null>(null)

export function useErrorHandler() {
  const context = useContext(ErrorContext)
  if (!context) {
    throw new Error('useErrorHandler must be used within ErrorProvider')
  }
  return context
}

// Error Provider
export function ErrorProvider({ 
  children,
  onError,
  maxErrors = 10
}: { 
  children: React.ReactNode
  onError?: (error: AppError) => void
  maxErrors?: number
}) {
  const [errors, setErrors] = useState<AppError[]>([])
  const [currentError, setCurrentError] = useState<AppError | null>(null)

  const addError = useCallback((error: AppError) => {
    setErrors(prev => {
      const newErrors = [error, ...prev].slice(0, maxErrors)
      return newErrors
    })
    setCurrentError(error)
    
    if (onError) {
      onError(error)
    }

    // Auto-dismiss low severity errors after 5 seconds
    if (error.severity === 'low') {
      setTimeout(() => {
        clearError(error.code)
      }, 5000)
    }
  }, [maxErrors, onError])

  const clearError = useCallback((code?: ErrorCode) => {
    if (code) {
      setErrors(prev => prev.filter(e => e.code !== code))
      if (currentError?.code === code) {
        setCurrentError(null)
      }
    } else if (currentError) {
      setErrors(prev => prev.filter(e => e !== currentError))
      setCurrentError(null)
    }
  }, [currentError])

  const clearAllErrors = useCallback(() => {
    setErrors([])
    setCurrentError(null)
  }, [])

  const retry = useCallback(async (error: AppError) => {
    // Implement retry logic based on error type
    clearError(error.code)
    // The actual retry logic would be implemented by the component that handles the error
  }, [clearError])

  const reportError = useCallback((error: AppError) => {
    // Send error report to backend
    const endpoint = serviceEndpoints.orchestrator('/api/errors/report')
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(error)
    }).catch(console.error)
  }, [])

  const value: ErrorContextValue = {
    errors,
    currentError,
    addError,
    clearError,
    clearAllErrors,
    retry,
    reportError
  }

  return (
    <ErrorContext.Provider value={value}>
      {children}
    </ErrorContext.Provider>
  )
}

// Error Message Mapping
const ERROR_MESSAGES: Record<ErrorCode, { title: string; description: string; action?: string }> = {
  [ErrorCode.DEMO_UNAVAILABLE]: {
    title: 'Service Temporarily Unavailable',
    description: 'This feature is currently unavailable. Please try again in a few moments.',
    action: 'Refresh the page or try again shortly'
  },
  [ErrorCode.TIMEOUT]: {
    title: 'Request Timed Out',
    description: 'The operation took longer than expected. This might be due to high server load.',
    action: 'Try again with a simpler query or wait a moment'
  },
  [ErrorCode.TOOL_ERROR]: {
    title: 'Processing Error',
    description: 'An error occurred while processing your request.',
    action: 'Check your input and try again'
  },
  [ErrorCode.STORAGE]: {
    title: 'Storage Error',
    description: 'Unable to save or retrieve data from storage.',
    action: 'Clear your browser cache or try incognito mode'
  },
  [ErrorCode.NETWORK]: {
    title: 'Network Error',
    description: 'Unable to connect to the server. Check your internet connection.',
    action: 'Check your connection and try again'
  },
  [ErrorCode.AUTH]: {
    title: 'Authentication Required',
    description: 'You need to be logged in to perform this action.',
    action: 'Please log in and try again'
  },
  [ErrorCode.VALIDATION]: {
    title: 'Invalid Input',
    description: 'The provided input is invalid or incomplete.',
    action: 'Review your input and try again'
  },
  [ErrorCode.RATE_LIMIT]: {
    title: 'Rate Limit Exceeded',
    description: 'You\'ve made too many requests. Please wait before trying again.',
    action: 'Wait a moment and try again'
  },
  [ErrorCode.SERVER]: {
    title: 'Server Error',
    description: 'An unexpected server error occurred.',
    action: 'Try again or contact support if the issue persists'
  },
  [ErrorCode.UNKNOWN]: {
    title: 'Unexpected Error',
    description: 'An unexpected error occurred.',
    action: 'Try again or refresh the page'
  }
}

// Error Display Component
export function ErrorDisplay({ 
  error,
  onRetry,
  onDismiss,
  compact = false
}: { 
  error: AppError
  onRetry?: () => void
  onDismiss?: () => void
  compact?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const errorInfo = ERROR_MESSAGES[error.code] || ERROR_MESSAGES[ErrorCode.UNKNOWN]

  const getSeverityColor = () => {
    switch (error.severity) {
      case 'critical': return 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800'
      case 'high': return 'bg-orange-50 border-orange-200 dark:bg-orange-900/20 dark:border-orange-800'
      case 'medium': return 'bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800'
      case 'low': return 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800'
    }
  }

  const getSeverityIcon = () => {
    switch (error.severity) {
      case 'critical':
      case 'high':
        return <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
      case 'medium':
        return <AlertCircle className="h-5 w-5 text-yellow-600 dark:text-yellow-400" />
      case 'low':
        return <AlertCircle className="h-5 w-5 text-blue-600 dark:text-blue-400" />
    }
  }

  if (compact) {
    return (
      <div className={`flex items-center gap-3 p-3 rounded-lg border ${getSeverityColor()}`}>
        {getSeverityIcon()}
        <div className="flex-1">
          <p className="text-sm font-medium">{errorInfo.title}</p>
        </div>
        {error.retryable && onRetry && (
          <button
            onClick={onRetry}
            className="p-1 hover:bg-white/50 dark:hover:bg-black/20 rounded"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-1 hover:bg-white/50 dark:hover:bg-black/20 rounded"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    )
  }

  return (
    <div className={`rounded-lg border ${getSeverityColor()} p-4`}>
      <div className="flex items-start gap-3">
        {getSeverityIcon()}
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900 dark:text-white">
            {errorInfo.title}
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            {error.message || errorInfo.description}
          </p>
          {errorInfo.action && (
            <p className="text-sm text-gray-700 dark:text-gray-300 mt-2 font-medium">
              💡 {errorInfo.action}
            </p>
          )}
          
          {/* Error details (expandable) */}
          {(error.details || error.stack) && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 mt-2"
            >
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              {expanded ? 'Hide' : 'Show'} details
            </button>
          )}
          
          {expanded && (
            <div className="mt-2 p-2 bg-gray-100 dark:bg-gray-800 rounded text-xs font-mono">
              {error.details && <p className="mb-2">{error.details}</p>}
              {error.stack && (
                <pre className="whitespace-pre-wrap text-gray-600 dark:text-gray-400">
                  {error.stack}
                </pre>
              )}
            </div>
          )}
        </div>
        
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-1 hover:bg-white/50 dark:hover:bg-black/20 rounded"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>
      
      {/* Actions */}
      <div className="flex items-center gap-2 mt-4">
        {error.retryable && onRetry && (
          <button
            onClick={onRetry}
            className="px-3 py-1.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            Try Again
          </button>
        )}
        <button
          onClick={() => window.location.href = '/'}
          className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white flex items-center gap-2"
        >
          <Home className="h-4 w-4" />
          Go Home
        </button>
      </div>
    </div>
  )
}

// Error Toast Notification
export function ErrorToast() {
  const { errors, clearError } = useErrorHandler()
  const visibleErrors = errors.slice(0, 3) // Show max 3 toasts

  if (visibleErrors.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2">
      {visibleErrors.map((error) => (
        <div
          key={`${error.code}-${error.timestamp}`}
          className="animate-slide-in-right"
        >
          <ErrorDisplay
            error={error}
            onDismiss={() => clearError(error.code)}
            compact
          />
        </div>
      ))}
    </div>
  )
}

// Retry with exponential backoff
export function useRetryWithBackoff(
  fn: () => Promise<any>,
  options: Partial<ErrorRecoveryStrategy> = {}
) {
  const {
    maxRetries = 3,
    retryDelay = 1000,
    backoffMultiplier = 2,
    timeout = 30000
  } = options

  const [retryCount, setRetryCount] = useState(0)
  const [isRetrying, setIsRetrying] = useState(false)

  const execute = useCallback(async () => {
    let lastError: Error | null = null
    
    for (let i = 0; i <= maxRetries; i++) {
      try {
        setIsRetrying(i > 0)
        setRetryCount(i)
        
        const result = await Promise.race([
          fn(),
          new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Timeout')), timeout)
          )
        ])
        
        setIsRetrying(false)
        setRetryCount(0)
        return result
      } catch (error) {
        lastError = error as Error
        
        if (i < maxRetries) {
          const delay = retryDelay * Math.pow(backoffMultiplier, i)
          await new Promise(resolve => setTimeout(resolve, delay))
        }
      }
    }
    
    setIsRetrying(false)
    throw lastError
  }, [fn, maxRetries, retryDelay, backoffMultiplier, timeout])

  return { execute, retryCount, isRetrying }
}

// Offline detection
export function useOfflineDetection() {
  const [isOffline, setIsOffline] = useState(!navigator.onLine)
  const { addError, clearError } = useErrorHandler()

  useEffect(() => {
    const handleOnline = () => {
      setIsOffline(false)
      clearError(ErrorCode.NETWORK)
    }

    const handleOffline = () => {
      setIsOffline(true)
      addError({
        code: ErrorCode.NETWORK,
        message: 'You are currently offline',
        timestamp: Date.now(),
        retryable: true,
        severity: 'medium'
      })
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [addError, clearError])

  return isOffline
}

// Timeout handler
export function useTimeout(
  fn: () => void,
  delay: number,
  onTimeout?: () => void
) {
  const [isTimedOut, setIsTimedOut] = useState(false)
  const timeoutRef = useRef<NodeJS.Timeout>()

  const start = useCallback(() => {
    setIsTimedOut(false)
    timeoutRef.current = setTimeout(() => {
      setIsTimedOut(true)
      if (onTimeout) {
        onTimeout()
      }
    }, delay)
  }, [delay, onTimeout])

  const cancel = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      setIsTimedOut(false)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  return { start, cancel, isTimedOut }
}

// Error fallback page component
export function ErrorFallbackPage({ 
  error,
  resetError
}: { 
  error: Error
  resetError: () => void
}) {
  const [reportSent, setReportSent] = useState(false)

  const sendReport = async () => {
    try {
      const endpoint = serviceEndpoints.orchestrator('/api/errors/report')
      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: error.message,
          stack: error.stack,
          url: window.location.href,
          userAgent: navigator.userAgent
        })
      })
      setReportSent(true)
    } catch (e) {
      console.error('Failed to send error report', e)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 dark:bg-red-900/20 rounded-full mb-4">
            <AlertTriangle className="h-8 w-8 text-red-600 dark:text-red-400" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Something went wrong
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            An unexpected error occurred. We apologize for the inconvenience.
          </p>
        </div>

        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 mb-6">
          <p className="text-sm font-mono text-gray-700 dark:text-gray-300">
            {error.message}
          </p>
        </div>

        <div className="flex flex-col gap-3">
          <button
            onClick={resetError}
            className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2"
          >
            <RefreshCw className="h-5 w-5" />
            Try Again
          </button>
          
          <button
            onClick={() => window.location.href = '/'}
            className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center justify-center gap-2"
          >
            <Home className="h-5 w-5" />
            Go to Homepage
          </button>
          
          {!reportSent ? (
            <button
              onClick={sendReport}
              className="w-full px-4 py-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white flex items-center justify-center gap-2"
            >
              <Send className="h-5 w-5" />
              Send Error Report
            </button>
          ) : (
            <p className="text-center text-sm text-green-600 dark:text-green-400">
              ✓ Error report sent
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// Export all components
const errorRecoveryExports = {
  ErrorProvider,
  useErrorHandler,
  ErrorDisplay,
  ErrorToast,
  ErrorFallbackPage,
  useRetryWithBackoff,
  useOfflineDetection,
  useTimeout,
  ErrorCode
}

export default errorRecoveryExports
