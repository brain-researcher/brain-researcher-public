'use client'

import React, { Component, ReactNode, ErrorInfo } from 'react'
import { ErrorFallbackPage } from './error-recovery'
import { ErrorCode } from './error-recovery'
import { AppError } from '@/contexts/ErrorContext'
import { serviceEndpoints } from '@/lib/service-endpoints'

interface Props {
  children: ReactNode
  fallback?: (error: Error, errorInfo: ErrorInfo, retry: () => void) => ReactNode
  onError?: (error: AppError) => void
  level?: 'app' | 'page' | 'component'
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
  errorId: string | null
}

export class GlobalErrorBoundary extends Component<Props, State> {
  private retryCount = 0
  private maxRetries = 3

  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null
    }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return {
      hasError: true,
      error
    }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('GlobalErrorBoundary caught error:', error, errorInfo)
    
    this.setState({ errorInfo })

    // Create structured error object
    const appError: AppError = {
      id: `boundary_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      code: this.getErrorCode(error),
      message: error.message,
      details: `Component error in ${this.props.level || 'unknown'} boundary`,
      timestamp: Date.now(),
      retryable: this.isRetryableError(error),
      severity: this.getErrorSeverity(error),
      stack: error.stack,
      componentStack: errorInfo.componentStack,
      context: {
        boundaryLevel: this.props.level,
        retryCount: this.retryCount,
        component: this.getComponentFromStack(errorInfo.componentStack)
      }
    }

    this.setState({ errorId: appError.id })

    // Report error to parent handler
    if (this.props.onError) {
      this.props.onError(appError)
    }

    // Report to global error tracking
    this.reportErrorToService(appError)
  }

  private getErrorCode(error: Error): ErrorCode {
    const message = error.message.toLowerCase()
    
    if (message.includes('network') || message.includes('fetch')) {
      return ErrorCode.NETWORK
    }
    if (message.includes('timeout')) {
      return ErrorCode.TIMEOUT
    }
    if (message.includes('chunk') || message.includes('loading')) {
      return ErrorCode.UNKNOWN // Could be a loading error
    }
    if (message.includes('permission') || message.includes('unauthorized')) {
      return ErrorCode.AUTH
    }
    if (message.includes('validation') || message.includes('invalid')) {
      return ErrorCode.VALIDATION
    }
    
    return ErrorCode.UNKNOWN
  }

  private getErrorSeverity(error: Error): 'low' | 'medium' | 'high' | 'critical' {
    const message = error.message.toLowerCase()
    
    // Critical errors that break the app
    if (message.includes('chunk') || 
        message.includes('script') ||
        error.name === 'ChunkLoadError') {
      return 'critical'
    }
    
    // High severity errors
    if (message.includes('network') || 
        message.includes('auth') ||
        message.includes('server')) {
      return 'high'
    }
    
    // Medium severity for most component errors
    if (this.props.level === 'app') {
      return 'critical'
    } else if (this.props.level === 'page') {
      return 'high'
    }
    
    return 'medium'
  }

  private isRetryableError(error: Error): boolean {
    const message = error.message.toLowerCase()
    
    // Network errors are usually retryable
    if (message.includes('network') || 
        message.includes('timeout') ||
        message.includes('fetch')) {
      return true
    }
    
    // Chunk loading errors are retryable
    if (message.includes('chunk') || error.name === 'ChunkLoadError') {
      return true
    }
    
    // Validation and programming errors are not retryable
    if (message.includes('validation') ||
        message.includes('undefined') ||
        message.includes('null') ||
        message.includes('reference')) {
      return false
    }
    
    return true
  }

  private getComponentFromStack(componentStack: string): string | undefined {
    const lines = componentStack.split('\n')
    for (const line of lines) {
      const match = line.trim().match(/^in (\w+)/)
      if (match && match[1] !== 'ErrorBoundary') {
        return match[1]
      }
    }
    return undefined
  }

  private async reportErrorToService(error: AppError) {
    try {
      const endpoint = serviceEndpoints.orchestrator('/api/errors/report')
      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // Flat structure matching backend ErrorReport schema
          message: error.message,
          code: error.code || 'UNKNOWN',
          details: error.componentStack || null,
          timestamp: error.timestamp, // Unix milliseconds (int)
          severity: error.severity || 'high',
          url: window.location.href,
          userAgent: navigator.userAgent,
          stack: error.stack || null,
          context: error.context || {},
          userId: null,
          sessionId: null
        })
      })
    } catch (reportingError) {
      console.error('Failed to report boundary error:', reportingError)
    }
  }

  private handleRetry = () => {
    if (this.retryCount < this.maxRetries) {
      this.retryCount++
      this.setState({
        hasError: false,
        error: null,
        errorInfo: null,
        errorId: null
      })
    } else {
      // Max retries reached, force page reload
      window.location.reload()
    }
  }

  private handleReset = () => {
    this.retryCount = 0
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      errorId: null
    })
  }

  render() {
    if (this.state.hasError && this.state.error) {
      // Use custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback(
          this.state.error, 
          this.state.errorInfo!, 
          this.handleRetry
        )
      }

      // Different fallbacks based on boundary level
      switch (this.props.level) {
        case 'app':
          return (
            <ErrorFallbackPage 
              error={this.state.error} 
              resetError={this.handleReset} 
            />
          )
        
        case 'page':
          return (
            <div className="min-h-[400px] flex items-center justify-center p-8">
              <div className="text-center max-w-md">
                <div className="mb-6">
                  <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 dark:bg-red-900/20 rounded-full mb-4">
                    <svg className="w-8 h-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  </div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                    Page Error
                  </h2>
                  <p className="text-gray-600 dark:text-gray-400 mb-4">
                    This page encountered an error and couldn't load properly.
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                    {this.state.error.message}
                  </p>
                </div>
                <div className="space-y-3">
                  {this.retryCount < this.maxRetries && (
                    <button
                      onClick={this.handleRetry}
                      className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      Try Again ({this.maxRetries - this.retryCount} attempts left)
                    </button>
                  )}
                  <button
                    onClick={() => window.location.href = '/'}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center justify-center gap-2"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                    </svg>
                    Go Home
                  </button>
                </div>
              </div>
            </div>
          )
        
        default: // component level
          return (
            <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <div className="flex-1">
                  <h3 className="font-medium text-red-900 dark:text-red-100 mb-1">
                    Component Error
                  </h3>
                  <p className="text-sm text-red-700 dark:text-red-300 mb-3">
                    {this.state.error.message}
                  </p>
                  {this.retryCount < this.maxRetries && (
                    <button
                      onClick={this.handleRetry}
                      className="text-sm bg-white dark:bg-gray-800 px-3 py-1 rounded border border-red-300 dark:border-red-600 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-900/30"
                    >
                      Retry ({this.maxRetries - this.retryCount} left)
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
      }
    }

    return this.props.children
  }
}

// Convenience components for different levels
export const AppErrorBoundary: React.FC<{ children: ReactNode; onError?: (error: AppError) => void }> = ({ 
  children, 
  onError 
}) => (
  <GlobalErrorBoundary level="app" onError={onError}>
    {children}
  </GlobalErrorBoundary>
)

export const PageErrorBoundary: React.FC<{ children: ReactNode; onError?: (error: AppError) => void }> = ({ 
  children, 
  onError 
}) => (
  <GlobalErrorBoundary level="page" onError={onError}>
    {children}
  </GlobalErrorBoundary>
)

export const ComponentErrorBoundary: React.FC<{ 
  children: ReactNode; 
  onError?: (error: AppError) => void;
  fallback?: (error: Error, errorInfo: ErrorInfo, retry: () => void) => ReactNode;
}> = ({ 
  children, 
  onError,
  fallback 
}) => (
  <GlobalErrorBoundary level="component" onError={onError} fallback={fallback}>
    {children}
  </GlobalErrorBoundary>
)

export default GlobalErrorBoundary
