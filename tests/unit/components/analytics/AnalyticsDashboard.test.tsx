/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AnalyticsDashboard } from '@/components/analytics/AnalyticsDashboard'
import { useAnalyticsData } from '@/hooks/useAnalyticsData'
import { AnalyticsMetrics, TimeRange } from '@/types/analytics'
import '@testing-library/jest-dom'

// Mock the analytics data hook
jest.mock('@/hooks/useAnalyticsData')

// Mock child components
jest.mock('@/components/analytics/MetricsOverview', () => ({
  MetricsOverview: ({ metrics, timeRange, compactMode, className }: any) => (
    <div data-testid="metrics-overview" data-time-range={timeRange.value} data-compact={compactMode} className={className}>
      Metrics Overview - Active Users: {metrics.usage.activeUsers}
    </div>
  )
}))

jest.mock('@/components/analytics/UsageAnalytics', () => ({
  UsageAnalytics: ({ metrics, timeRange, compactMode, className }: any) => (
    <div data-testid="usage-analytics" data-time-range={timeRange.value} data-compact={compactMode} className={className}>
      Usage Analytics - Total Users: {metrics.totalUsers}
    </div>
  )
}))

jest.mock('@/components/analytics/PerformanceMonitor', () => ({
  PerformanceMonitor: ({ metrics, systemMetrics, timeRange, compactMode, className }: any) => (
    <div data-testid="performance-monitor" data-time-range={timeRange.value} data-compact={compactMode} className={className}>
      Performance Monitor - Avg Response: {metrics.avgResponseTime}ms, CPU: {systemMetrics.cpuUsage}%
    </div>
  )
}))

jest.mock('@/components/analytics/RealTimeMonitor', () => ({
  RealTimeMonitor: ({ metrics, refreshInterval, className }: any) => (
    <div data-testid="realtime-monitor" data-refresh-interval={refreshInterval} className={className}>
      Real-time Monitor - Active Jobs: {metrics.system.activeJobs}
    </div>
  )
}))

jest.mock('@/components/analytics/TimeRangeSelector', () => ({
  TimeRangeSelector: ({ selectedRange, onRangeChange, ranges }: any) => (
    <div data-testid="time-range-selector">
      <select 
        data-testid="time-range-select"
        value={selectedRange.value} 
        onChange={(e) => {
          const range = ranges.find((r: TimeRange) => r.value === e.target.value)
          onRangeChange(range)
        }}
      >
        {ranges.map((range: TimeRange) => (
          <option key={range.value} value={range.value}>{range.label}</option>
        ))}
      </select>
    </div>
  )
}))

jest.mock('@/components/analytics/ExportMenu', () => ({
  ExportMenu: ({ onExport }: any) => (
    <div data-testid="export-menu">
      <button data-testid="export-csv" onClick={() => onExport('csv')}>Export CSV</button>
      <button data-testid="export-json" onClick={() => onExport('json')}>Export JSON</button>
      <button data-testid="export-pdf" onClick={() => onExport('pdf')}>Export PDF</button>
    </div>
  )
}))

jest.mock('@/components/analytics/DashboardCustomizer', () => ({
  DashboardCustomizer: ({ open, onClose, currentConfig, onConfigChange }: any) => (
    open ? (
      <div data-testid="dashboard-customizer">
        <button data-testid="close-customizer" onClick={onClose}>Close</button>
        <button 
          data-testid="toggle-realtime" 
          onClick={() => onConfigChange({ ...currentConfig, realTimeEnabled: !currentConfig.realTimeEnabled })}
        >
          Toggle Real-time
        </button>
      </div>
    ) : null
  )
}))

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({ children, className }: any) => <div data-testid="card" className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div data-testid="card-content" className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div data-testid="card-header" className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <h3 data-testid="card-title" className={className}>{children}</h3>
}))

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, disabled, variant, size, className, ...props }: any) => (
    <button 
      data-testid={props['data-testid'] || 'button'}
      onClick={onClick} 
      disabled={disabled}
      className={className}
      data-variant={variant}
      data-size={size}
    >
      {children}
    </button>
  )
}))

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children, variant, className }: any) => (
    <span data-testid="badge" data-variant={variant} className={className}>{children}</span>
  )
}))

jest.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children, value, onValueChange }: any) => (
    <div data-testid="tabs" data-value={value} onClick={(e: any) => {
      if (e.target.dataset.tabValue) onValueChange(e.target.dataset.tabValue)
    }}>
      {children}
    </div>
  ),
  TabsList: ({ children, className }: any) => <div data-testid="tabs-list" className={className}>{children}</div>,
  TabsTrigger: ({ children, value, className }: any) => (
    <button data-testid={`tab-${value}`} data-tab-value={value} className={className}>{children}</button>
  ),
  TabsContent: ({ children, value, className }: any) => (
    <div data-testid={`tab-content-${value}`} className={className}>{children}</div>
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
  RefreshCw: ({ className, ...props }: any) => <span data-testid="refresh-icon" className={className} {...props}>↻</span>,
  Settings: ({ className, ...props }: any) => <span data-testid="settings-icon" className={className} {...props}>⚙</span>,
  Download: ({ className, ...props }: any) => <span data-testid="download-icon" className={className} {...props}>↓</span>,
  Filter: ({ className, ...props }: any) => <span data-testid="filter-icon" className={className} {...props}>⧩</span>,
  Calendar: ({ className, ...props }: any) => <span data-testid="calendar-icon" className={className} {...props}>📅</span>
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

const mockUseAnalyticsData = useAnalyticsData as jest.MockedFunction<typeof useAnalyticsData>

describe('AnalyticsDashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockUseAnalyticsData.mockReturnValue({
      metrics: mockMetrics,
      loading: false,
      error: null,
      lastUpdated: new Date('2025-01-01T12:00:00Z'),
      refreshData: jest.fn(),
      setRealTime: jest.fn()
    })
  })

  describe('Rendering', () => {
    it('renders the dashboard with default props', () => {
      render(<AnalyticsDashboard />)
      
      expect(screen.getByText('Analytics Dashboard')).toBeInTheDocument()
      expect(screen.getByText('Monitor system performance, user behavior, and research metrics')).toBeInTheDocument()
    })

    it('renders with custom props', () => {
      render(
        <AnalyticsDashboard 
          className="custom-class" 
          defaultTimeRange="30d"
          showRealTime={false}
          compactMode={true}
        />
      )
      
      expect(screen.getByText('Analytics Dashboard')).toBeInTheDocument()
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveClass('custom-class')
    })

    it('renders last updated time when available', () => {
      render(<AnalyticsDashboard />)
      
      const badge = screen.getByTestId('badge')
      expect(badge).toHaveTextContent('Updated 12:00:00 PM')
    })
  })

  describe('Loading States', () => {
    it('shows loading state when loading and no metrics', () => {
      mockUseAnalyticsData.mockReturnValue({
        metrics: null,
        loading: true,
        error: null,
        lastUpdated: null,
        refreshData: jest.fn(),
        setRealTime: jest.fn()
      })

      render(<AnalyticsDashboard />)
      
      expect(screen.getByText('Loading Analytics Data')).toBeInTheDocument()
      expect(screen.getByText('Please wait while we fetch the latest metrics...')).toBeInTheDocument()
      expect(screen.getByTestId('refresh-icon')).toHaveClass('animate-spin')
    })

    it('shows content when not loading and has metrics', () => {
      render(<AnalyticsDashboard />)
      
      expect(screen.queryByText('Loading Analytics Data')).not.toBeInTheDocument()
      expect(screen.getByTestId('metrics-overview')).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('shows error state when error exists', () => {
      mockUseAnalyticsData.mockReturnValue({
        metrics: null,
        loading: false,
        error: 'Network error',
        lastUpdated: null,
        refreshData: jest.fn(),
        setRealTime: jest.fn()
      })

      render(<AnalyticsDashboard />)
      
      expect(screen.getByText('Failed to Load Analytics Data')).toBeInTheDocument()
      expect(screen.getByText('Network error')).toBeInTheDocument()
      expect(screen.getByText('Try Again')).toBeInTheDocument()
    })

    it('calls refreshData when Try Again is clicked', async () => {
      const mockRefreshData = jest.fn()
      mockUseAnalyticsData.mockReturnValue({
        metrics: null,
        loading: false,
        error: 'Network error',
        lastUpdated: null,
        refreshData: mockRefreshData,
        setRealTime: jest.fn()
      })

      render(<AnalyticsDashboard />)
      
      const tryAgainButton = screen.getByText('Try Again')
      await userEvent.click(tryAgainButton)
      
      expect(mockRefreshData).toHaveBeenCalledTimes(1)
    })
  })

  describe('Interactions', () => {
    it('calls refreshData when refresh button is clicked', async () => {
      const mockRefreshData = jest.fn()
      mockUseAnalyticsData.mockReturnValue({
        metrics: mockMetrics,
        loading: false,
        error: null,
        lastUpdated: new Date(),
        refreshData: mockRefreshData,
        setRealTime: jest.fn()
      })

      render(<AnalyticsDashboard />)
      
      const refreshButton = screen.getByText('Refresh')
      await userEvent.click(refreshButton)
      
      expect(mockRefreshData).toHaveBeenCalledTimes(1)
    })

    it('disables refresh button when loading', () => {
      mockUseAnalyticsData.mockReturnValue({
        metrics: mockMetrics,
        loading: true,
        error: null,
        lastUpdated: new Date(),
        refreshData: jest.fn(),
        setRealTime: jest.fn()
      })

      render(<AnalyticsDashboard />)
      
      const refreshButton = screen.getByText('Refresh')
      expect(refreshButton).toBeDisabled()
    })

    it('handles time range changes', async () => {
      render(<AnalyticsDashboard />)
      
      const timeRangeSelect = screen.getByTestId('time-range-select')
      await userEvent.selectOptions(timeRangeSelect, '30d')
      
      // Check that the metrics overview receives the updated time range
      await waitFor(() => {
        const metricsOverview = screen.getByTestId('metrics-overview')
        expect(metricsOverview).toHaveAttribute('data-time-range', '30d')
      })
    })

    it('handles tab changes', async () => {
      render(<AnalyticsDashboard />)
      
      const usageTab = screen.getByTestId('tab-usage')
      await userEvent.click(usageTab)
      
      await waitFor(() => {
        const tabs = screen.getByTestId('tabs')
        expect(tabs).toHaveAttribute('data-value', 'usage')
      })
    })
  })

  describe('Export Functionality', () => {
    it('handles CSV export', async () => {
      const consoleSpy = jest.spyOn(console, 'log').mockImplementation()
      render(<AnalyticsDashboard />)
      
      const exportCsv = screen.getByTestId('export-csv')
      await userEvent.click(exportCsv)
      
      expect(consoleSpy).toHaveBeenCalledWith('Exporting all analytics data as csv')
      consoleSpy.mockRestore()
    })

    it('handles JSON export', async () => {
      const consoleSpy = jest.spyOn(console, 'log').mockImplementation()
      render(<AnalyticsDashboard />)
      
      const exportJson = screen.getByTestId('export-json')
      await userEvent.click(exportJson)
      
      expect(consoleSpy).toHaveBeenCalledWith('Exporting all analytics data as json')
      consoleSpy.mockRestore()
    })

    it('handles PDF export', async () => {
      const consoleSpy = jest.spyOn(console, 'log').mockImplementation()
      render(<AnalyticsDashboard />)
      
      const exportPdf = screen.getByTestId('export-pdf')
      await userEvent.click(exportPdf)
      
      expect(consoleSpy).toHaveBeenCalledWith('Exporting all analytics data as pdf')
      consoleSpy.mockRestore()
    })
  })

  describe('Dashboard Customization', () => {
    it('opens customizer when customize button is clicked', async () => {
      render(<AnalyticsDashboard />)
      
      const customizeButton = screen.getByText('Customize')
      await userEvent.click(customizeButton)
      
      expect(screen.getByTestId('dashboard-customizer')).toBeInTheDocument()
    })

    it('closes customizer when close button is clicked', async () => {
      render(<AnalyticsDashboard />)
      
      // Open customizer
      const customizeButton = screen.getByText('Customize')
      await userEvent.click(customizeButton)
      
      // Close customizer
      const closeButton = screen.getByTestId('close-customizer')
      await userEvent.click(closeButton)
      
      expect(screen.queryByTestId('dashboard-customizer')).not.toBeInTheDocument()
    })

    it('handles configuration changes', async () => {
      render(<AnalyticsDashboard />)
      
      // Open customizer
      const customizeButton = screen.getByText('Customize')
      await userEvent.click(customizeButton)
      
      // Toggle real-time
      const toggleButton = screen.getByTestId('toggle-realtime')
      await userEvent.click(toggleButton)
      
      // The component should handle the config change
      expect(screen.getByTestId('dashboard-customizer')).toBeInTheDocument()
    })
  })

  describe('Real-time Features', () => {
    it('shows real-time tab when real-time is enabled', () => {
      render(<AnalyticsDashboard showRealTime={true} />)
      
      expect(screen.getByTestId('tab-realtime')).toBeInTheDocument()
    })

    it('hides real-time tab when real-time is disabled', () => {
      render(<AnalyticsDashboard showRealTime={false} />)
      
      expect(screen.queryByTestId('tab-realtime')).not.toBeInTheDocument()
    })

    it('displays live badge when real-time is enabled', () => {
      render(<AnalyticsDashboard showRealTime={true} />)
      
      const liveBadge = screen.getByText('Live')
      expect(liveBadge).toBeInTheDocument()
    })
  })

  describe('Filtering', () => {
    it('handles user segment filter changes', async () => {
      render(<AnalyticsDashboard />)
      
      const userSegmentItem = screen.getByTestId('select-item-researchers')
      await userEvent.click(userSegmentItem)
      
      // The filter should be applied through the useAnalyticsData hook
      expect(mockUseAnalyticsData).toHaveBeenCalledWith(
        expect.objectContaining({
          userSegment: 'researchers'
        }),
        expect.any(Object)
      )
    })

    it('handles data source filter changes', async () => {
      render(<AnalyticsDashboard />)
      
      const dataSourceItem = screen.getByTestId('select-item-api')
      await userEvent.click(dataSourceItem)
      
      expect(mockUseAnalyticsData).toHaveBeenCalledWith(
        expect.objectContaining({
          dataSource: 'api'
        }),
        expect.any(Object)
      )
    })
  })

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(<AnalyticsDashboard />)
      
      const heading = screen.getByRole('heading', { level: 1 })
      expect(heading).toHaveTextContent('Analytics Dashboard')
    })

    it('supports keyboard navigation', async () => {
      render(<AnalyticsDashboard />)
      
      const refreshButton = screen.getByText('Refresh')
      refreshButton.focus()
      
      expect(document.activeElement).toBe(refreshButton)
    })
  })

  describe('Responsive Behavior', () => {
    it('applies compact mode when enabled', () => {
      render(<AnalyticsDashboard compactMode={true} />)
      
      const metricsOverview = screen.getByTestId('metrics-overview')
      expect(metricsOverview).toHaveAttribute('data-compact', 'true')
    })

    it('applies custom className', () => {
      render(<AnalyticsDashboard className="test-class" />)
      
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveClass('test-class')
    })
  })
})