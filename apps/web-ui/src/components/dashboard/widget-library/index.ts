export { AnalysisQueueWidget } from './AnalysisQueueWidget'
export { RecentResultsWidget } from './RecentResultsWidget'
export { ResourceUsageWidget } from './ResourceUsageWidget'
export { TeamActivityWidget } from './TeamActivityWidget'
export { QuickActionsWidget } from './QuickActionsWidget'
export { DatasetStatsWidget } from './DatasetStatsWidget'
export { CitationMetricsWidget } from './CitationMetricsWidget'
export { CustomChartWidget } from './CustomChartWidget'

import { 
  BarChart3,
  Download,
  Activity,
  Users,
  Play,
  Database,
  BookOpen,
  LineChart,
  LucideIcon
} from 'lucide-react'
import { WidgetType, WidgetCatalogItem } from '@/types/dashboard'

export const WIDGET_CATALOG: WidgetCatalogItem[] = [
  {
    type: WidgetType.ANALYSIS_QUEUE,
    name: 'Analysis Queue',
    description: 'Monitor running and queued analysis jobs',
    icon: BarChart3,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 12, h: 12 },
    category: 'analytics',
    tags: ['jobs', 'queue', 'analysis', 'monitoring']
  },
  {
    type: WidgetType.RECENT_RESULTS,
    name: 'Recent Results',
    description: 'View and download recent analysis outputs',
    icon: Download,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 8, h: 12 },
    category: 'analytics',
    tags: ['results', 'downloads', 'outputs', 'files']
  },
  {
    type: WidgetType.RESOURCE_USAGE,
    name: 'Resource Usage',
    description: 'Monitor CPU, GPU, memory and storage usage',
    icon: Activity,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 8, h: 10 },
    category: 'resources',
    tags: ['cpu', 'gpu', 'memory', 'storage', 'monitoring']
  },
  {
    type: WidgetType.TEAM_ACTIVITY,
    name: 'Team Activity',
    description: 'Track team member activities and collaborations',
    icon: Users,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 8, h: 12 },
    category: 'activity',
    tags: ['team', 'collaboration', 'activity', 'social']
  },
  {
    type: WidgetType.QUICK_ACTIONS,
    name: 'Quick Actions',
    description: 'Fast access to common tasks and functions',
    icon: Play,
    defaultSize: { w: 4, h: 8 },
    minSize: { w: 3, h: 6 },
    maxSize: { w: 6, h: 12 },
    category: 'actions',
    tags: ['shortcuts', 'actions', 'tools', 'productivity']
  },
  {
    type: WidgetType.DATASET_STATS,
    name: 'Dataset Statistics',
    description: 'Overview of available datasets and statistics',
    icon: Database,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 8, h: 12 },
    category: 'analytics',
    tags: ['datasets', 'statistics', 'data', 'overview']
  },
  {
    type: WidgetType.CITATION_METRICS,
    name: 'Citation Metrics',
    description: 'Track publications and citation metrics',
    icon: BookOpen,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 6 },
    maxSize: { w: 8, h: 12 },
    category: 'analytics',
    tags: ['publications', 'citations', 'research', 'metrics']
  },
  {
    type: WidgetType.CUSTOM_CHART,
    name: 'Custom Chart',
    description: 'Create and display custom data visualizations',
    icon: LineChart,
    defaultSize: { w: 8, h: 6 },
    minSize: { w: 4, h: 4 },
    maxSize: { w: 12, h: 12 },
    category: 'analytics',
    tags: ['charts', 'visualization', 'custom', 'data']
  }
]

export const getWidgetComponent = (type: WidgetType) => {
  switch (type) {
    case WidgetType.ANALYSIS_QUEUE:
      return require('./AnalysisQueueWidget').AnalysisQueueWidget
    case WidgetType.RECENT_RESULTS:
      return require('./RecentResultsWidget').RecentResultsWidget
    case WidgetType.RESOURCE_USAGE:
      return require('./ResourceUsageWidget').ResourceUsageWidget
    case WidgetType.TEAM_ACTIVITY:
      return require('./TeamActivityWidget').TeamActivityWidget
    case WidgetType.QUICK_ACTIONS:
      return require('./QuickActionsWidget').QuickActionsWidget
    case WidgetType.DATASET_STATS:
      return require('./DatasetStatsWidget').DatasetStatsWidget
    case WidgetType.CITATION_METRICS:
      return require('./CitationMetricsWidget').CitationMetricsWidget
    case WidgetType.CUSTOM_CHART:
      return require('./CustomChartWidget').CustomChartWidget
    default:
      return null
  }
}