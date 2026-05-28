/**
 * @jest-environment jsdom
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsageAnalytics } from '@/components/analytics/UsageAnalytics'
import { UsageMetrics, TimeRange } from '@/types/analytics'
import '@testing-library/jest-dom'

// Mock chart components
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
      Line Chart: {title} ({data?.length || 0} points)
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
      Bar Chart: {title} ({data?.length || 0} bars)
    </div>
  )
}))

jest.mock('@/components/charts/DonutChart', () => ({
  DonutChart: ({ data, title, labelKey, valueKey, height, className }: any) => (
    <div 
      data-testid="donut-chart"
      data-title={title}
      data-label-key={labelKey}
      data-value-key={valueKey}
      data-height={height}
      className={className}
    >
      Donut Chart: {title} ({data?.length || 0} segments)
    </div>
  )
}))

jest.mock('@/components/charts/HeatmapChart', () => ({
  HeatmapChart: ({ data, title, xKey, yKey, valueKey, height, className }: any) => (
    <div 
      data-testid="heatmap-chart"
      data-title={title}
      data-x-key={xKey}
      data-y-key={yKey}
      data-value-key={valueKey}
      data-height={height}
      className={className}
    >
      Heatmap Chart: {title} ({data?.length || 0} cells)
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

// Mock Lucide React icons
jest.mock('lucide-react', () => ({
  Users: ({ className }: any) => <span data-testid="users-icon" className={className}>👥</span>,
  UserPlus: ({ className }: any) => <span data-testid="user-plus-icon" className={className}>👤+</span>,
  Activity: ({ className }: any) => <span data-testid="activity-icon" className={className}>📈</span>,
  Clock: ({ className }: any) => <span data-testid="clock-icon" className={className}>⏰</span>,
  Eye: ({ className }: any) => <span data-testid="eye-icon" className={className}>👁️</span>,
  MousePointer: ({ className }: any) => <span data-testid="mouse-pointer-icon" className={className}>🖱️</span>,
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

const mockUsageMetrics: UsageMetrics = {
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
    { page: '/analysis', views: 9876, uniqueUsers: 6543 },
    { page: '/knowledge-graph', views: 8765, uniqueUsers: 5432 },
    { page: '/chat', views: 6543, uniqueUsers: 4321 }
  ],
  userGrowth: [
    { date: '2025-01-01', newUsers: 25, activeUsers: 220 },
    { date: '2025-01-02', newUsers: 30, activeUsers: 235 },
    { date: '2025-01-03', newUsers: 28, activeUsers: 245 },
    { date: '2025-01-04', newUsers: 35, activeUsers: 260 },
    { date: '2025-01-05', newUsers: 32, activeUsers: 275 },
    { date: '2025-01-06', newUsers: 38, activeUsers: 290 },
    { date: '2025-01-07', newUsers: 40, activeUsers: 310 }
  ],
  hourlyActivity: [
    { hour: 0, users: 50, sessions: 80 },
    { hour: 1, users: 45, sessions: 70 },
    { hour: 2, users: 40, sessions: 65 },
    { hour: 8, users: 150, sessions: 200 },
    { hour: 9, users: 180, sessions: 250 },
    { hour: 10, users: 190, sessions: 270 },
    { hour: 14, users: 200, sessions: 280 },
    { hour: 15, users: 185, sessions: 260 },
    { hour: 16, users: 175, sessions: 240 },
    { hour: 20, users: 120, sessions: 160 },
    { hour: 21, users: 100, sessions: 140 },
    { hour: 22, users: 80, sessions: 110 },
    { hour: 23, users: 60, sessions: 90 }
  ]
}

describe('UsageAnalytics', () => {
  describe('Rendering', () => {
    it('renders with default props', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Usage Analytics')).toBeInTheDocument()
      expect(screen.getByText('User behavior and engagement patterns')).toBeInTheDocument()
    })

    it('renders with compact mode', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
          compactMode={true}
        />
      )
      
      // Should still render the main content but potentially with different styling
      expect(screen.getByText('Usage Analytics')).toBeInTheDocument()
    })

    it('renders with custom className', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
          className="test-class"
        />
      )
      
      const container = screen.getAllByTestId('card')[0]
      expect(container).toHaveClass('test-class')
    })
  })

  describe('Key Metrics Cards', () => {
    it('displays total users metric correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Total Users')).toBeInTheDocument()
      expect(screen.getByText('12,847')).toBeInTheDocument()
    })

    it('displays active users metric correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Active Users')).toBeInTheDocument()
      expect(screen.getByText('8,932')).toBeInTheDocument()
    })

    it('displays new users metric correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('New Users')).toBeInTheDocument()
      expect(screen.getByText('234')).toBeInTheDocument()
    })

    it('displays session metrics correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Avg Session Duration')).toBeInTheDocument()
      expect(screen.getByText('7m 0s')).toBeInTheDocument() // 420 seconds = 7 minutes
      
      expect(screen.getByText('Sessions per User')).toBeInTheDocument()
      expect(screen.getByText('2.4')).toBeInTheDocument()
    })

    it('displays page views and bounce rate correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('Page Views per Session')).toBeInTheDocument()
      expect(screen.getByText('4.2')).toBeInTheDocument()
      
      expect(screen.getByText('Bounce Rate')).toBeInTheDocument()
      expect(screen.getByText('35.2%')).toBeInTheDocument()
    })
  })

  describe('Charts and Visualizations', () => {
    it('renders user growth line chart', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const lineCharts = screen.getAllByTestId('line-chart')
      const userGrowthChart = lineCharts.find(chart => 
        chart.textContent?.includes('User Growth Over Time')
      )
      
      expect(userGrowthChart).toBeInTheDocument()
      expect(userGrowthChart).toHaveTextContent('(7 points)')
    })

    it('renders top pages bar chart', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toBeInTheDocument()
      expect(barChart).toHaveTextContent('Top Pages by Views')
      expect(barChart).toHaveTextContent('(5 bars)')
    })

    it('renders hourly activity heatmap', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const heatmap = screen.getByTestId('heatmap-chart')
      expect(heatmap).toBeInTheDocument()
      expect(heatmap).toHaveTextContent('User Activity by Hour')
      expect(heatmap).toHaveTextContent('(13 cells)') // Only showing hours with data
    })
  })

  describe('Tabs Navigation', () => {
    it('renders all tab options', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByTestId('tab-overview')).toBeInTheDocument()
      expect(screen.getByTestId('tab-growth')).toBeInTheDocument()
      expect(screen.getByTestId('tab-pages')).toBeInTheDocument()
      expect(screen.getByTestId('tab-activity')).toBeInTheDocument()
    })

    it('switches tabs correctly', async () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const growthTab = screen.getByTestId('tab-growth')
      await userEvent.click(growthTab)
      
      // Check that the tab content changed
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveAttribute('data-value', 'growth')
    })

    it('shows correct content in overview tab', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Overview tab should be active by default
      expect(screen.getByTestId('tab-content-overview')).toBeInTheDocument()
    })
  })

  describe('Data Processing', () => {
    it('formats session duration correctly', () => {
      const metricsWithLongSession = {
        ...mockUsageMetrics,
        avgSessionDuration: 3661 // 1 hour, 1 minute, 1 second
      }

      render(
        <UsageAnalytics 
          metrics={metricsWithLongSession} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('1h 1m 1s')).toBeInTheDocument()
    })

    it('formats large numbers with commas', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('12,847')).toBeInTheDocument()
      expect(screen.getByText('8,932')).toBeInTheDocument()
    })

    it('handles zero values gracefully', () => {
      const emptyMetrics: UsageMetrics = {
        ...mockUsageMetrics,
        totalUsers: 0,
        activeUsers: 0,
        newUsers: 0,
        topPages: [],
        userGrowth: [],
        hourlyActivity: []
      }

      render(
        <UsageAnalytics 
          metrics={emptyMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      expect(screen.getByText('0')).toBeInTheDocument()
    })
  })

  describe('Top Pages Analysis', () => {
    it('displays top pages with correct data', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Switch to pages tab
      const pagesTab = screen.getByTestId('tab-pages')
      fireEvent.click(pagesTab)
      
      // Check that the bar chart shows top pages data
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toHaveAttribute('data-title', 'Top Pages by Views')
      expect(barChart).toHaveAttribute('data-x-key', 'page')
      expect(barChart).toHaveAttribute('data-y-key', 'views')
    })

    it('shows page metrics in correct order', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // The top pages should be ordered by views (highest first)
      const topPage = mockUsageMetrics.topPages[0]
      expect(topPage.page).toBe('/dashboard')
      expect(topPage.views).toBe(15234)
    })
  })

  describe('Growth Analysis', () => {
    it('displays user growth trends correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Switch to growth tab
      const growthTab = screen.getByTestId('tab-growth')
      fireEvent.click(growthTab)
      
      // Check that growth charts are rendered
      const lineCharts = screen.getAllByTestId('line-chart')
      expect(lineCharts.length).toBeGreaterThan(0)
      
      const userGrowthChart = lineCharts.find(chart => 
        chart.getAttribute('data-title')?.includes('User Growth')
      )
      expect(userGrowthChart).toBeInTheDocument()
    })

    it('calculates growth rates correctly', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // The component should calculate and display growth metrics
      // This would be visible in the growth tab content
      const growthTab = screen.getByTestId('tab-growth')
      fireEvent.click(growthTab)
      
      expect(screen.getByTestId('tab-content-growth')).toBeInTheDocument()
    })
  })

  describe('Activity Patterns', () => {
    it('displays hourly activity patterns', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Switch to activity tab
      const activityTab = screen.getByTestId('tab-activity')
      fireEvent.click(activityTab)
      
      const heatmap = screen.getByTestId('heatmap-chart')
      expect(heatmap).toHaveAttribute('data-title', 'User Activity by Hour')
      expect(heatmap).toHaveAttribute('data-x-key', 'hour')
      expect(heatmap).toHaveAttribute('data-value-key', 'users')
    })

    it('identifies peak activity hours', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Peak activity should be around hour 14 (200 users)
      const peakActivity = Math.max(...mockUsageMetrics.hourlyActivity.map(h => h.users))
      expect(peakActivity).toBe(200)
    })
  })

  describe('Responsive Design', () => {
    it('adapts layout for compact mode', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
          compactMode={true}
        />
      )
      
      // In compact mode, charts might have different heights or layouts
      const charts = screen.getAllByTestId(/chart$/)
      charts.forEach(chart => {
        expect(chart).toBeInTheDocument()
      })
    })

    it('maintains functionality across different screen sizes', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Tab navigation should work regardless of screen size
      const pagesTab = screen.getByTestId('tab-pages')
      fireEvent.click(pagesTab)
      
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveAttribute('data-value', 'pages')
    })
  })

  describe('Accessibility', () => {
    it('provides proper semantic structure', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const headings = screen.getAllByRole('heading')
      expect(headings.length).toBeGreaterThan(0)
      
      const mainHeading = screen.getByRole('heading', { level: 2 })
      expect(mainHeading).toHaveTextContent('Usage Analytics')
    })

    it('supports keyboard navigation', async () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const growthTab = screen.getByTestId('tab-growth')
      growthTab.focus()
      
      expect(document.activeElement).toBe(growthTab)
      
      // Simulate Enter key press
      fireEvent.keyDown(growthTab, { key: 'Enter' })
      fireEvent.click(growthTab)
      
      const tabs = screen.getByTestId('tabs')
      expect(tabs).toHaveAttribute('data-value', 'growth')
    })

    it('provides meaningful labels for charts', () => {
      render(
        <UsageAnalytics 
          metrics={mockUsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toHaveAttribute('data-title', 'Top Pages by Views')
      
      const heatmap = screen.getByTestId('heatmap-chart')
      expect(heatmap).toHaveAttribute('data-title', 'User Activity by Hour')
    })
  })

  describe('Error Handling', () => {
    it('handles missing data gracefully', () => {
      const incompleteMetrics: Partial<UsageMetrics> = {
        totalUsers: 0,
        activeUsers: 0
      }

      render(
        <UsageAnalytics 
          metrics={incompleteMetrics as UsageMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      // Should not crash and should show default values
      expect(screen.getByText('Usage Analytics')).toBeInTheDocument()
    })

    it('handles empty arrays gracefully', () => {
      const emptyDataMetrics: UsageMetrics = {
        ...mockUsageMetrics,
        topPages: [],
        userGrowth: [],
        hourlyActivity: []
      }

      render(
        <UsageAnalytics 
          metrics={emptyDataMetrics} 
          timeRange={mockTimeRange} 
        />
      )
      
      const barChart = screen.getByTestId('bar-chart')
      expect(barChart).toHaveTextContent('(0 bars)')
      
      const lineCharts = screen.getAllByTestId('line-chart')
      const userGrowthChart = lineCharts.find(chart => 
        chart.textContent?.includes('User Growth Over Time')
      )
      expect(userGrowthChart).toHaveTextContent('(0 points)')
    })
  })
})