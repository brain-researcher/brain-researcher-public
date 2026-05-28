import { ReactNode } from 'react';

export interface WidgetPosition {
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
  maxW?: number;
  maxH?: number;
}

export interface WidgetConfig {
  refreshInterval?: number; // ms
  showHeader?: boolean;
  title?: string;
  color?: string;
  [key: string]: any;
}

export enum WidgetType {
  ANALYSIS_QUEUE = 'analysis_queue',
  RECENT_RESULTS = 'recent_results',
  RESOURCE_USAGE = 'resource_usage',
  TEAM_ACTIVITY = 'team_activity',
  QUICK_ACTIONS = 'quick_actions',
  DATASET_STATS = 'dataset_stats',
  CITATION_METRICS = 'citation_metrics',
  CUSTOM_CHART = 'custom_chart'
}

export interface Widget {
  id: string;
  type: WidgetType;
  title: string;
  position: WidgetPosition;
  config: WidgetConfig;
  visible: boolean;
  locked?: boolean;
  created_at: Date;
  updated_at: Date;
}

export interface BreakpointLayouts {
  lg: Array<{ i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number; maxW?: number; maxH?: number }>;
  md: Array<{ i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number; maxW?: number; maxH?: number }>;
  sm: Array<{ i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number; maxW?: number; maxH?: number }>;
  xs: Array<{ i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number; maxW?: number; maxH?: number }>;
  [key: string]: Array<{ i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number; maxW?: number; maxH?: number }>;
}

export interface DashboardLayout {
  id: string;
  name: string;
  description?: string;
  widgets: Widget[];
  breakpoints: BreakpointLayouts;
  isDefault: boolean;
  user_id?: string;
  created_at: Date;
  updated_at: Date;
}

export interface WidgetProps {
  widget: Widget;
  data?: any;
  loading?: boolean;
  error?: string;
  onConfigChange?: (config: WidgetConfig) => void;
  onRemove?: () => void;
  onRefresh?: () => void;
  className?: string;
}

export interface WidgetComponentProps extends WidgetProps {
  children?: ReactNode;
}

export interface DashboardState {
  currentLayout: DashboardLayout | null;
  availableLayouts: DashboardLayout[];
  isEditing: boolean;
  selectedWidget: Widget | null;
  configPanelOpen: boolean;
}

export interface DashboardActions {
  loadLayout: (layoutId: string) => Promise<void>;
  saveLayout: (layout: DashboardLayout) => Promise<void>;
  createLayout: (name: string, description?: string) => Promise<DashboardLayout>;
  deleteLayout: (layoutId: string) => Promise<void>;
  duplicateLayout: (layoutId: string, newName: string) => Promise<DashboardLayout>;
  exportLayout: (layoutId: string) => Promise<string>;
  importLayout: (layoutData: string) => Promise<DashboardLayout>;
  
  addWidget: (type: WidgetType, position?: Partial<WidgetPosition>) => void;
  removeWidget: (widgetId: string) => void;
  updateWidget: (widgetId: string, updates: Partial<Widget>) => void;
  updateWidgetConfig: (widgetId: string, config: WidgetConfig) => void;
  moveWidget: (widgetId: string, position: WidgetPosition) => void;
  
  setEditing: (editing: boolean) => void;
  setSelectedWidget: (widget: Widget | null) => void;
  setConfigPanelOpen: (open: boolean) => void;
  
  resetToDefault: () => void;
  autoArrangeWidgets: () => void;
}

import { LucideIcon } from 'lucide-react';

export interface WidgetCatalogItem {
  type: WidgetType;
  name: string;
  description: string;
  icon: LucideIcon | ReactNode;
  defaultSize: { w: number; h: number };
  minSize: { w: number; h: number };
  maxSize?: { w: number; h: number };
  category: 'analytics' | 'resources' | 'activity' | 'actions';
  tags: string[];
  preview?: string;
}

// Widget data interfaces for each widget type
export interface AnalysisQueueData {
  running: number;
  queued: number;
  completed_today: number;
  failed: number;
  recent_jobs: Array<{
    id: string;
    title: string;
    status: 'running' | 'queued' | 'completed' | 'failed';
    progress?: number;
    eta?: string;
    user: string;
  }>;
}

export interface RecentResultsData {
  results: Array<{
    id: string;
    title: string;
    type: 'brain_map' | 'report' | 'chart' | 'table';
    size: string;
    created_at: Date;
    download_url: string;
    thumbnail_url?: string;
  }>;
}

export interface ResourceUsageData {
  cpu: {
    usage: number;
    cores: number;
    frequency: number;
  };
  memory: {
    used: number;
    total: number;
    percentage: number;
  };
  gpu: {
    count: number;
    usage: number[];
    memory_used: number[];
    memory_total: number[];
  };
  storage: {
    used: number;
    total: number;
    percentage: number;
  };
}

export interface TeamActivityData {
  activities: Array<{
    id: string;
    user: string;
    action: string;
    timestamp: Date;
    type: 'analysis' | 'upload' | 'share' | 'error' | 'success';
  }>;
}

export interface DatasetStatsData {
  total_datasets: number;
  total_subjects: number;
  total_sessions: number;
  modalities: Record<string, number>;
  categories: Record<string, number>;
  recent_uploads: Array<{
    id: string;
    name: string;
    subjects: number;
    modality: string;
    uploaded_at: Date;
  }>;
}

export interface CitationMetricsData {
  total_citations: number;
  h_index: number;
  recent_publications: Array<{
    title: string;
    authors: string[];
    journal: string;
    year: number;
    citations: number;
    doi?: string;
  }>;
  trending_topics: string[];
}

export interface CustomChartData {
  chart_type: 'line' | 'bar' | 'scatter' | 'heatmap';
  data: any[];
  config: {
    x_axis: string;
    y_axis: string;
    title?: string;
    color_scheme?: string;
  };
}
