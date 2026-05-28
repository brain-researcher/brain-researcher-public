# Error Boundary System Usage Guide

## 🚀 Quick Start

The error boundary system is automatically integrated into your app. Here's how to use it:

### Basic Usage

```tsx
// The ErrorProvider is already set up in app layout
// Just use the error context in any component

import { useErrorHandler } from '@/contexts/ErrorContext'

function MyComponent() {
  const { addError } = useErrorHandler()
  
  const handleAction = async () => {
    try {
      await riskyOperation()
    } catch (error) {
      addError({
        code: ErrorCode.TOOL_ERROR,
        message: 'Failed to process brain data',
        details: error.message,
        retryable: true,
        severity: 'medium',
        context: { operation: 'brain_analysis', tool: 'nilearn' }
      })
    }
  }
  
  return <button onClick={handleAction}>Process Data</button>
}
```

### Using Error Boundaries for Components

```tsx
import { ComponentErrorBoundary } from '@/components/error/GlobalErrorBoundary'

function App() {
  return (
    <ComponentErrorBoundary>
      <RiskyComponent />
    </ComponentErrorBoundary>
  )
}
```

### Manual Error Reporting

```tsx
import { useErrorReporting } from '@/contexts/ErrorContext'

function MyComponent() {
  const { reportError } = useErrorReporting()
  
  const handleError = () => {
    reportError('User clicked broken feature', {
      code: ErrorCode.TOOL_ERROR,
      severity: 'low',
      context: { feature: 'experimental_analysis' }
    })
  }
}
```

## 🎯 Error Types and Codes

### Available Error Codes

```tsx
import { ErrorCode } from '@/contexts/ErrorContext'

ErrorCode.NETWORK        // Network/connection issues
ErrorCode.TIMEOUT        // Operation timeouts
ErrorCode.AUTH          // Authentication/authorization
ErrorCode.VALIDATION    // Input validation errors
ErrorCode.RATE_LIMIT    // Rate limiting
ErrorCode.SERVER        // Server errors
ErrorCode.STORAGE       // Browser storage issues
ErrorCode.TOOL_ERROR    // Analysis tool failures
ErrorCode.DEMO_UNAVAILABLE // Demo service unavailable
ErrorCode.UNKNOWN       // Unknown errors
```

### Severity Levels

```tsx
type Severity = 'low' | 'medium' | 'high' | 'critical'

// low: User can continue, minimal impact
// medium: Feature unavailable, workarounds exist
// high: Significant functionality affected
// critical: App-breaking, requires immediate attention
```

## 🛠️ Advanced Usage

### Custom Error Boundaries

```tsx
import { GlobalErrorBoundary } from '@/components/error/GlobalErrorBoundary'

function CustomBoundary({ children }) {
  return (
    <GlobalErrorBoundary 
      level="component"
      fallback={(error, errorInfo, retry) => (
        <div className="custom-error">
          <h2>Oops! {error.message}</h2>
          <button onClick={retry}>Try Again</button>
        </div>
      )}
      onError={(error) => {
        console.log('Custom error handling:', error)
      }}
    >
      {children}
    </GlobalErrorBoundary>
  )
}
```

### Error Recovery with Retry Logic

```tsx
import { RetryHelper } from '@/lib/error-utils'

async function fetchDataWithRetry() {
  return await RetryHelper.withRetry(
    async () => {
      const response = await fetch('/api/data')
      if (!response.ok) throw new Error('Fetch failed')
      return response.json()
    },
    {
      maxAttempts: 3,
      baseDelay: 1000,
      backoffFactor: 2
    }
  )
}
```

### Error Classification

```tsx
import { classifyError, createAppError } from '@/lib/error-utils'

function handleUnknownError(error: Error) {
  const classification = classifyError(error)
  const appError = createAppError(error, {
    context: { component: 'DataProcessor' }
  })
  
  addError(appError)
}
```

## 🎨 Toast Notifications

Toast notifications are automatically displayed for appropriate errors. The system:

- Shows max 4 toasts at once
- Auto-dismisses low severity errors after 5 seconds
- Provides retry buttons for retryable errors
- Respects user's reduced-motion preferences

### Toast Positioning

```tsx
// In your providers setup
<ErrorToastSystem 
  position="top-right"    // top-right, top-left, bottom-right, bottom-left
  maxToasts={4}           // Maximum toasts to show
/>
```

## 🧪 Testing Error Scenarios

### Testing Components with Error Boundaries

```tsx
import { render, screen } from '@testing-library/react'
import { ErrorProvider } from '@/contexts/ErrorContext'

function renderWithErrorBoundary(component) {
  return render(
    <ErrorProvider>
      {component}
    </ErrorProvider>
  )
}

test('handles errors gracefully', () => {
  const ThrowError = () => {
    throw new Error('Test error')
  }
  
  renderWithErrorBoundary(<ThrowError />)
  expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
})
```

### Simulating Different Error Types

```tsx
// Network error simulation
const networkError = new Error('Failed to fetch')
networkError.name = 'NetworkError'

// Authentication error simulation  
const authError = new Error('401 Unauthorized')

// Validation error simulation
const validationError = new Error('Validation failed: email required')
```

## 🔧 Configuration

### Environment Variables

```bash
# Error reporting configuration
ERROR_REPORTING_WEBHOOK=https://monitoring.example.com/errors
ERROR_REPORTING_TOKEN=your_webhook_token
STORE_ERROR_REPORTS=true
DATABASE_URL=postgresql://...

# Development vs Production
NODE_ENV=production  # Affects stack trace inclusion
```

### Runtime Configuration

```tsx
// In your app setup
<ErrorProvider
  maxErrors={25}                    // Max errors to keep in memory
  enableAutoReport={true}           // Auto-report errors to API
  onGlobalError={(error) => {       // Custom global error handler
    if (error.severity === 'critical') {
      // Send to monitoring service
      monitoringService.alert(error)
    }
  }}
>
  <App />
</ErrorProvider>
```

## 🎯 Brain Researcher Specific Usage

### Handling Neuroimaging Tool Errors

```tsx
import { useErrorHandler, ErrorCode } from '@/contexts/ErrorContext'

function NeuroimagingAnalysis() {
  const { addError } = useErrorHandler()
  
  const runAnalysis = async () => {
    try {
      await nilearn.processData(data)
    } catch (error) {
      addError({
        code: ErrorCode.TOOL_ERROR,
        message: 'Brain analysis failed',
        details: error.message,
        retryable: true,
        severity: 'medium',
        context: {
          tool: 'nilearn',
          analysisType: 'GLM',
          datasetSize: data.length,
          parameters: analysisParams
        }
      })
    }
  }
}
```

### Dataset Loading Errors

```tsx
function DatasetLoader() {
  const { addError } = useErrorHandler()
  
  const loadDataset = async (datasetId) => {
    try {
      const dataset = await fetchDataset(datasetId)
      return dataset
    } catch (error) {
      const errorCode = error.status === 404 
        ? ErrorCode.VALIDATION 
        : ErrorCode.NETWORK
        
      addError({
        code: errorCode,
        message: `Failed to load dataset ${datasetId}`,
        details: error.message,
        retryable: errorCode === ErrorCode.NETWORK,
        severity: 'high',
        context: { datasetId, operation: 'dataset_load' }
      })
    }
  }
}
```

## 📊 Monitoring and Analytics

The error system integrates with analytics:

```tsx
// Errors are automatically tracked with:
{
  event: 'error_occurred',
  properties: {
    error_code: 'E_NETWORK',
    error_severity: 'medium',
    component_stack: '...',
    user_agent: '...',
    url: '...'
  }
}
```

## ♿ Accessibility Features

The error system is fully accessible:

- **Screen Reader Support**: Errors are announced to screen readers
- **Keyboard Navigation**: All error actions are keyboard accessible
- **High Contrast**: Error indicators meet WCAG contrast requirements
- **Focus Management**: Focus is properly managed during error states

## 🔒 Security Notes

- Error messages are sanitized to prevent XSS
- Sensitive data is filtered from error reports
- Stack traces are only included in development
- Rate limiting prevents error report spam
- User data is anonymized in error reports

## 📈 Performance Considerations

- Error processing is non-blocking
- Toast animations use CSS transforms
- Error history is limited to prevent memory leaks
- Error deduplication prevents excessive notifications
- Background error reporting doesn't block UI

## 🚨 Troubleshooting

### Common Issues

1. **Errors not showing**: Check that ErrorProvider wraps your app
2. **Toast not appearing**: Verify error severity allows toast display
3. **Recovery not working**: Ensure error is marked as `retryable: true`
4. **API reporting failing**: Check network and authentication

### Debug Mode

```tsx
// Enable debug logging
<ErrorProvider
  onGlobalError={(error) => {
    console.debug('Error details:', error)
  }}
>
```

## 📚 Best Practices

1. **Use appropriate error codes** for better categorization
2. **Provide context** in error objects for debugging
3. **Mark errors as retryable** when appropriate
4. **Use descriptive messages** that help users understand what happened
5. **Test error scenarios** in your components
6. **Monitor error patterns** to identify common issues
7. **Keep error messages user-friendly** and actionable

## 🎉 Success!

You now have a comprehensive error boundary system that provides excellent user experience and robust error handling for the Brain Researcher application!