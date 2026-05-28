import { ErrorCode, AppError } from '@/contexts/ErrorContext'

// Error classification utilities
export function classifyError(error: Error | string): {
  code: ErrorCode
  severity: 'low' | 'medium' | 'high' | 'critical'
  retryable: boolean
  context?: Record<string, any>
} {
  const message = typeof error === 'string' ? error : error.message
  const lowercaseMessage = message.toLowerCase()

  // Network errors
  if (lowercaseMessage.includes('fetch') || 
      lowercaseMessage.includes('network') ||
      lowercaseMessage.includes('connection')) {
    return {
      code: ErrorCode.NETWORK,
      severity: 'medium',
      retryable: true,
      context: { type: 'network', originalMessage: message }
    }
  }

  // Timeout errors
  if (lowercaseMessage.includes('timeout') || 
      lowercaseMessage.includes('timed out')) {
    return {
      code: ErrorCode.TIMEOUT,
      severity: 'medium',
      retryable: true,
      context: { type: 'timeout', originalMessage: message }
    }
  }

  // Authentication errors
  if (lowercaseMessage.includes('unauthorized') || 
      lowercaseMessage.includes('forbidden') ||
      lowercaseMessage.includes('authentication') ||
      lowercaseMessage.includes('401') ||
      lowercaseMessage.includes('403')) {
    return {
      code: ErrorCode.AUTH,
      severity: 'high',
      retryable: false,
      context: { type: 'auth', originalMessage: message }
    }
  }

  // Validation errors
  if (lowercaseMessage.includes('validation') || 
      lowercaseMessage.includes('invalid') ||
      lowercaseMessage.includes('required') ||
      lowercaseMessage.includes('must be')) {
    return {
      code: ErrorCode.VALIDATION,
      severity: 'low',
      retryable: false,
      context: { type: 'validation', originalMessage: message }
    }
  }

  // Rate limiting
  if (lowercaseMessage.includes('rate limit') || 
      lowercaseMessage.includes('too many requests') ||
      lowercaseMessage.includes('429')) {
    return {
      code: ErrorCode.RATE_LIMIT,
      severity: 'medium',
      retryable: true,
      context: { type: 'rate_limit', originalMessage: message }
    }
  }

  // Server errors
  if (lowercaseMessage.includes('server error') || 
      lowercaseMessage.includes('500') ||
      lowercaseMessage.includes('502') ||
      lowercaseMessage.includes('503') ||
      lowercaseMessage.includes('504')) {
    return {
      code: ErrorCode.SERVER,
      severity: 'high',
      retryable: true,
      context: { type: 'server', originalMessage: message }
    }
  }

  // Storage/quota errors
  if (lowercaseMessage.includes('quota') || 
      lowercaseMessage.includes('storage') ||
      lowercaseMessage.includes('localstorage') ||
      lowercaseMessage.includes('disk full')) {
    return {
      code: ErrorCode.STORAGE,
      severity: 'medium',
      retryable: false,
      context: { type: 'storage', originalMessage: message }
    }
  }

  // Chunk loading errors (critical for app functionality)
  if (lowercaseMessage.includes('chunk') || 
      lowercaseMessage.includes('loading chunk') ||
      error instanceof Error && error.name === 'ChunkLoadError') {
    return {
      code: ErrorCode.UNKNOWN,
      severity: 'critical',
      retryable: true,
      context: { type: 'chunk_loading', originalMessage: message, errorName: error instanceof Error ? error.name : undefined }
    }
  }

  // Tool/processing errors
  if (lowercaseMessage.includes('tool') || 
      lowercaseMessage.includes('processing') ||
      lowercaseMessage.includes('analysis')) {
    return {
      code: ErrorCode.TOOL_ERROR,
      severity: 'medium',
      retryable: true,
      context: { type: 'tool_processing', originalMessage: message }
    }
  }

  // Default classification
  return {
    code: ErrorCode.UNKNOWN,
    severity: 'medium',
    retryable: false,
    context: { type: 'unknown', originalMessage: message }
  }
}

// Create standardized error object
export function createAppError(
  error: Error | string,
  additionalContext?: Partial<AppError>
): Omit<AppError, 'id' | 'timestamp'> {
  const classification = classifyError(error)
  const baseError = typeof error === 'string' ? new Error(error) : error

  return {
    code: classification.code,
    message: baseError.message,
    details: additionalContext?.details,
    retryable: classification.retryable,
    severity: classification.severity,
    stack: baseError.stack,
    context: {
      ...classification.context,
      ...additionalContext?.context
    },
    ...additionalContext
  }
}

// Error boundary helpers
export function shouldErrorBubbleUp(error: Error): boolean {
  const message = error.message.toLowerCase()
  
  // These errors should bubble up to higher boundaries
  return (
    message.includes('chunk') ||
    message.includes('script') ||
    error.name === 'ChunkLoadError' ||
    message.includes('module') ||
    message.includes('import')
  )
}

export function isUserFacingError(error: Error): boolean {
  const message = error.message.toLowerCase()
  
  // Internal React/development errors that shouldn't be shown to users
  const internalErrors = [
    'non-error promise rejection',
    'hydration',
    'cannot read prop',
    'cannot access before initialization',
    'unexpected token',
    'syntax error'
  ]
  
  return !internalErrors.some(internal => message.includes(internal))
}

// Retry strategies
export interface RetryOptions {
  maxAttempts: number
  baseDelay: number
  maxDelay: number
  backoffFactor: number
  jitter: boolean
}

export class RetryHelper {
  private static defaultOptions: RetryOptions = {
    maxAttempts: 3,
    baseDelay: 1000,
    maxDelay: 10000,
    backoffFactor: 2,
    jitter: true
  }

  static async withRetry<T>(
    operation: () => Promise<T>,
    options: Partial<RetryOptions> = {}
  ): Promise<T> {
    const config = { ...this.defaultOptions, ...options }
    let lastError: Error | null = null

    for (let attempt = 1; attempt <= config.maxAttempts; attempt++) {
      try {
        return await operation()
      } catch (error) {
        lastError = error as Error
        
        // Don't retry on the last attempt
        if (attempt === config.maxAttempts) break
        
        // Don't retry non-retryable errors
        const classification = classifyError(lastError)
        if (!classification.retryable) break
        
        // Calculate delay with exponential backoff
        const delay = Math.min(
          config.baseDelay * Math.pow(config.backoffFactor, attempt - 1),
          config.maxDelay
        )
        
        // Add jitter to prevent thundering herd
        const jitteredDelay = config.jitter 
          ? delay * (0.5 + Math.random() * 0.5)
          : delay
        
        await new Promise(resolve => setTimeout(resolve, jitteredDelay))
      }
    }

    throw lastError
  }

  static getRetryDelay(attempt: number, options: Partial<RetryOptions> = {}): number {
    const config = { ...this.defaultOptions, ...options }
    const delay = Math.min(
      config.baseDelay * Math.pow(config.backoffFactor, attempt - 1),
      config.maxDelay
    )
    
    return config.jitter 
      ? delay * (0.5 + Math.random() * 0.5)
      : delay
  }
}

// Error logging utilities
export function sanitizeErrorForLogging(error: AppError): Record<string, any> {
  return {
    id: error.id,
    code: error.code,
    message: error.message?.substring(0, 500),
    severity: error.severity,
    retryable: error.retryable,
    timestamp: error.timestamp,
    context: error.context ? Object.keys(error.context).reduce((acc, key) => {
      const value = error.context![key]
      // Only include safe context data
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        acc[key] = typeof value === 'string' ? value.substring(0, 200) : value
      }
      return acc
    }, {} as Record<string, any>) : undefined,
    url: error.url?.substring(0, 300),
    userId: error.userId?.substring(0, 50)
  }
}

// Performance monitoring integration
export function measureErrorImpact(error: AppError): {
  userImpact: 'low' | 'medium' | 'high' | 'critical'
  businessImpact: 'low' | 'medium' | 'high' | 'critical'
  technicalImpact: 'low' | 'medium' | 'high' | 'critical'
} {
  const userImpact = (() => {
    switch (error.severity) {
      case 'critical': return 'critical'
      case 'high': return 'high'
      case 'medium': return 'medium'
      case 'low': return 'low'
    }
  })()

  const businessImpact = (() => {
    if (error.code === ErrorCode.AUTH) return 'high'
    if (error.code === ErrorCode.SERVER) return 'high'
    if (error.code === ErrorCode.NETWORK) return 'medium'
    if (error.code === ErrorCode.TOOL_ERROR) return 'medium'
    return 'low'
  })()

  const technicalImpact = (() => {
    if (error.severity === 'critical') return 'critical'
    if (error.code === ErrorCode.SERVER) return 'high'
    if (error.code === ErrorCode.NETWORK) return 'medium'
    return 'low'
  })()

  return { userImpact, businessImpact, technicalImpact }
}

// Browser compatibility helpers
export function getBrowserErrorContext(): Record<string, any> {
  if (typeof window === 'undefined') return {}

  return {
    userAgent: navigator.userAgent,
    language: navigator.language,
    platform: navigator.platform,
    cookieEnabled: navigator.cookieEnabled,
    onLine: navigator.onLine,
    screen: {
      width: screen.width,
      height: screen.height,
      colorDepth: screen.colorDepth
    },
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight
    },
    localStorage: (() => {
      try {
        return !!window.localStorage
      } catch {
        return false
      }
    })(),
    sessionStorage: (() => {
      try {
        return !!window.sessionStorage
      } catch {
        return false
      }
    })()
  }
}

const errorUtilities = {
  classifyError,
  createAppError,
  shouldErrorBubbleUp,
  isUserFacingError,
  RetryHelper,
  sanitizeErrorForLogging,
  measureErrorImpact,
  getBrowserErrorContext
}

export default errorUtilities
