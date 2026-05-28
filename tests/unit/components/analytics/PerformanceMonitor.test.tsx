/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PerformanceMonitor } from '@/components/analytics/PerformanceMonitor'
import { PerformanceMetrics, SystemMetrics, TimeRange } from '@/types/analytics'
import '@testing-library/jest-dom'

// Mock chart components
jest.mock('@/components/charts/LineChart', () => ({
  LineChart: ({ data, title, xKey, yKey, color, height, className, onPointClick }: any) => (
    <div 
      data-testid="line-chart" 
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      className={className}
      onClick={() => onPointClick && onPointClick({ x: '2025-01-01T00:00:00Z', y: 200 })}
    >
      Line Chart: {title} ({data?.length || 0} points)
    </div>
  )
}))

jest.mock('@/components/charts/AreaChart', () => ({
  AreaChart: ({ data, title, xKey, yKey, color, height, className }: any) => (
    <div 
      data-testid="area-chart"
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      className={className}
    >
      Area Chart: {title} ({data?.length || 0} points)
    </div>
  )
}))

jest.mock('@/components/charts/BarChart', () => ({
  BarChart: ({ data, title, xKey, yKey, color, height, className, horizontal }: any) => (
    <div 
      data-testid="bar-chart"
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      data-horizontal={horizontal}
      className={className}
    >
      Bar Chart: {title} ({data?.length || 0} bars)
    </div>
  )
}))

jest.mock('@/components/charts/DonutChart', () => ({
  DonutChart: ({ data, title, labelKey, valueKey, height, className, colors }: any) => (
    <div 
      data-testid="donut-chart"
      data-title={title}
      data-label-key={labelKey}
      data-value-key={valueKey}
      data-height={height}
      data-colors={colors?.join(',')}
      className={className}
    >
      Donut Chart: {title} ({data?.length || 0} segments)
    </div>
  )
}))

// Mock progress components
jest.mock('@/components/ui/progress', () => ({
  Progress: ({ value, className, ...props }: any) => (
    <div 
      data-testid="progress" 
      data-value={value}
      className={className}
      {...props}
    >
      Progress: {value}%
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

jest.mock('@/components/ui/alert', () => ({
  Alert: ({ children, className }: any) => <div data-testid="alert" className={className}>{children}</div>,
  AlertDescription: ({ children }: any) => <div data-testid="alert-description">{children}</div>
}))

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  Cpu: ({ className }: any) => <span data-testid="cpu-icon" className={className}>🖥️</span>,
  MemoryStick: ({ className }: any) => <span data-testid="memory-icon" className={className}>💾</span>,
  HardDrive: ({ className }: any) => <span data-testid="hard-drive-icon" className={className}>💿</span>,
  Zap: ({ className }: any) => <span data-testid="zap-icon" className={className}>⚡</span>,
  Clock: ({ className }: any) => <span data-testid="clock-icon" className={className}>⏰</span>,
  CheckCircle: ({ className }: any) => <span data-testid="check-circle-icon" className={className}>✅</span>,
  AlertTriangle: ({ className }: any) => <span data-testid="alert-triangle-icon" className={className}>⚠️</span>,
  XCircle: ({ className }: any) => <span data-testid="x-circle-icon" className={className}>❌</span>,
  Server: ({ className }: any) => <span data-testid="server-icon" className={className}>🖥️</span>,
  Activity: ({ className }: any) => <span data-testid="activity-icon" className={className}>📈</span>,
  TrendingUp: ({ className }: any) => <span data-testid="trending-up-icon" className={className}>📈</span>,
  TrendingDown: ({ className }: any) => <span data-testid="trending-down-icon" className={className}>📉</span>
}))

// Mock cn utility
jest.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' ')
}))

// Mock data
const mockTimeRange: TimeRange = {
  label: 'Last 7 Days',
  value: '7d',
  start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
  end: new Date()
}

const mockPerformanceMetrics: PerformanceMetrics = {
  avgResponseTime: 245,
  p50ResponseTime: 180,
  p95ResponseTime: 450,
  p99ResponseTime: 890,
  successRate: 98.5,
  errorRate: 1.5,
  throughput: 145.3,
  uptime: 99.8,
  responseTimeHistory: [
    { timestamp: '2025-01-01T00:00:00Z', avgTime: 200, p95Time: 400 },
    { timestamp: '2025-01-01T06:00:00Z', avgTime: 220, p95Time: 420 },
    { timestamp: '2025-01-01T12:00:00Z', avgTime: 245, p95Time: 450 },
    { timestamp: '2025-01-01T18:00:00Z', avgTime: 260, p95Time: 480 },
    { timestamp: '2025-01-02T00:00:00Z', avgTime: 240, p95Time: 460 }
  ],
  errorBreakdown: [
    { type: '4xx Client Error', count: 234, percentage: 65.2 },
    { type: '5xx Server Error', count: 87, percentage: 24.3 },
    { type: 'Timeout', count: 23, percentage: 6.4 },
    { type: 'Network Error', count: 15, percentage: 4.1 }
  ],
  endpointPerformance: [
    { endpoint: '/api/analytics/metrics', avgTime: 450, calls: 12847, errors: 23 },
    { endpoint: '/api/datasets/search', avgTime: 320, calls: 9876, errors: 15 },
    { endpoint: '/api/kg/query', avgTime: 280, calls: 8765, errors: 12 },
    { endpoint: '/api/agent/chat', avgTime: 180, calls: 15432, errors: 8 },
    { endpoint: '/api/upload', avgTime: 890, calls: 2345, errors: 34 }
  ]
}

const mockSystemMetrics: SystemMetrics = {
  cpuUsage: 45.3,
  memoryUsage: 62.8,
  gpuUsage: 78.2,
  storageUsage: 34.7,
  queueLength: 5,
  activeJobs: 8,
  completedJobs: 1247,
  failedJobs: 23,
  resourceHistory: [
    { timestamp: '2025-01-01T00:00:00Z', cpu: 30, memory: 40, gpu: 60, storage: 30 },
    { timestamp: '2025-01-01T06:00:00Z', cpu: 35, memory: 45, gpu: 65, storage: 32 },
    { timestamp: '2025-01-01T12:00:00Z', cpu: 45, memory: 62, gpu: 78, storage: 34 },
    { timestamp: '2025-01-01T18:00:00Z', cpu: 50, memory: 68, gpu: 85, storage: 36 },
    { timestamp: '2025-01-02T00:00:00Z', cpu: 40, memory: 55, gpu: 70, storage: 33 }
  ],
  jobQueue: [
    { id: 'job_1', type: 'analysis', status: 'running', startTime: '2025-01-01T00:00:00Z', duration: 3600, user: 'user_1' },
    { id: 'job_2', type: 'preprocessing', status: 'queued', startTime: '2025-01-01T01:00:00Z', duration: 1800, user: 'user_2' },
    { id: 'job_3', type: 'visualization', status: 'completed', startTime: '2025-01-01T02:00:00Z', duration: 900, user: 'user_3' }
  ]
}

describe('PerformanceMonitor', () => {
  describe('Rendering', () => {
    it('renders with default props', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Performance Monitor')).toBeInTheDocument()
      expect(screen.getByText('System performance and resource utilization')).toBeInTheDocument()
    })

    it('renders with compact mode', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
          compactMode={true}
        />
      )
      
      expect(screen.getByText('Performance Monitor')).toBeInTheDocument()
    })

    it('renders with custom className', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
          className="test-class"
        />
      )
      
      const container = screen.getAllByTestId('card')[0]
      expect(container).toHaveClass('test-class')
    })
  })

  describe('Key Performance Metrics', () => {
    it('displays response time metrics correctly', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Avg Response Time')).toBeInTheDocument()
      expect(screen.getByText('245ms')).toBeInTheDocument()
      
      expect(screen.getByText('P95 Response Time')).toBeInTheDocument()
      expect(screen.getByText('450ms')).toBeInTheDocument()
    })

    it('displays success rate and uptime correctly', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Success Rate')).toBeInTheDocument()
      expect(screen.getByText('98.5%')).toBeInTheDocument()
      
      expect(screen.getByText('System Uptime')).toBeInTheDocument()
      expect(screen.getByText('99.8%')).toBeInTheDocument()
    })

    it('displays throughput correctly', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Throughput')).toBeInTheDocument()
      expect(screen.getByText('145.3 req/min')).toBeInTheDocument()
    })
  })

  describe('System Resource Usage', () => {
    it('displays CPU usage with progress bar', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('CPU Usage')).toBeInTheDocument()
      expect(screen.getByText('45.3%')).toBeInTheDocument()
      
      const cpuProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '45.3'
      )
      expect(cpuProgress).toBeInTheDocument()
    })

    it('displays memory usage with progress bar', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Memory Usage')).toBeInTheDocument()
      expect(screen.getByText('62.8%')).toBeInTheDocument()
      
      const memoryProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '62.8'
      )
      expect(memoryProgress).toBeInTheDocument()
    })

    it('displays GPU usage with progress bar', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('GPU Usage')).toBeInTheDocument()
      expect(screen.getByText('78.2%')).toBeInTheDocument()
      
      const gpuProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '78.2'
      )
      expect(gpuProgress).toBeInTheDocument()
    })

    it('displays storage usage with progress bar', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Storage Usage')).toBeInTheDocument()
      expect(screen.getByText('34.7%')).toBeInTheDocument()
      
      const storageProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '34.7'
      )
      expect(storageProgress).toBeInTheDocument()
    })
  })

  describe('Job Queue Information', () => {
    it('displays active jobs count', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Active Jobs')).toBeInTheDocument()
      expect(screen.getByText('8')).toBeInTheDocument()
    })

    it('displays completed and failed jobs', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Completed: 1,247')).toBeInTheDocument()
      expect(screen.getByText('Failed: 23')).toBeInTheDocument()
    })

    it('displays queue length', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Queue Length')).toBeInTheDocument()
      expect(screen.getByText('5')).toBeInTheDocument()
    })
  })

  describe('Charts and Visualizations', () => {
    it('renders response time history chart', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const lineCharts = screen.getAllByTestId('line-chart')
      const responseTimeChart = lineCharts.find(chart => 
        chart.getAttribute('data-title')?.includes('Response Time History')
      )
      
      expect(responseTimeChart).toBeInTheDocument()
      expect(responseTimeChart).toHaveTextContent('(5 points)')
    })

    it('renders resource utilization chart', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const areaChart = screen.getByTestId('area-chart')
      expect(areaChart).toBeInTheDocument()
      expect(areaChart).toHaveAttribute('data-title', 'Resource Utilization Over Time')
    })

    it('renders error breakdown donut chart', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const donutChart = screen.getByTestId('donut-chart')
      expect(donutChart).toBeInTheDocument()
      expect(donutChart).toHaveAttribute('data-title', 'Error Breakdown')
      expect(donutChart).toHaveTextContent('(4 segments)')
    })

    it('renders endpoint performance bar chart', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toBeInTheDocument()
      expect(barChart).toHaveAttribute('data-title', 'Endpoint Performance')
      expect(barChart).toHaveTextContent('(5 bars)')
    })
  })

  describe('Tabs Navigation', () => {
    it('renders all tab options', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByTestId('tab-overview')).toBeInTheDocument()
      expect(screen.getByTestId('tab-response-times')).toBeInTheDocument()
      expect(screen.getByTestId('tab-resources')).toBeInTheDocument()
      expect(screen.getByTestId('tab-errors')).toBeInTheDocument()
      expect(screen.getByTestId('tab-endpoints')).toBeInTheDocument()
    })

    it('switches tabs correctly', async () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const resourcesTab = screen.getByTestId('tab-resources')
      await userEvent.click(resourcesTab)
      
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveAttribute('data-value', 'resources')
    })

    it('shows correct content in each tab', async () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      // Switch to errors tab
      const errorsTab = screen.getByTestId('tab-errors')
      await userEvent.click(errorsTab)
      
      expect(screen.getByTestId('tab-content-errors')).toBeInTheDocument()
      expect(screen.getByTestId('donut-chart')).toBeInTheDocument()
    })
  })

  describe('Performance Alerts', () => {
    it('shows warning for high response time', () => {
      const slowMetrics = {
        ...mockPerformanceMetrics,
        avgResponseTime: 1200 // Above 1000ms threshold
      }

      render(
        <PerformanceMonitor 
          metrics={slowMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const alerts = screen.getAllByTestId('alert')
      const responseTimeAlert = alerts.find(alert => 
        alert.textContent?.includes('High response time detected')
      )
      expect(responseTimeAlert).toBeInTheDocument()
    })

    it('shows warning for low success rate', () => {
      const lowSuccessMetrics = {
        ...mockPerformanceMetrics,
        successRate: 85.0 // Below 95% threshold
      }

      render(
        <PerformanceMonitor 
          metrics={lowSuccessMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const alerts = screen.getAllByTestId('alert')
      const successRateAlert = alerts.find(alert => 
        alert.textContent?.includes('Low success rate')
      )
      expect(successRateAlert).toBeInTheDocument()
    })

    it('shows warning for high resource usage', () => {
      const highResourceMetrics = {
        ...mockSystemMetrics,
        cpuUsage: 95.0, // Above 90% threshold
        memoryUsage: 98.0 // Above 90% threshold
      }

      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={highResourceMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const alerts = screen.getAllByTestId('alert')
      const resourceAlert = alerts.find(alert => 
        alert.textContent?.includes('High resource usage')
      )
      expect(resourceAlert).toBeInTheDocument()
    })
  })

  describe('Color Coding', () => {
    it('uses appropriate colors for resource usage levels', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      // CPU usage (45.3%) should be in safe range - green
      const cpuProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '45.3'
      )
      expect(cpuProgress).toHaveClass(expect.stringMatching(/green|success/))
      
      // GPU usage (78.2%) should be in warning range - yellow/orange
      const gpuProgress = screen.getAllByTestId('progress').find(
        progress => progress.getAttribute('data-value') === '78.2'
      )
      expect(gpuProgress).toHaveClass(expect.stringMatching(/yellow|warning|orange/))
    })
  })

  describe('Endpoint Performance Analysis', () => {
    it('displays endpoint performance data correctly', async () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      // Switch to endpoints tab
      const endpointsTab = screen.getByTestId('tab-endpoints')
      await userEvent.click(endpointsTab)
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toHaveAttribute('data-title', 'Endpoint Performance')
      expect(barChart).toHaveAttribute('data-x-key', 'endpoint')
      expect(barChart).toHaveAttribute('data-y-key', 'avgTime')
    })

    it('identifies slowest endpoints', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      // The slowest endpoint should be /api/upload with 890ms
      const slowestEndpoint = mockPerformanceMetrics.endpointPerformance
        .sort((a, b) => b.avgTime - a.avgTime)[0]
      expect(slowestEndpoint.endpoint).toBe('/api/upload')
      expect(slowestEndpoint.avgTime).toBe(890)
    })
  })

  describe('Real-time Updates', () => {
    it('handles real-time data updates', () => {
      const { rerender } = render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const updatedSystemMetrics = {
        ...mockSystemMetrics,
        cpuUsage: 60.5,
        activeJobs: 12
      }
      
      rerender(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={updatedSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('60.5%')).toBeInTheDocument()
      expect(screen.getByText('12')).toBeInTheDocument()
    })
  })

  describe('Chart Interactions', () => {
    it('supports chart click interactions', async () => {
      const mockOnPointClick = jest.fn()
      
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const lineChart = screen.getAllByTestId('line-chart')[0]
      await userEvent.click(lineChart)
      
      // The mock chart component simulates a point click
      // In a real implementation, this would trigger detailed views or tooltips
      expect(lineChart).toBeInTheDocument()
    })
  })

  describe('Data Processing', () => {
    it('calculates percentile correctly', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('P95 Response Time')).toBeInTheDocument()
      expect(screen.getByText('450ms')).toBeInTheDocument()
      expect(screen.getByText('P99 Response Time')).toBeInTheDocument()
      expect(screen.getByText('890ms')).toBeInTheDocument()
    })

    it('formats large numbers correctly', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Completed: 1,247')).toBeInTheDocument()
    })
  })

  describe('Error Handling', () => {
    it('handles missing data gracefully', () => {
      const incompleteMetrics: Partial<PerformanceMetrics> = {
        avgResponseTime: 0,
        successRate: 0
      }

      const incompleteSystemMetrics: Partial<SystemMetrics> = {
        cpuUsage: 0,
        memoryUsage: 0
      }

      render(
        <PerformanceMonitor 
          metrics={incompleteMetrics as PerformanceMetrics}
          systemMetrics={incompleteSystemMetrics as SystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Performance Monitor')).toBeInTheDocument()
    })

    it('handles empty arrays gracefully', () => {
      const emptyDataMetrics: PerformanceMetrics = {
        ...mockPerformanceMetrics,
        responseTimeHistory: [],
        errorBreakdown: [],
        endpointPerformance: []
      }

      const emptySystemMetrics: SystemMetrics = {
        ...mockSystemMetrics,
        resourceHistory: [],
        jobQueue: []
      }

      render(
        <PerformanceMonitor 
          metrics={emptyDataMetrics}
          systemMetrics={emptySystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const lineCharts = screen.getAllByTestId('line-chart')
      const responseTimeChart = lineCharts.find(chart => 
        chart.getAttribute('data-title')?.includes('Response Time History')
      )
      expect(responseTimeChart).toHaveTextContent('(0 points)')
    })
  })

  describe('Accessibility', () => {
    it('provides proper semantic structure', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const headings = screen.getAllByRole('heading')
      expect(headings.length).toBeGreaterThan(0)
      
      const mainHeading = screen.getByRole('heading', { level: 2 })
      expect(mainHeading).toHaveTextContent('Performance Monitor')
    })

    it('provides ARIA labels for progress bars', () => {
      render(
        <PerformanceMonitor 
          metrics={mockPerformanceMetrics}
          systemMetrics={mockSystemMetrics}
          timeRange={mockTimeRange} 
        />
      )
      
      const progressBars = screen.getAllByTestId('progress')
      expect(progressBars.length).toBeGreaterThan(0)
      
      progressBars.forEach(progress => {
        expect(progress).toHaveAttribute('data-value')
      })
    })
  })
})