/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MetricsOverview } from '@/components/analytics/MetricsOverview'
import { AnalyticsMetrics, TimeRange } from '@/types/analytics'
import '@testing-library/jest-dom'

// Mock child components
jest.mock('@/components/analytics/KPICard', () => ({
  KPICard: ({ title, value, format, subtitle, color, trend, target, className }: any) => (
    <div 
      data-testid={`kpi-card-${title.toLowerCase().replace(/\s+/g, '-')}`}
      className={className}
      data-color={color}
    >
      <div data-testid="kpi-title">{title}</div>
      <div data-testid="kpi-value">{format === 'percentage' ? `${value}%` : value}</div>
      <div data-testid="kpi-subtitle">{subtitle}</div>
      {trend && (
        <div data-testid="kpi-trend">
          <span data-testid="trend-direction">{trend.trend}</span>
          <span data-testid="trend-change">{trend.changePercentage}%</span>
        </div>
      )}
      {target && <div data-testid="kpi-target">Target: {target}</div>}
    </div>
  )
}))

jest.mock('@/components/charts/LineChart', () => ({
  LineChart: ({ data, title, xKey, yKey, color, height, className }: any) => (
    <div 
      data-testid="line-chart" 
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      className={className}
    >
      Line Chart: {data?.length || 0} data points
    </div>
  )
}))

jest.mock('@/components/charts/BarChart', () => ({
  BarChart: ({ data, title, xKey, yKey, color, height, className }: any) => (
    <div 
      data-testid="bar-chart"
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-color={color}
      data-height={height}
      className={className}
    >
      Bar Chart: {data?.length || 0} data points
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

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  Users: ({ className }: any) => <span data-testid="users-icon" className={className}>👥</span>,
  Activity: ({ className }: any) => <span data-testid="activity-icon" className={className}>📈</span>,
  Zap: ({ className }: any) => <span data-testid="zap-icon" className={className}>⚡</span>,
  Database: ({ className }: any) => <span data-testid="database-icon" className={className}>🗄️</span>,
  TrendingUp: ({ className }: any) => <span data-testid="trending-up-icon" className={className}>📈</span>,
  Clock: ({ className }: any) => <span data-testid="clock-icon" className={className}>⏰</span>,
  CheckCircle: ({ className }: any) => <span data-testid="check-circle-icon" className={className}>✅</span>,
  AlertCircle: ({ className }: any) => <span data-testid="alert-circle-icon" className={className}>⚠️</span>,
  Server: ({ className }: any) => <span data-testid="server-icon" className={className}>🖥️</span>,
  Brain: ({ className }: any) => <span data-testid="brain-icon" className={className}>🧠</span>
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
      { page: '/dashboard', views: 15234, uniqueUsers: 8932 },
      { page: '/datasets', views: 12847, uniqueUsers: 7654 },
      { page: '/analysis', views: 9876, uniqueUsers: 6543 }
    ],
    userGrowth: [
      { date: '2025-01-01', newUsers: 25, activeUsers: 220 },
      { date: '2025-01-02', newUsers: 30, activeUsers: 235 }
    ],
    hourlyActivity: [
      { hour: 0, users: 50, sessions: 80 },
      { hour: 1, users: 45, sessions: 70 }
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
      { timestamp: '2025-01-01T00:00:00Z', avgTime: 200, p95Time: 400 },
      { timestamp: '2025-01-01T06:00:00Z', avgTime: 220, p95Time: 420 }
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
    datasetsUsed: new Map([
      ['OpenNeuro', 234],
      ['HCP', 187],
      ['ADNI', 145]
    ]),
    toolsUsed: new Map([
      ['fmri_glm_analysis', 345],
      ['spatial_roi_search', 287]
    ]),
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
      modalityBreakdown: { 'fMRI': 234, 'T1w': 187, 'DTI': 98 }
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

describe('MetricsOverview', () => {
  describe('Rendering', () => {
    it('renders with default props', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Check for KPI cards
      expect(screen.getByTestId('kpi-card-active-users')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-card-avg-response-time')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-card-success-rate')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-card-system-uptime')).toBeInTheDocument()
    })

    it('renders with compact mode', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
          compactMode={true}
        />
      )
      
      // In compact mode, should still render KPI cards but potentially with different styling
      expect(screen.getByTestId('kpi-card-active-users')).toBeInTheDocument()
    })

    it('renders with custom className', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
          className="test-class"
        />
      )
      
      const container = screen.getByTestId('card')
      expect(container).toHaveClass('test-class')
    })
  })

  describe('KPI Cards Content', () => {
    it('displays active users KPI correctly', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      expect(activeUsersCard).toBeInTheDocument()
      
      const title = activeUsersCard.querySelector('[data-testid="kpi-title"]')
      const value = activeUsersCard.querySelector('[data-testid="kpi-value"]')
      const subtitle = activeUsersCard.querySelector('[data-testid="kpi-subtitle"]')
      
      expect(title).toHaveTextContent('Active Users')
      expect(value).toHaveTextContent('8932')
      expect(subtitle).toHaveTextContent('234 new users')
    })

    it('displays response time KPI with correct color coding', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const responseTimeCard = screen.getByTestId('kpi-card-avg-response-time')
      expect(responseTimeCard).toBeInTheDocument()
      
      const title = responseTimeCard.querySelector('[data-testid="kpi-title"]')
      const value = responseTimeCard.querySelector('[data-testid="kpi-value"]')
      
      expect(title).toHaveTextContent('Avg Response Time')
      expect(value).toHaveTextContent('245')
      
      // Should be green since response time < 500ms
      expect(responseTimeCard).toHaveAttribute('data-color', '#22c55e')
    })

    it('displays success rate KPI with percentage format', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const successRateCard = screen.getByTestId('kpi-card-success-rate')
      const value = successRateCard.querySelector('[data-testid="kpi-value"]')
      
      expect(value).toHaveTextContent('98.5%')
    })

    it('displays system uptime KPI with correct color coding', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const uptimeCard = screen.getByTestId('kpi-card-system-uptime')
      expect(uptimeCard).toHaveAttribute('data-color', '#22c55e') // Should be green since uptime >= 99.9%
    })
  })

  describe('Trend Information', () => {
    it('displays trend information for KPI cards', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const trend = activeUsersCard.querySelector('[data-testid="kpi-trend"]')
      const trendDirection = trend?.querySelector('[data-testid="trend-direction"]')
      const trendChange = trend?.querySelector('[data-testid="trend-change"]')
      
      expect(trendDirection).toHaveTextContent('up')
      expect(trendChange).toHaveTextContent('11.1%')
    })

    it('displays target information when available', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const target = activeUsersCard.querySelector('[data-testid="kpi-target"]')
      
      expect(target).toHaveTextContent('Target: 10718') // 8932 * 1.2
    })
  })

  describe('Charts', () => {
    it('renders user growth line chart', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const lineChart = screen.getByTestId('line-chart')
      expect(lineChart).toBeInTheDocument()
      expect(lineChart).toHaveTextContent('Line Chart: 2 data points')
    })

    it('renders top pages bar chart', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toBeInTheDocument()
      expect(barChart).toHaveTextContent('Bar Chart: 3 data points')
    })
  })

  describe('Error Handling', () => {
    it('handles missing metrics gracefully', () => {
      const incompleteMetrics = {
        ...mockMetrics,
        usage: {
          ...mockMetrics.usage,
          activeUsers: 0,
          newUsers: 0
        }
      }

      render(
        <MetricsOverview 
          metrics={incompleteMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const value = activeUsersCard.querySelector('[data-testid="kpi-value"]')
      
      expect(value).toHaveTextContent('0')
    })

    it('handles missing performance data', () => {
      const incompleteMetrics = {
        ...mockMetrics,
        performance: {
          ...mockMetrics.performance,
          avgResponseTime: 0,
          successRate: 0,
          uptime: 0
        }
      }

      render(
        <MetricsOverview 
          metrics={incompleteMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByTestId('kpi-card-avg-response-time')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-card-success-rate')).toBeInTheDocument()
      expect(screen.getByTestId('kpi-card-system-uptime')).toBeInTheDocument()
    })
  })

  describe('Color Coding Logic', () => {
    it('uses warning color for slow response times', () => {
      const slowMetrics = {
        ...mockMetrics,
        performance: {
          ...mockMetrics.performance,
          avgResponseTime: 600 // Above 500ms threshold
        }
      }

      render(
        <MetricsOverview 
          metrics={slowMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const responseTimeCard = screen.getByTestId('kpi-card-avg-response-time')
      expect(responseTimeCard).toHaveAttribute('data-color', '#f59e0b') // Warning color
    })

    it('uses error color for low uptime', () => {
      const lowUptimeMetrics = {
        ...mockMetrics,
        performance: {
          ...mockMetrics.performance,
          uptime: 95.0 // Below 99.9% threshold
        }
      }

      render(
        <MetricsOverview 
          metrics={lowUptimeMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const uptimeCard = screen.getByTestId('kpi-card-system-uptime')
      expect(uptimeCard).toHaveAttribute('data-color', '#ef4444') // Error color
    })

    it('uses warning color for low success rate', () => {
      const lowSuccessMetrics = {
        ...mockMetrics,
        performance: {
          ...mockMetrics.performance,
          successRate: 95.0 // Below 99% threshold
        }
      }

      render(
        <MetricsOverview 
          metrics={lowSuccessMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const successRateCard = screen.getByTestId('kpi-card-success-rate')
      expect(successRateCard).toHaveAttribute('data-color', '#f59e0b') // Warning color
    })
  })

  describe('Data Processing', () => {
    it('calculates trend data correctly', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // The component calculates previous values as 90% of current for mocking
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const trendChange = activeUsersCard.querySelector('[data-testid="trend-change"]')
      
      expect(trendChange).toHaveTextContent('11.1%')
    })

    it('calculates target values correctly', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const target = activeUsersCard.querySelector('[data-testid="kpi-target"]')
      
      // Target should be 120% of current value: 8932 * 1.2 = 10718.4 → 10718
      expect(target).toHaveTextContent('Target: 10718')
    })
  })

  describe('Accessibility', () => {
    it('uses semantic HTML elements', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const cardTitles = screen.getAllByTestId('card-title')
      expect(cardTitles.length).toBeGreaterThan(0)
    })

    it('provides meaningful content for screen readers', () => {
      render(
        <MetricsOverview 
          metrics={mockMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const activeUsersCard = screen.getByTestId('kpi-card-active-users')
      const title = activeUsersCard.querySelector('[data-testid="kpi-title"]')
      const value = activeUsersCard.querySelector('[data-testid="kpi-value"]')
      
      expect(title).toHaveTextContent('Active Users')
      expect(value).toHaveTextContent('8932')
    })
  })
})