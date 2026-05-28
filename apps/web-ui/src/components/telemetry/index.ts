/**
 * Telemetry Components Index
 * TELEMETRY-003 Usage Metrics Tracking System
 */

export { 
  TelemetryProvider, 
  useTelemetry, 
  useInteractionTracking,
  usePerformanceTracking,
  useErrorTracking
} from './telemetry-provider';

export { UsageMetricsPanel } from './usage-metrics-panel';
export { FeatureAdoptionChart } from './feature-adoption-chart';
export { ToolUsageHeatmap } from './tool-usage-heatmap';

// Re-export types for convenience
export type {
  TelemetryEvent,
  TelemetryConfig,
  UsageMetric,
  FeatureUsage,
  TelemetryContextValue
} from './telemetry-provider';