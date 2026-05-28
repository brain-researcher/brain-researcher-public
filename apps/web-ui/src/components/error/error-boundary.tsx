'use client'

import React, { Component, ReactNode } from 'react'
import { AlertTriangle, RefreshCw, Home, ArrowLeft, ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Custom fallback component */
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode)
  /** Page/component name for better error messages */
  name?: string
  /** Callback when error occurs */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
  /** Show retry button (default: true) */
  showRetry?: boolean
  /** Show navigation buttons (default: true) */
  showNavigation?: boolean
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  errorInfo: React.ErrorInfo | null
  showDetails: boolean
}

/**
 * React Error Boundary component for catching render errors.
 *
 * Usage:
 * ```tsx
 * <ErrorBoundary name="RunDetail">
 *   <RunDetailPage />
 * </ErrorBoundary>
 * ```
 *
 * Or with custom fallback:
 * ```tsx
 * <ErrorBoundary
 *   fallback={(error, reset) => <CustomError error={error} onRetry={reset} />}
 * >
 *   <MyComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    this.setState({ errorInfo })

    // Log error
    console.error('ErrorBoundary caught an error:', error, errorInfo)

    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo)
    }

    // Report error to backend (non-blocking)
    this.reportError(error, errorInfo)
  }

  private reportError = async (error: Error, errorInfo: React.ErrorInfo) => {
    try {
      await fetch('/api/errors/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: error.message,
          stack: error.stack,
          componentStack: errorInfo.componentStack,
          name: this.props.name || 'unknown',
          url: typeof window !== 'undefined' ? window.location.href : '',
          userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
          timestamp: new Date().toISOString(),
        }),
      })
    } catch (e) {
      // Silently fail - don't want to cause more errors
      console.warn('Failed to report error:', e)
    }
  }

  private reset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    })
  }

  private toggleDetails = () => {
    this.setState(prev => ({ showDetails: !prev.showDetails }))
  }

  render() {
    const { hasError, error, errorInfo, showDetails } = this.state
    const { children, fallback, name, showRetry = true, showNavigation = true } = this.props

    if (!hasError || !error) {
      return children
    }

    // Use custom fallback if provided
    if (fallback) {
      if (typeof fallback === 'function') {
        return fallback(error, this.reset)
      }
      return fallback
    }

    // Default error UI
    return (
      <div className="min-h-[400px] flex items-center justify-center p-6">
        <div className="max-w-lg w-full">
          <div className="text-center mb-6">
            <div className="inline-flex items-center justify-center w-14 h-14 bg-red-100 dark:bg-red-900/20 rounded-full mb-4">
              <AlertTriangle className="h-7 w-7 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
              {name ? `Failed to load ${name}` : 'Something went wrong'}
            </h2>
            <p className="text-gray-600 dark:text-gray-400 text-sm">
              An error occurred while rendering this page. Please try again.
            </p>
          </div>

          {/* Error message */}
          <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
            <p className="text-sm text-red-800 dark:text-red-300 font-mono break-words">
              {error.message || 'Unknown error'}
            </p>
          </div>

          {/* Expandable details */}
          {(error.stack || errorInfo?.componentStack) && (
            <div className="mb-4">
              <button
                onClick={this.toggleDetails}
                className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {showDetails ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
                {showDetails ? 'Hide' : 'Show'} technical details
              </button>

              {showDetails && (
                <div className="mt-2 p-3 bg-gray-100 dark:bg-gray-800 rounded-lg text-xs font-mono overflow-auto max-h-48">
                  {error.stack && (
                    <pre className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap mb-2">
                      {error.stack}
                    </pre>
                  )}
                  {errorInfo?.componentStack && (
                    <>
                      <p className="text-gray-500 dark:text-gray-400 mb-1">Component stack:</p>
                      <pre className="text-gray-600 dark:text-gray-400 whitespace-pre-wrap">
                        {errorInfo.componentStack}
                      </pre>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap items-center justify-center gap-3">
            {showRetry && (
              <Button onClick={this.reset} className="flex items-center gap-2">
                <RefreshCw className="h-4 w-4" />
                Try Again
              </Button>
            )}
            {showNavigation && (
              <>
                <Button
                  variant="outline"
                  onClick={() => window.history.back()}
                  className="flex items-center gap-2"
                >
                  <ArrowLeft className="h-4 w-4" />
                  Go Back
                </Button>
                <Button
                  variant="outline"
                  onClick={() => (window.location.href = '/')}
                  className="flex items-center gap-2"
                >
                  <Home className="h-4 w-4" />
                  Home
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }
}

/**
 * Higher-order component to wrap a component with an error boundary.
 *
 * Usage:
 * ```tsx
 * const SafeRunDetail = withErrorBoundary(RunDetailPage, { name: 'Run Detail' })
 * ```
 */
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  options?: Omit<ErrorBoundaryProps, 'children'>
) {
  return function WithErrorBoundary(props: P) {
    return (
      <ErrorBoundary {...options}>
        <WrappedComponent {...props} />
      </ErrorBoundary>
    )
  }
}

/**
 * Simple error display component for API/fetch errors (not render errors).
 * Use this for data loading failures where ErrorBoundary doesn't apply.
 */
export function PageError({
  title = 'Failed to load',
  message,
  onRetry,
  showHome = true,
}: {
  title?: string
  message?: string
  onRetry?: () => void
  showHome?: boolean
}) {
  return (
    <div className="min-h-[300px] flex items-center justify-center p-6">
      <div className="text-center max-w-md">
        <div className="inline-flex items-center justify-center w-12 h-12 bg-red-100 dark:bg-red-900/20 rounded-full mb-4">
          <AlertTriangle className="h-6 w-6 text-red-600 dark:text-red-400" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
          {title}
        </h3>
        {message && (
          <p className="text-gray-600 dark:text-gray-400 text-sm mb-4">{message}</p>
        )}
        <div className="flex items-center justify-center gap-3">
          {onRetry && (
            <Button onClick={onRetry} size="sm" className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          )}
          {showHome && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => (window.location.href = '/')}
              className="flex items-center gap-2"
            >
              <Home className="h-4 w-4" />
              Home
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export default ErrorBoundary
