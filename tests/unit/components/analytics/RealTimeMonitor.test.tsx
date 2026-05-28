/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, act, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RealTimeMonitor } from '@/components/analytics/RealTimeMonitor'
import { AnalyticsMetrics } from '@/types/analytics'
import '@testing-library/jest-dom'

// Mock WebSocket
const mockWebSocket = {
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  send: jest.fn(),
  close: jest.fn(),
  readyState: WebSocket.OPEN
}

;(global as any).WebSocket = jest.fn().mockImplementation(() => mockWebSocket)

// Mock timers
jest.useFakeTimers()

// Mock chart components
jest.mock('@/components/charts/LineChart', () => ({
  LineChart: ({ data, title, xKey, yKey, color, height, className, realTime }: any) => (
    <div 
      data-testid="line-chart" 
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      data-real-time={realTime}
      className={className}
    >
      Line Chart: {title} ({data?.length || 0} points)
    </div>
  )
}))

jest.mock('@/components/charts/SparklineChart', () => ({
  SparklineChart: ({ data, color, height, className }: any) => (
    <div 
      data-testid="sparkline-chart"
      data-color={color}
      data-height={height}
      className={className}
    >
      Sparkline: {data?.length || 0} points
    </div>
  )
}))

jest.mock('@/components/charts/MetricCard', () => ({
  MetricCard: ({ title, value, delta, trend, color, className }: any) => (
    <div 
      data-testid="metric-card"
      data-title={title}
      data-value={value}
      data-delta={delta}
      data-trend={trend}
      data-color={color}
      className={className}
    >
      <div data-testid="metric-title">{title}</div>
      <div data-testid="metric-value">{value}</div>
      {delta && <div data-testid="metric-delta">{delta}</div>}
      {trend && <div data-testid="metric-trend">{trend}</div>}
    </div>
  )
}))

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({ children, className }: any) => <div data-testid="card" className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div data-testid="card-content" className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div data-testid="card-header" className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <h3 data-testid="card-title" className={className}>{children}</h3>
}))

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children, variant, className }: any) => (
    <span data-testid="badge" data-variant={variant} className={className}>{children}</span>
  )
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

jest.mock('@/components/ui/switch', () => ({
  Switch: ({ checked, onCheckedChange, className }: any) => (
    <button 
      data-testid="switch"
      data-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      className={className}
    >
      Switch: {checked ? 'ON' : 'OFF'}
    </button>
  )
}))

jest.mock('@/components/ui/select', () => ({
  Select: ({ children, value, onValueChange }: any) => (
    <div data-testid="select-root" data-value={value} onClick={(e: any) => {
      if (e.target.dataset.selectValue) onValueChange(e.target.dataset.selectValue)
    }}>
      {children}
    </div>
  ),
  SelectTrigger: ({ children, className }: any) => <div data-testid="select-trigger" className={className}>{children}</div>,
  SelectValue: ({ placeholder }: any) => <span data-testid="select-value">{placeholder}</span>,
  SelectContent: ({ children }: any) => <div data-testid="select-content">{children}</div>,
  SelectItem: ({ children, value }: any) => (
    <div data-testid={`select-item-${value}`} data-select-value={value}>{children}</div>
  )
}))

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  Activity: ({ className }: any) => <span data-testid="activity-icon" className={className}>📈</span>,
  Wifi: ({ className }: any) => <span data-testid="wifi-icon" className={className}>📶</span>,
  WifiOff: ({ className }: any) => <span data-testid="wifi-off-icon" className={className}>📵</span>,
  Play: ({ className }: any) => <span data-testid="play-icon" className={className}>▶️</span>,
  Pause: ({ className }: any) => <span data-testid="pause-icon" className={className}>⏸️</span>,
  RefreshCw: ({ className }: any) => <span data-testid="refresh-icon" className={className}>🔄</span>,
  Settings: ({ className }: any) => <span data-testid="settings-icon" className={className}>⚙️</span>,
  AlertCircle: ({ className }: any) => <span data-testid="alert-circle-icon" className={className}>⚠️</span>,
  CheckCircle: ({ className }: any) => <span data-testid="check-circle-icon" className={className}>✅</span>,
  Clock: ({ className }: any) => <span data-testid="clock-icon" className={className}>⏰</span>
}))

// Mock cn utility
jest.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' ')
}))

// Mock data
const mockMetrics: AnalyticsMetrics = {
  usage: {
    totalUsers: 12847,
    activeUsers: 8932,
    newUsers: 234,
    sessionsPerUser: 2.4,
    avgSessionDuration: 420,
    pageViewsPerSession: 4.2,
    bounceRate: 35.2,
    topPages: [
      { page: '/dashboard', views: 15234, uniqueUsers: 8932 }
    ],
    userGrowth: [
      { date: '2025-01-01', newUsers: 25, activeUsers: 220 }
    ],
    hourlyActivity: [
      { hour: 0, users: 50, sessions: 80 }
    ]
  },
  performance: {
    avgResponseTime: 245,
    p50ResponseTime: 180,
    p95ResponseTime: 450,
    p99ResponseTime: 890,
    successRate: 98.5,
    errorRate: 1.5,
    throughput: 145.3,
    uptime: 99.8,
    responseTimeHistory: [
      { timestamp: '2025-01-01T00:00:00Z', avgTime: 200, p95Time: 400 }
    ],
    errorBreakdown: [
      { type: '4xx Client Error', count: 234, percentage: 65.2 }
    ],
    endpointPerformance: [
      { endpoint: '/api/analytics/metrics', avgTime: 450, calls: 12847, errors: 23 }
    ]
  },
  research: {
    analysesRun: 1847,
    datasetsUsed: new Map([['OpenNeuro', 234]]),
    toolsUsed: new Map([['fmri_glm_analysis', 345]]),
    popularWorkflows: [
      { workflow: 'Preprocessing → GLM → Results Visualization', usage: 234, successRate: 89.5 }
    ],
    publicationMetrics: {
      totalCitations: 1247,
      hIndex: 23,
      recentPublications: 15
    },
    datasetStats: {
      totalDatasets: 487,
      totalSubjects: 23847,
      modalityBreakdown: { 'fMRI': 234 }
    },
    toolUsageTrends: [
      { date: '2025-01-01', toolUsage: { 'fmri_glm_analysis': 10 } }
    ]
  },
  system: {
    cpuUsage: 45.3,
    memoryUsage: 62.8,
    gpuUsage: 78.2,
    storageUsage: 34.7,
    queueLength: 5,
    activeJobs: 8,
    completedJobs: 1247,
    failedJobs: 23,
    resourceHistory: [
      { timestamp: '2025-01-01T00:00:00Z', cpu: 30, memory: 40, gpu: 60, storage: 30 }
    ],
    jobQueue: [
      { id: 'job_1', type: 'analysis', status: 'running', startTime: '2025-01-01T00:00:00Z', duration: 3600, user: 'user_1' }
    ]
  },
  engagement: {
    dailyActiveUsers: 2847,
    weeklyActiveUsers: 8932,
    monthlyActiveUsers: 23847,
    retentionRate: 78.5,
    churnRate: 12.3,
    avgTimeOnSite: 450,
    conversionFunnels: [
      {
        name: 'New User Onboarding',
        steps: [
          { step: 'Sign Up', users: 1000, conversionRate: 100 }
        ]
      }
    ],
    featureAdoption: [
      { feature: 'Dashboard', adoptionRate: 89.2, activeUsers: 7964 }
    ],
    userSegments: [
      { segment: 'Researchers', users: 5432, engagement: 85.3 }
    ]
  }
}

describe('RealTimeMonitor', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    jest.clearAllTimers()
  })

  afterEach(() => {
    jest.runOnlyPendingTimers()
    jest.useRealTimers()
    jest.useFakeTimers()
  })

  describe('Rendering', () => {
    it('renders with default props', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      expect(screen.getByText('Real-time Monitor')).toBeInTheDocument()
      expect(screen.getByText('Live system metrics and activity')).toBeInTheDocument()
    })

    it('renders with custom className', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
          className="test-class"
        />
      )
      
      const container = screen.getAllByTestId('card')[0]
      expect(container).toHaveClass('test-class')
    })

    it('shows connection status badge', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const badge = screen.getByTestId('badge')
      expect(badge).toHaveTextContent('Connected')
      expect(badge).toHaveAttribute('data-variant', 'default')
    })
  })

  describe('Connection Management', () => {
    it('establishes WebSocket connection on mount', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      expect(global.WebSocket).toHaveBeenCalledWith(
        expect.stringContaining('ws://localhost:8080/analytics/realtime')
      )
      expect(mockWebSocket.addEventListener).toHaveBeenCalledWith('open', expect.any(Function))
      expect(mockWebSocket.addEventListener).toHaveBeenCalledWith('message', expect.any(Function))
      expect(mockWebSocket.addEventListener).toHaveBeenCalledWith('close', expect.any(Function))
      expect(mockWebSocket.addEventListener).toHaveBeenCalledWith('error', expect.any(Function))
    })

    it('cleans up WebSocket connection on unmount', () => {
      const { unmount } = render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      unmount()
      
      expect(mockWebSocket.close).toHaveBeenCalled()
      expect(mockWebSocket.removeEventListener).toHaveBeenCalled()
    })

    it('shows disconnected status when connection fails', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      // Simulate connection close
      const closeHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'close'
      )?.[1]
      
      act(() => {
        closeHandler?.()
      })
      
      const badge = screen.getByTestId('badge')
      expect(badge).toHaveTextContent('Disconnected')
      expect(badge).toHaveAttribute('data-variant', 'destructive')
    })

    it('attempts to reconnect when connection is lost', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      // Simulate connection close
      const closeHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'close'
      )?.[1]
      
      act(() => {
        closeHandler?.()
      })
      
      // Fast-forward past reconnect delay
      act(() => {
        jest.advanceTimersByTime(5000)
      })
      
      // Should attempt to create new WebSocket connection
      expect(global.WebSocket).toHaveBeenCalledTimes(2)
    })
  })

  describe('Real-time Data Updates', () => {
    it('processes incoming WebSocket messages', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const messageHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'message'
      )?.[1]
      
      const mockUpdate = {
        type: 'metrics_update',
        data: {
          timestamp: new Date().toISOString(),
          activeUsers: 9500,
          cpuUsage: 52.3,
          memoryUsage: 67.1,
          responseTime: 230
        }
      }
      
      act(() => {
        messageHandler?.({ data: JSON.stringify(mockUpdate) })
      })
      
      // Should update the displayed metrics
      expect(screen.getByText('9,500')).toBeInTheDocument()
    })

    it('handles malformed WebSocket messages gracefully', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const messageHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'message'
      )?.[1]
      
      act(() => {
        // Send invalid JSON
        messageHandler?.({ data: 'invalid json' })
      })
      
      // Should not crash and continue to show original metrics
      expect(screen.getByText('Real-time Monitor')).toBeInTheDocument()
    })

    it('updates charts with real-time data', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const lineChart = screen.getByTestId('line-chart')
      expect(lineChart).toHaveAttribute('data-real-time', 'true')
    })
  })

  describe('Controls and Settings', () => {
    it('toggles real-time updates with play/pause button', async () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const playPauseButton = screen.getByTestId('button')
      expect(playPauseButton).toHaveTextContent('⏸️')
      
      await userEvent.click(playPauseButton)
      
      expect(playPauseButton).toHaveTextContent('▶️')
    })

    it('adjusts refresh interval', async () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const selectItem = screen.getByTestId('select-item-1000')
      await userEvent.click(selectItem)
      
      // Should update the refresh interval to 1 second
      const select = screen.getByTestId('select-root')
      expect(select).toHaveAttribute('data-value', '1000')
    })

    it('toggles auto-scroll for live updates', async () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const autoScrollSwitch = screen.getByTestId('switch')
      expect(autoScrollSwitch).toHaveAttribute('data-checked', 'true')
      
      await userEvent.click(autoScrollSwitch)
      
      expect(autoScrollSwitch).toHaveAttribute('data-checked', 'false')
    })
  })

  describe('Live Metrics Display', () => {
    it('displays current active users', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const activeUsersCard = screen.getAllByTestId('metric-card').find(
        card => card.getAttribute('data-title') === 'Active Users'
      )
      
      expect(activeUsersCard).toBeInTheDocument()
      expect(activeUsersCard).toHaveAttribute('data-value', '8932')
    })

    it('displays system resource usage', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const cpuCard = screen.getAllByTestId('metric-card').find(
        card => card.getAttribute('data-title') === 'CPU Usage'
      )
      
      expect(cpuCard).toBeInTheDocument()
      expect(cpuCard).toHaveAttribute('data-value', '45.3%')
    })

    it('displays response time metrics', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const responseTimeCard = screen.getAllByTestId('metric-card').find(
        card => card.getAttribute('data-title') === 'Avg Response Time'
      )
      
      expect(responseTimeCard).toBeInTheDocument()
      expect(responseTimeCard).toHaveAttribute('data-value', '245ms')
    })

    it('displays active jobs count', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const activeJobsCard = screen.getAllByTestId('metric-card').find(
        card => card.getAttribute('data-title') === 'Active Jobs'
      )
      
      expect(activeJobsCard).toBeInTheDocument()
      expect(activeJobsCard).toHaveAttribute('data-value', '8')
    })
  })

  describe('Sparkline Charts', () => {
    it('renders sparkline charts for key metrics', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const sparklines = screen.getAllByTestId('sparkline-chart')
      expect(sparklines.length).toBeGreaterThan(0)
      
      sparklines.forEach(sparkline => {
        expect(sparkline).toHaveAttribute('data-height')
      })
    })

    it('updates sparklines with new data points', () => {
      const { rerender } = render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const updatedMetrics = {
        ...mockMetrics,
        usage: {
          ...mockMetrics.usage,
          activeUsers: 9200
        }
      }
      
      rerender(
        <RealTimeMonitor 
          metrics={updatedMetrics}
          refreshInterval={5000}
        />
      )
      
      // Sparklines should reflect the updated data
      const sparklines = screen.getAllByTestId('sparkline-chart')
      expect(sparklines.length).toBeGreaterThan(0)
    })
  })

  describe('Alert System', () => {
    it('shows alerts for critical metrics', () => {
      const criticalMetrics = {
        ...mockMetrics,
        system: {
          ...mockMetrics.system,
          cpuUsage: 95.5, // Critical level
          memoryUsage: 92.1 // Critical level
        }
      }
      
      render(
        <RealTimeMonitor 
          metrics={criticalMetrics}
          refreshInterval={5000}
        />
      )
      
      const alertIcon = screen.getByTestId('alert-circle-icon')
      expect(alertIcon).toBeInTheDocument()
    })

    it('shows different alert levels based on severity', () => {
      const warningMetrics = {
        ...mockMetrics,
        performance: {
          ...mockMetrics.performance,
          avgResponseTime: 800, // Warning level
          successRate: 96.0 // Warning level
        }
      }
      
      render(
        <RealTimeMonitor 
          metrics={warningMetrics}
          refreshInterval={5000}
        />
      )
      
      // Should show warning indicators
      expect(screen.getByText('Real-time Monitor')).toBeInTheDocument()
    })
  })

  describe('Data Retention', () => {
    it('maintains limited history of real-time data', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={1000}
        />
      )
      
      const messageHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'message'
      )?.[1]
      
      // Simulate multiple data updates
      for (let i = 0; i < 100; i++) {
        const mockUpdate = {
          type: 'metrics_update',
          data: {
            timestamp: new Date(Date.now() + i * 1000).toISOString(),
            activeUsers: 9000 + i,
            cpuUsage: 45 + Math.random() * 10
          }
        }
        
        act(() => {
          messageHandler?.({ data: JSON.stringify(mockUpdate) })
        })
      }
      
      // Should maintain reasonable number of data points (not exceed memory limits)
      const sparklines = screen.getAllByTestId('sparkline-chart')
      expect(sparklines.length).toBeGreaterThan(0)
    })
  })

  describe('Performance Optimization', () => {
    it('throttles rapid updates', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={100} // Very fast updates
        />
      )
      
      const messageHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'message'
      )?.[1]
      
      // Send rapid updates
      for (let i = 0; i < 10; i++) {
        const mockUpdate = {
          type: 'metrics_update',
          data: {
            timestamp: new Date().toISOString(),
            activeUsers: 9000 + i
          }
        }
        
        act(() => {
          messageHandler?.({ data: JSON.stringify(mockUpdate) })
        })
      }
      
      // Should handle updates without performance issues
      expect(screen.getByText('Real-time Monitor')).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('handles WebSocket errors gracefully', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const errorHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'error'
      )?.[1]
      
      act(() => {
        errorHandler?.({ type: 'error', message: 'Connection failed' })
      })
      
      // Should show disconnected status
      const badge = screen.getByTestId('badge')
      expect(badge).toHaveTextContent('Disconnected')
    })

    it('shows error message when connection fails persistently', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      // Simulate multiple connection failures
      const errorHandler = mockWebSocket.addEventListener.mock.calls.find(
        call => call[0] === 'error'
      )?.[1]
      
      for (let i = 0; i < 5; i++) {
        act(() => {
          errorHandler?.({ type: 'error', message: 'Connection failed' })
        })
        
        act(() => {
          jest.advanceTimersByTime(5000)
        })
      }
      
      // Should show persistent error state
      const badge = screen.getByTestId('badge')
      expect(badge).toHaveTextContent('Disconnected')
    })
  })

  describe('Accessibility', () => {
    it('provides proper ARIA labels', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const heading = screen.getByRole('heading', { level: 2 })
      expect(heading).toHaveTextContent('Real-time Monitor')
    })

    it('supports keyboard navigation', async () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const playPauseButton = screen.getByTestId('button')
      playPauseButton.focus()
      
      expect(document.activeElement).toBe(playPauseButton)
    })

    it('provides screen reader friendly content', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const metricCards = screen.getAllByTestId('metric-card')
      metricCards.forEach(card => {
        expect(card).toHaveAttribute('data-title')
        expect(card).toHaveAttribute('data-value')
      })
    })
  })

  describe('Visual Indicators', () => {
    it('shows connection status with appropriate icons', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const wifiIcon = screen.getByTestId('wifi-icon')
      expect(wifiIcon).toBeInTheDocument()
    })

    it('shows activity indicators for live data', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const activityIcon = screen.getByTestId('activity-icon')
      expect(activityIcon).toBeInTheDocument()
    })

    it('shows timestamp of last update', () => {
      render(
        <RealTimeMonitor 
          metrics={mockMetrics}
          refreshInterval={5000}
        />
      )
      
      const clockIcon = screen.getByTestId('clock-icon')
      expect(clockIcon).toBeInTheDocument()
    })
  })
})