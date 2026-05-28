// Analytics Dashboard Types and Interfaces

export interface AnalyticsMetrics {
  usage: UsageMetrics;
  performance: PerformanceMetrics;
  research: ResearchMetrics;
  system: SystemMetrics;
  engagement: EngagementMetrics;
}

export interface UsageMetrics {
  totalUsers: number;
  activeUsers: number;
  newUsers: number;
  sessionsPerUser: number;
  avgSessionDuration: number;
  pageViewsPerSession: number;
  bounceRate: number;
  topPages: Array<{
    page: string;
    views: number;
    uniqueUsers: number;
  }>;
  userGrowth: Array<{
    date: string;
    newUsers: number;
    activeUsers: number;
  }>;
  hourlyActivity: Array<{
    hour: number;
    users: number;
    sessions: number;
  }>;
}

export interface PerformanceMetrics {
  avgResponseTime: number;
  p50ResponseTime: number;
  p95ResponseTime: number;
  p99ResponseTime: number;
  successRate: number;
  errorRate: number;
  throughput: number;
  uptime: number;
  responseTimeHistory: Array<{
    timestamp: string;
    avgTime: number;
    p95Time: number;
  }>;
  errorBreakdown: Array<{
    type: string;
    count: number;
    percentage: number;
  }>;
  endpointPerformance: Array<{
    endpoint: string;
    avgTime: number;
    calls: number;
    errors: number;
  }>;
}

export interface ResearchMetrics {
  analysesRun: number;
  datasetsUsed: Map<string, number>;
  toolsUsed: Map<string, number>;
  popularWorkflows: Array<{
    workflow: string;
    usage: number;
    successRate: number;
  }>;
  publicationMetrics: {
    totalCitations: number;
    hIndex: number;
    recentPublications: number;
  };
  datasetStats: {
    totalDatasets: number;
    totalSubjects: number;
    modalityBreakdown: Record<string, number>;
  };
  toolUsageTrends: Array<{
    date: string;
    toolUsage: Record<string, number>;
  }>;
}

export interface SystemMetrics {
  cpuUsage: number;
  memoryUsage: number;
  gpuUsage: number;
  storageUsage: number;
  queueLength: number;
  activeJobs: number;
  completedJobs: number;
  failedJobs: number;
  throughput?: number;
  resourceHistory: Array<{
    timestamp: string;
    cpu: number;
    memory: number;
    gpu: number;
    storage: number;
  }>;
  jobQueue: Array<{
    id: string;
    type: string;
    status: 'queued' | 'running' | 'completed' | 'failed';
    startTime?: string;
    duration?: number;
    user: string;
  }>;
}

export interface EngagementMetrics {
  dailyActiveUsers: number;
  weeklyActiveUsers: number;
  monthlyActiveUsers: number;
  retentionRate: number;
  churnRate: number;
  avgTimeOnSite: number;
  conversionFunnels: Array<{
    name: string;
    steps: Array<{
      step: string;
      users: number;
      conversionRate: number;
    }>;
  }>;
  featureAdoption: Array<{
    feature: string;
    adoptionRate: number;
    activeUsers: number;
  }>;
  userSegments: Array<{
    segment: string;
    users: number;
    engagement: number;
  }>;
}

export interface TimeRange {
  label: string;
  value: string;
  start: Date;
  end: Date;
}

export interface AnalyticsFilter {
  timeRange: TimeRange;
  userSegment?: string;
  dataSource?: string;
  customFilters?: Record<string, any>;
}

export interface KPITrend {
  current: number;
  previous: number;
  change: number;
  changePercentage: number;
  trend: 'up' | 'down' | 'stable';
}

export interface ChartConfig {
  type: 'line' | 'bar' | 'area' | 'pie' | 'heatmap' | 'gauge' | 'funnel';
  data: any[];
  options: Record<string, any>;
  title?: string;
  description?: string;
}

export interface CustomReport {
  id: string;
  name: string;
  description?: string;
  charts: ChartConfig[];
  filters: AnalyticsFilter;
  schedule?: {
    frequency: 'daily' | 'weekly' | 'monthly';
    recipients: string[];
  };
  createdAt: Date;
  updatedAt: Date;
}

export interface AlertConfig {
  id: string;
  name: string;
  metric: string;
  threshold: number;
  condition: 'above' | 'below' | 'equals';
  severity: 'info' | 'warning' | 'error' | 'critical';
  enabled: boolean;
  recipients: string[];
  lastTriggered?: Date;
}

export interface AnalyticsDashboardState {
  metrics: AnalyticsMetrics | null;
  loading: boolean;
  error: string | null;
  filter: AnalyticsFilter;
  realTimeEnabled: boolean;
  customReports: CustomReport[];
  alerts: AlertConfig[];
  lastUpdated: Date | null;
}

// Widget-specific interfaces
export interface KPICardData {
  title: string;
  value: number | string;
  unit?: string;
  trend: KPITrend;
  /**
   * Whether an increasing value is "good" for coloring/alerts.
   * Defaults to true (up=good, down=bad). Set to false for metrics like latency/CPU usage where down is better.
   */
  isGoodWhenUp?: boolean;
  subtitle?: string;
  color?: string;
  target?: number;
  format?: 'number' | 'percentage' | 'currency' | 'time';
}

export interface GeographicData {
  country: string;
  users: number;
  sessions: number;
  coordinates: [number, number];
}

export interface HeatmapData {
  x: number;
  y: number;
  value: number;
  label?: string;
}

export interface FunnelStep {
  name: string;
  users: number;
  conversionRate: number;
  dropOffRate: number;
}

export interface CorrelationData {
  x: string;
  y: string;
  correlation: number;
  significance: number;
}
