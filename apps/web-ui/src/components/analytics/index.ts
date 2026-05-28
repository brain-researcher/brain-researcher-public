// Main Dashboard Component
export { AnalyticsDashboard } from './AnalyticsDashboard'

// Core Analytics Components  
export { MetricsOverview } from './MetricsOverview'
export { UsageAnalytics } from './UsageAnalytics'
export { PerformanceMonitor } from './PerformanceMonitor'
export { RealTimeMonitor } from './RealTimeMonitor'

// Enhanced Chart Components
export { TimeSeriesChart } from './TimeSeriesChart'
export type { 
  TimeSeriesDataPoint, 
  TimeSeriesLine, 
  TimeSeriesChartProps 
} from './TimeSeriesChart'

// UI Components
export { KPICard } from './KPICard'
export { ExportMenu } from './ExportMenu'
export { TimeRangeSelector } from './TimeRangeSelector'
export { DashboardCustomizer } from './DashboardCustomizer'

// Research and System Specific Components
export { ResearchInsights } from './ResearchInsights'
export { SystemHealthMonitor } from './SystemHealthMonitor'
export { ReportBuilder } from './ReportBuilder'
export { UsageChart } from './UsageChart'

// Error Handling and Loading States
export { 
  AnalyticsLoadingStates,
  LoadingProgress,
  KPICardSkeleton,
  ChartSkeleton,
  MetricsOverviewSkeleton,
  UsageAnalyticsSkeleleton,
  PerformanceMonitorSkeleton,
  RealTimeMonitorSkeleton
} from './AnalyticsLoadingStates'

// Re-export types for convenience
export type {
  AnalyticsMetrics,
  UsageMetrics,
  PerformanceMetrics,
  SystemMetrics,
  ResearchMetrics,
  EngagementMetrics,
  KPICardData,
  TimeRange,
  AnalyticsFilter,
  ChartConfig,
  CustomReport,
  AlertConfig,
  AnalyticsDashboardState,
  GeographicData,
  HeatmapData,
  FunnelStep,
  CorrelationData
} from '@/types/analytics'
