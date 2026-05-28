'use client'

import React, { useState, useEffect } from 'react'
import { useErrorHandler } from '@/contexts/ErrorContext'
import { ErrorCode } from './error-recovery'
import { X, AlertTriangle, AlertCircle, Info, CheckCircle, RefreshCw, ExternalLink } from 'lucide-react'

interface ToastProps {
  error: any
  onDismiss: () => void
  onRetry?: () => void
}

function ErrorToast({ error, onDismiss, onRetry }: ToastProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [isLeaving, setIsLeaving] = useState(false)

  useEffect(() => {
    // Animate in
    const timer = setTimeout(() => setIsVisible(true), 50)
    return () => clearTimeout(timer)
  }, [])

  const handleDismiss = () => {
    setIsLeaving(true)
    setTimeout(onDismiss, 300) // Match animation duration
  }

  const getSeverityStyles = () => {
    switch (error.severity) {
      case 'critical':
        return {
          bg: 'bg-red-900 dark:bg-red-950',
          border: 'border-red-700 dark:border-red-800',
          text: 'text-red-100',
          icon: 'text-red-300',
          iconBg: 'bg-red-800 dark:bg-red-900'
        }
      case 'high':
        return {
          bg: 'bg-orange-900 dark:bg-orange-950',
          border: 'border-orange-700 dark:border-orange-800',
          text: 'text-orange-100',
          icon: 'text-orange-300',
          iconBg: 'bg-orange-800 dark:bg-orange-900'
        }
      case 'medium':
        return {
          bg: 'bg-yellow-900 dark:bg-yellow-950',
          border: 'border-yellow-700 dark:border-yellow-800',
          text: 'text-yellow-100',
          icon: 'text-yellow-300',
          iconBg: 'bg-yellow-800 dark:bg-yellow-900'
        }
      case 'low':
        return {
          bg: 'bg-blue-900 dark:bg-blue-950',
          border: 'border-blue-700 dark:border-blue-800',
          text: 'text-blue-100',
          icon: 'text-blue-300',
          iconBg: 'bg-blue-800 dark:bg-blue-900'
        }
      default:
        return {
          bg: 'bg-gray-900 dark:bg-gray-950',
          border: 'border-gray-700 dark:border-gray-800',
          text: 'text-gray-100',
          icon: 'text-gray-300',
          iconBg: 'bg-gray-800 dark:bg-gray-900'
        }
    }
  }

  const getIcon = () => {
    switch (error.severity) {
      case 'critical':
      case 'high':
        return <AlertTriangle className="h-5 w-5" />
      case 'medium':
        return <AlertCircle className="h-5 w-5" />
      case 'low':
        return <Info className="h-5 w-5" />
      default:
        return <AlertCircle className="h-5 w-5" />
    }
  }

  const getTitle = () => {
    switch (error.code) {
      case ErrorCode.NETWORK:
        return 'Connection Problem'
      case ErrorCode.TIMEOUT:
        return 'Request Timed Out'
      case ErrorCode.AUTH:
        return 'Authentication Required'
      case ErrorCode.VALIDATION:
        return 'Invalid Input'
      case ErrorCode.RATE_LIMIT:
        return 'Rate Limit Exceeded'
      case ErrorCode.SERVER:
        return 'Server Error'
      case ErrorCode.STORAGE:
        return 'Storage Error'
      case ErrorCode.TOOL_ERROR:
        return 'Processing Error'
      case ErrorCode.DEMO_UNAVAILABLE:
        return 'Service Unavailable'
      default:
        return 'Error'
    }
  }

  const styles = getSeverityStyles()

  return (
    <div
      className={`
        transform transition-all duration-300 ease-out
        ${isVisible && !isLeaving ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0'}
        ${isLeaving ? 'scale-95' : 'scale-100'}
      `}
    >
      <div className={`
        max-w-sm w-full ${styles.bg} ${styles.border} border rounded-lg shadow-lg pointer-events-auto ring-1 ring-black ring-opacity-5 overflow-hidden
      `}>
        <div className="p-4">
          <div className="flex items-start">
            <div className={`flex-shrink-0 ${styles.iconBg} rounded-full p-1.5`}>
              <div className={styles.icon}>
                {getIcon()}
              </div>
            </div>
            <div className="ml-3 w-0 flex-1">
              <p className={`text-sm font-medium ${styles.text}`}>
                {getTitle()}
              </p>
              <p className={`mt-1 text-sm ${styles.text} opacity-90`}>
                {error.message}
              </p>
              {error.details && (
                <p className={`mt-1 text-xs ${styles.text} opacity-75`}>
                  {error.details}
                </p>
              )}
            </div>
            <div className="ml-4 flex-shrink-0 flex">
              <button
                className={`inline-flex ${styles.text} hover:opacity-75 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-white`}
                onClick={handleDismiss}
              >
                <span className="sr-only">Close</span>
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
          {(error.retryable || error.code === ErrorCode.NETWORK) && (
            <div className="mt-3 flex gap-2">
              {onRetry && error.retryable && (
                <button
                  onClick={onRetry}
                  className={`
                    inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium 
                    bg-white bg-opacity-20 hover:bg-opacity-30 
                    ${styles.text} rounded-md transition-colors
                    focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2
                  `}
                >
                  <RefreshCw className="h-3 w-3" />
                  Try Again
                </button>
              )}
              {error.code === ErrorCode.NETWORK && (
                <button
                  onClick={() => window.location.reload()}
                  className={`
                    inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium 
                    bg-white bg-opacity-20 hover:bg-opacity-30 
                    ${styles.text} rounded-md transition-colors
                    focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2
                  `}
                >
                  <RefreshCw className="h-3 w-3" />
                  Reload
                </button>
              )}
              {error.severity === 'critical' && (
                <button
                  onClick={() => window.open('/support', '_blank')}
                  className={`
                    inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium 
                    bg-white bg-opacity-20 hover:bg-opacity-30 
                    ${styles.text} rounded-md transition-colors
                    focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2
                  `}
                >
                  <ExternalLink className="h-3 w-3" />
                  Get Help
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface SuccessToastProps {
  message: string
  onDismiss: () => void
}

function SuccessToast({ message, onDismiss }: SuccessToastProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [isLeaving, setIsLeaving] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(true), 50)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    // Auto-dismiss success toasts after 4 seconds
    const timer = setTimeout(() => {
      setIsLeaving(true)
      setTimeout(onDismiss, 300)
    }, 4000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  const handleDismiss = () => {
    setIsLeaving(true)
    setTimeout(onDismiss, 300)
  }

  return (
    <div
      className={`
        transform transition-all duration-300 ease-out
        ${isVisible && !isLeaving ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0'}
        ${isLeaving ? 'scale-95' : 'scale-100'}
      `}
    >
      <div className="max-w-sm w-full bg-green-900 dark:bg-green-950 border border-green-700 dark:border-green-800 rounded-lg shadow-lg pointer-events-auto ring-1 ring-black ring-opacity-5 overflow-hidden">
        <div className="p-4">
          <div className="flex items-start">
            <div className="flex-shrink-0 bg-green-800 dark:bg-green-900 rounded-full p-1.5">
              <CheckCircle className="h-5 w-5 text-green-300" />
            </div>
            <div className="ml-3 w-0 flex-1">
              <p className="text-sm font-medium text-green-100">
                Success
              </p>
              <p className="mt-1 text-sm text-green-100 opacity-90">
                {message}
              </p>
            </div>
            <div className="ml-4 flex-shrink-0 flex">
              <button
                className="inline-flex text-green-100 hover:opacity-75 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-white"
                onClick={handleDismiss}
              >
                <span className="sr-only">Close</span>
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

interface ToastContainerProps {
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left'
  maxToasts?: number
}

export function ErrorToastSystem({ 
  position = 'top-right',
  maxToasts = 4
}: ToastContainerProps) {
  const { errors, clearError, retry, getRecoveryActions } = useErrorHandler()
  const [successMessages, setSuccessMessages] = useState<Array<{id: string; message: string}>>([])
  
  // Only show errors that should appear as toasts
  const toastableErrors = errors.filter(error => 
    error.severity !== 'critical' && // Critical errors get full-screen treatment
    !['DEMO_UNAVAILABLE'].includes(error.code) // Some errors get special treatment
  ).slice(0, maxToasts)

  const getPositionClasses = () => {
    switch (position) {
      case 'top-left':
        return 'top-4 left-4'
      case 'bottom-right':
        return 'bottom-4 right-4'
      case 'bottom-left':
        return 'bottom-4 left-4'
      default: // top-right
        return 'top-4 right-4'
    }
  }

  const handleRetry = async (errorId: string) => {
    try {
      await retry(errorId)
      // Show success message
      setSuccessMessages(prev => [...prev, {
        id: `success_${Date.now()}`,
        message: 'Operation retried successfully'
      }])
    } catch (retryError) {
      console.error('Retry failed:', retryError)
    }
  }

  const dismissSuccessMessage = (id: string) => {
    setSuccessMessages(prev => prev.filter(msg => msg.id !== id))
  }

  // Global keyboard shortcut to dismiss all toasts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && (e.ctrlKey || e.metaKey)) {
        toastableErrors.forEach(error => clearError(error.id))
        setSuccessMessages([])
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [toastableErrors, clearError])

  if (toastableErrors.length === 0 && successMessages.length === 0) {
    return null
  }

  return (
    <>
      {/* Toast container */}
      <div
        className={`fixed ${getPositionClasses()} z-50 flex flex-col space-y-2 pointer-events-none`}
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
      >
        {/* Success messages */}
        {successMessages.map((msg) => (
          <SuccessToast
            key={msg.id}
            message={msg.message}
            onDismiss={() => dismissSuccessMessage(msg.id)}
          />
        ))}
        
        {/* Error toasts */}
        {toastableErrors.map((error) => (
          <ErrorToast
            key={error.id}
            error={error}
            onDismiss={() => clearError(error.id)}
            onRetry={error.retryable ? () => handleRetry(error.id) : undefined}
          />
        ))}
      </div>

      {/* Screen reader announcements */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {toastableErrors.map(error => (
          <div key={error.id}>
            Error: {error.message}
          </div>
        ))}
      </div>
    </>
  )
}

// Hook to show success messages
export function useSuccessToast() {
  const showSuccess = (message: string) => {
    // This would typically dispatch to a success toast context
    // For now, we'll use a custom event
    window.dispatchEvent(new CustomEvent('showSuccessToast', { detail: message }))
  }

  return { showSuccess }
}

export default ErrorToastSystem
