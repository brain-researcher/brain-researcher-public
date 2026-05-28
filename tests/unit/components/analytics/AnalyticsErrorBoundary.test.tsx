/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AnalyticsErrorBoundary } from '@/components/analytics/AnalyticsErrorBoundary'
import '@testing-library/jest-dom'

// Mock console.error to avoid noise in tests
const originalError = console.error
beforeAll(() => {
  console.error = jest.fn()
})

afterAll(() => {
  console.error = originalError
})

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({ children, className }: any) => <div data-testid="card" className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div data-testid="card-content" className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div data-testid="card-header" className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <h3 data-testid="card-title" className={className}>{children}</h3>
}))

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, variant, size, className }: any) => (
    <button 
      data-testid="button"
      onClick={onClick} 
      data-variant={variant}
      data-size={size}
      className={className}
    >
      {children}
    </button>
  )
}))

jest.mock('@/components/ui/alert', () => ({
  Alert: ({ children, className }: any) => <div data-testid="alert" className={className}>{children}</div>,
  AlertDescription: ({ children, className }: any) => <div data-testid="alert-description" className={className}>{children}</div>,
  AlertTitle: ({ children, className }: any) => <h4 data-testid="alert-title" className={className}>{children}</h4>
}))

jest.mock('@/components/ui/collapsible', () => ({
  Collapsible: ({ children, open, onOpenChange }: any) => (
    <div data-testid="collapsible" data-open={open}>
      <button data-testid="collapsible-trigger" onClick={() => onOpenChange(!open)}>
        Toggle Details
      </button>
      {open && children}
    </div>
  ),
  CollapsibleContent: ({ children }: any) => (
    <div data-testid="collapsible-content">{children}</div>
  )
}))

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  AlertTriangle: ({ className }: any) => <span data-testid="alert-triangle-icon" className={className}>⚠️</span>,
  RefreshCw: ({ className }: any) => <span data-testid="refresh-cw-icon" className={className}>🔄</span>,
  Bug: ({ className }: any) => <span data-testid="bug-icon" className={className}>🐛</span>,
  ChevronDown: ({ className }: any) => <span data-testid="chevron-down-icon" className={className}>⌄</span>,
  ChevronRight: ({ className }: any) => <span data-testid="chevron-right-icon" className={className}>⌄</span>,
  Copy: ({ className }: any) => <span data-testid="copy-icon" className={className}>📋</span>,
  ExternalLink: ({ className }: any) => <span data-testid="external-link-icon" className={className}>🔗</span>
}))

// Mock cn utility
jest.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' ')
}))

// Test components that will throw errors
const ThrowError = ({ shouldThrow, errorMessage }: { shouldThrow: boolean; errorMessage?: string }) => {
  if (shouldThrow) {
    throw new Error(errorMessage || 'Test error')
  }
  return <div data-testid="working-component">Working component</div>
}

const AsyncThrowError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  React.useEffect(() => {
    if (shouldThrow) {
      setTimeout(() => {
        throw new Error('Async test error')
      }, 0)
    }
  }, [shouldThrow])
  
  return <div data-testid="async-component">Async component</div>
}

// Mock error reporting service
const mockErrorReporting = {
  reportError: jest.fn(),
  reportErrorWithContext: jest.fn()
}

jest.mock('@/lib/error-reporting', () => mockErrorReporting)

describe('AnalyticsErrorBoundary', () => {
  const mockOnError = jest.fn()
  const mockOnRetry = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
    ;(console.error as jest.Mock).mockClear()
  })

  describe('Normal Operation', () => {
    it('renders children when no error occurs', () => {
      render(
        <AnalyticsErrorBoundary>
          <div data-testid="child-component">Child component</div>
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('child-component')).toBeInTheDocument()
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument()
    })

    it('renders multiple children correctly', () => {
      render(
        <AnalyticsErrorBoundary>
          <div data-testid="child-1">Child 1</div>
          <div data-testid="child-2">Child 2</div>
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('child-1')).toBeInTheDocument()
      expect(screen.getByTestId('child-2')).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('catches and displays error when child throws', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Analytics component failed" />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.queryByTestId('working-component')).not.toBeInTheDocument()
      expect(screen.getByTestId('alert')).toBeInTheDocument()
      expect(screen.getByTestId('alert-title')).toHaveTextContent('Analytics Error')
      expect(screen.getByText('Analytics component failed')).toBeInTheDocument()
    })

    it('displays fallback UI when error occurs', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('card')).toBeInTheDocument()
      expect(screen.getByTestId('card-title')).toHaveTextContent('Analytics Unavailable')
      expect(screen.getByText('There was an error loading the analytics dashboard')).toBeInTheDocument()
    })

    it('shows retry button in error state', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const retryButton = screen.getByTestId('button')
      expect(retryButton).toBeInTheDocument()
      expect(retryButton).toHaveTextContent('Try Again')
    })

    it('shows error details toggle', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Detailed error message" />
        </AnalyticsErrorBoundary>
      )
      
      const collapsible = screen.getByTestId('collapsible')
      expect(collapsible).toBeInTheDocument()
      expect(screen.getByTestId('collapsible-trigger')).toBeInTheDocument()
    })
  })

  describe('Error Details', () => {
    it('displays error stack trace when expanded', async () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Stack trace error" />
        </AnalyticsErrorBoundary>
      )
      
      const toggle = screen.getByTestId('collapsible-trigger')
      await userEvent.click(toggle)
      
      expect(screen.getByTestId('collapsible-content')).toBeInTheDocument()
      expect(screen.getByText('Stack trace error')).toBeInTheDocument()
    })

    it('shows component stack information', async () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const toggle = screen.getByTestId('collapsible-trigger')
      await userEvent.click(toggle)
      
      // Should show component stack information
      expect(screen.getByTestId('collapsible-content')).toBeInTheDocument()
    })

    it('provides copy error button', async () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Copy test error" />
        </AnalyticsErrorBoundary>
      )
      
      const toggle = screen.getByTestId('collapsible-trigger')
      await userEvent.click(toggle)
      
      const copyButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('Copy Error')
      )
      expect(copyButton).toBeInTheDocument()
    })
  })

  describe('Retry Functionality', () => {
    it('resets error boundary when retry is clicked', async () => {
      const { rerender } = render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('alert')).toBeInTheDocument()
      
      const retryButton = screen.getByTestId('button')
      await userEvent.click(retryButton)
      
      // Re-render with working component
      rerender(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={false} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('working-component')).toBeInTheDocument()
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument()
    })

    it('calls onRetry callback when provided', async () => {
      render(
        <AnalyticsErrorBoundary onRetry={mockOnRetry}>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const retryButton = screen.getByTestId('button')
      await userEvent.click(retryButton)
      
      expect(mockOnRetry).toHaveBeenCalledTimes(1)
    })

    it('allows custom retry button text', () => {
      render(
        <AnalyticsErrorBoundary retryButtonText="Reload Analytics">
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const retryButton = screen.getByTestId('button')
      expect(retryButton).toHaveTextContent('Reload Analytics')
    })
  })

  describe('Custom Error Messages', () => {
    it('displays custom fallback message', () => {
      render(
        <AnalyticsErrorBoundary fallbackMessage="Custom analytics error occurred">
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByText('Custom analytics error occurred')).toBeInTheDocument()
    })

    it('displays custom title', () => {
      render(
        <AnalyticsErrorBoundary title="Dashboard Error">
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('card-title')).toHaveTextContent('Dashboard Error')
    })

    it('shows support contact information when provided', () => {
      render(
        <AnalyticsErrorBoundary supportContact="support@example.com">
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByText(/contact support at support@example.com/i)).toBeInTheDocument()
    })
  })

  describe('Error Reporting', () => {
    it('calls onError callback when error occurs', () => {
      render(
        <AnalyticsErrorBoundary onError={mockOnError}>
          <ThrowError shouldThrow={true} errorMessage="Callback test error" />
        </AnalyticsErrorBoundary>
      )
      
      expect(mockOnError).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Callback test error'
        }),
        expect.objectContaining({
          componentStack: expect.stringContaining('ThrowError')
        })
      )
    })

    it('reports error to external service', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="External service error" />
        </AnalyticsErrorBoundary>
      )
      
      expect(mockErrorReporting.reportErrorWithContext).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'External service error'
        }),
        expect.objectContaining({
          component: 'AnalyticsErrorBoundary',
          context: 'analytics_dashboard'
        })
      )
    })

    it('includes error boundary ID in reports', () => {
      render(
        <AnalyticsErrorBoundary errorBoundaryId="test-analytics-boundary">
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(mockErrorReporting.reportErrorWithContext).toHaveBeenCalledWith(
        expect.any(Error),
        expect.objectContaining({
          boundaryId: 'test-analytics-boundary'
        })
      )
    })
  })

  describe('Development Features', () => {
    it('shows detailed error information in development', () => {
      const originalEnv = process.env.NODE_ENV
      process.env.NODE_ENV = 'development'
      
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Development error" />
        </AnalyticsErrorBoundary>
      )
      
      // Should show more detailed error information
      expect(screen.getByText('Development error')).toBeInTheDocument()
      
      process.env.NODE_ENV = originalEnv
    })

    it('hides sensitive information in production', () => {
      const originalEnv = process.env.NODE_ENV
      process.env.NODE_ENV = 'production'
      
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Sensitive production error" />
        </AnalyticsErrorBoundary>
      )
      
      // Should show generic error message in production
      expect(screen.queryByText('Sensitive production error')).not.toBeInTheDocument()
      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
      
      process.env.NODE_ENV = originalEnv
    })
  })

  describe('Accessibility', () => {
    it('provides proper ARIA labels for error state', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const alert = screen.getByTestId('alert')
      expect(alert).toHaveAttribute('role', 'alert')
      
      const heading = screen.getByRole('heading', { level: 3 })
      expect(heading).toBeInTheDocument()
    })

    it('supports keyboard navigation', async () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const retryButton = screen.getByTestId('button')
      retryButton.focus()
      
      expect(document.activeElement).toBe(retryButton)
      
      // Should be able to activate with Enter key
      fireEvent.keyDown(retryButton, { key: 'Enter' })
      fireEvent.click(retryButton)
      
      expect(retryButton).toBeInTheDocument()
    })

    it('provides screen reader friendly content', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const alertDescription = screen.getByTestId('alert-description')
      expect(alertDescription).toHaveTextContent(/analytics dashboard.*error/i)
    })
  })

  describe('Performance Considerations', () => {
    it('does not re-render when error state is stable', () => {
      const renderSpy = jest.fn()
      const TestComponent = () => {
        renderSpy()
        return <ThrowError shouldThrow={true} />
      }
      
      const { rerender } = render(
        <AnalyticsErrorBoundary>
          <TestComponent />
        </AnalyticsErrorBoundary>
      )
      
      expect(renderSpy).toHaveBeenCalledTimes(1)
      
      // Re-render with same props
      rerender(
        <AnalyticsErrorBoundary>
          <TestComponent />
        </AnalyticsErrorBoundary>
      )
      
      // TestComponent should not re-render in error state
      expect(renderSpy).toHaveBeenCalledTimes(1)
    })

    it('handles memory cleanup properly', () => {
      const { unmount } = render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      // Should unmount without errors
      unmount()
      
      // Error reporting should have been called
      expect(mockErrorReporting.reportErrorWithContext).toHaveBeenCalled()
    })
  })

  describe('Edge Cases', () => {
    it('handles errors with no message', () => {
      const EmptyErrorComponent = () => {
        throw new Error()
      }
      
      render(
        <AnalyticsErrorBoundary>
          <EmptyErrorComponent />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('alert')).toBeInTheDocument()
      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
    })

    it('handles non-Error objects being thrown', () => {
      const StringErrorComponent = () => {
        throw 'String error' // eslint-disable-line no-throw-literal
      }
      
      render(
        <AnalyticsErrorBoundary>
          <StringErrorComponent />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByTestId('alert')).toBeInTheDocument()
      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
    })

    it('handles recursive error boundaries', () => {
      render(
        <AnalyticsErrorBoundary>
          <AnalyticsErrorBoundary>
            <ThrowError shouldThrow={true} errorMessage="Nested error" />
          </AnalyticsErrorBoundary>
        </AnalyticsErrorBoundary>
      )
      
      // Inner boundary should catch the error
      expect(screen.getByTestId('alert')).toBeInTheDocument()
      expect(screen.getByText('Nested error')).toBeInTheDocument()
    })
  })

  describe('Integration with Analytics Components', () => {
    it('provides appropriate context for analytics errors', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} errorMessage="Chart rendering failed" />
        </AnalyticsErrorBoundary>
      )
      
      expect(mockErrorReporting.reportErrorWithContext).toHaveBeenCalledWith(
        expect.any(Error),
        expect.objectContaining({
          context: 'analytics_dashboard'
        })
      )
    })

    it('suggests relevant troubleshooting steps', () => {
      render(
        <AnalyticsErrorBoundary>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      expect(screen.getByText(/try refreshing the page/i)).toBeInTheDocument()
      expect(screen.getByText(/check your connection/i)).toBeInTheDocument()
    })

    it('provides analytics-specific error recovery options', () => {
      render(
        <AnalyticsErrorBoundary showAlternativeData={true}>
          <ThrowError shouldThrow={true} />
        </AnalyticsErrorBoundary>
      )
      
      const alternativeDataButton = screen.getAllByTestId('button').find(
        btn => btn.textContent?.includes('View Cached Data')
      )
      expect(alternativeDataButton).toBeInTheDocument()
    })
  })
})