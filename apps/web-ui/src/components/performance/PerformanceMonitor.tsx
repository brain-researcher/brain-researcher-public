/**
 * Performance monitoring dashboard component
 * Real-time performance metrics display with alerts and insights
 */

'use client';

import React, { useState } from 'react';
import { 
  Activity, 
  TrendingUp, 
  TrendingDown, 
  Clock, 
  Zap, 
  Eye,
  AlertTriangle,
  CheckCircle,
  XCircle,
  BarChart3,
  Download,
  RefreshCw,
  Info
} from 'lucide-react';
import { 
  useWebVitals, 
  useMemoryUsage, 
  usePerformanceDashboard,
  usePerformanceReport,
  usePerformanceBudget 
} from '@/hooks/use-performance';
import { Card } from '@/components/ui/card';

interface MetricCardProps {
  title: string;
  value: number | string;
  unit?: string;
  rating: 'good' | 'needs-improvement' | 'poor';
  trend?: 'up' | 'down' | 'stable';
  target?: number;
  description?: string;
  icon: React.ReactNode;
}

function MetricCard({ 
  title, 
  value, 
  unit = 'ms', 
  rating, 
  trend, 
  target, 
  description,
  icon 
}: MetricCardProps) {
  const getRatingColor = (rating: string) => {
    switch (rating) {
      case 'good': return 'text-green-600 bg-green-50 border-green-200';
      case 'needs-improvement': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      case 'poor': return 'text-red-600 bg-red-50 border-red-200';
      default: return 'text-gray-600 bg-gray-50 border-gray-200';
    }
  };

  const getRatingIcon = (rating: string) => {
    switch (rating) {
      case 'good': return <CheckCircle className="w-4 h-4" />;
      case 'needs-improvement': return <AlertTriangle className="w-4 h-4" />;
      case 'poor': return <XCircle className="w-4 h-4" />;
      default: return null;
    }
  };

  const getTrendIcon = (trend?: string) => {
    switch (trend) {
      case 'up': return <TrendingUp className="w-3 h-3 text-red-500" />;
      case 'down': return <TrendingDown className="w-3 h-3 text-green-500" />;
      default: return null;
    }
  };

  return (
    <Card className={`p-4 border-l-4 ${getRatingColor(rating)}`}>
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-white dark:bg-gray-800 shadow-sm">
            {icon}
          </div>
          <div>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {title}
            </h3>
            <div className="flex items-center space-x-2 mt-1">
              <span className="text-2xl font-bold text-gray-900 dark:text-white">
                {typeof value === 'number' ? value.toFixed(0) : value}
              </span>
              <span className="text-sm text-gray-500">{unit}</span>
              {getTrendIcon(trend)}
            </div>
            {target && (
              <div className="text-xs text-gray-500 mt-1">
                Target: &lt; {target}{unit}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center space-x-1">
          {getRatingIcon(rating)}
          {description && (
            <div className="group relative">
              <Info className="w-4 h-4 text-gray-400 cursor-help" />
              <div className="absolute right-0 top-6 w-64 p-2 bg-black text-white text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-10">
                {description}
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

interface PerformanceMonitorProps {
  compact?: boolean;
  showDetails?: boolean;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

export function PerformanceMonitor({
  compact = false,
  showDetails = true,
  autoRefresh = true,
  refreshInterval = 5000
}: PerformanceMonitorProps) {
  const [isExpanded, setIsExpanded] = useState(!compact);
  const { webVitals, memoryUsage, customMetrics, overallScore, status } = usePerformanceDashboard();
  const { report, isGenerating, generateReport, exportReport } = usePerformanceReport();

  // Performance budgets (in ms, except CLS which is unitless)
  const budgets = {
    TTI: 3000,  // Our key target
    LCP: 2500,
    FCP: 1800,
    FID: 100,
    CLS: 0.1,
    apiResponseTime: 1000,
    chartRenderTime: 500
  };

  const violations = usePerformanceBudget(budgets);

  // Auto-refresh effect
  React.useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(() => {
        generateReport();
      }, refreshInterval);

      return () => clearInterval(interval);
    }
  }, [autoRefresh, refreshInterval, generateReport]);

  const getOverallStatusColor = (status: string) => {
    switch (status) {
      case 'excellent': return 'text-green-600 bg-green-50 border-green-200';
      case 'good': return 'text-blue-600 bg-blue-50 border-blue-200';
      case 'needs-improvement': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      case 'poor': return 'text-red-600 bg-red-50 border-red-200';
      default: return 'text-gray-600 bg-gray-50 border-gray-200';
    }
  };

  if (compact && !isExpanded) {
    return (
      <div 
        className={`fixed bottom-4 right-4 p-3 rounded-lg shadow-lg cursor-pointer transition-all duration-200 hover:shadow-xl ${getOverallStatusColor(status)}`}
        onClick={() => setIsExpanded(true)}
      >
        <div className="flex items-center space-x-2">
          <Activity className="w-5 h-5" />
          <span className="font-medium">Performance: {status}</span>
          <span className="text-sm">({overallScore}/100)</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`${compact ? 'fixed bottom-4 right-4 w-96 max-h-[80vh] overflow-y-auto' : ''} bg-white dark:bg-gray-900 rounded-lg shadow-lg border`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Activity className="w-6 h-6 text-blue-600" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Performance Monitor
              </h2>
              <div className="flex items-center space-x-2 mt-1">
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${getOverallStatusColor(status)}`}>
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                </span>
                <span className="text-sm text-gray-500">Score: {overallScore}/100</span>
              </div>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={generateReport}
              disabled={isGenerating}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md"
              title="Refresh metrics"
            >
              <RefreshCw className={`w-4 h-4 ${isGenerating ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={exportReport}
              disabled={!report}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md"
              title="Export report"
            >
              <Download className="w-4 h-4" />
            </button>
            {compact && (
              <button
                onClick={() => setIsExpanded(false)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md"
              >
                ×
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Violations Alert */}
      {violations.length > 0 && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800">
          <div className="flex items-center space-x-2 mb-2">
            <AlertTriangle className="w-5 h-5 text-red-600" />
            <span className="font-medium text-red-800 dark:text-red-300">
              Performance Budget Violations ({violations.length})
            </span>
          </div>
          <div className="space-y-1">
            {violations.map((violation, index) => (
              <div key={index} className="text-sm text-red-700 dark:text-red-300">
                <strong>{violation.metric}:</strong> {violation.value.toFixed(0)}ms 
                (budget: {violation.budget}ms) 
                <span className={`ml-2 px-1 rounded text-xs ${violation.severity === 'error' ? 'bg-red-200 text-red-800' : 'bg-yellow-200 text-yellow-800'}`}>
                  {violation.severity}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Core Web Vitals */}
      <div className="p-4">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3 flex items-center">
          <Zap className="w-4 h-4 mr-2" />
          Core Web Vitals
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {webVitals.TTI && (
            <MetricCard
              title="Time to Interactive (TTI)"
              value={webVitals.TTI.value}
              rating={webVitals.TTI.rating}
              target={3000}
              description="Time until page is fully interactive. Our key target: <3s"
              icon={<Clock className="w-5 h-5 text-purple-600" />}
            />
          )}
          {webVitals.LCP && (
            <MetricCard
              title="Largest Contentful Paint"
              value={webVitals.LCP.value}
              rating={webVitals.LCP.rating}
              target={2500}
              description="Time to render the largest visible element"
              icon={<Eye className="w-5 h-5 text-blue-600" />}
            />
          )}
          {webVitals.FID && (
            <MetricCard
              title="First Input Delay"
              value={webVitals.FID.value}
              rating={webVitals.FID.rating}
              target={100}
              description="Time from first interaction to browser response"
              icon={<Zap className="w-5 h-5 text-green-600" />}
            />
          )}
          {webVitals.CLS && (
            <MetricCard
              title="Cumulative Layout Shift"
              value={webVitals.CLS.value}
              unit=""
              rating={webVitals.CLS.rating}
              target={0.1}
              description="Visual stability - lower is better"
              icon={<BarChart3 className="w-5 h-5 text-orange-600" />}
            />
          )}
          {webVitals.FCP && (
            <MetricCard
              title="First Contentful Paint"
              value={webVitals.FCP.value}
              rating={webVitals.FCP.rating}
              target={1800}
              description="Time to first visible content"
              icon={<Eye className="w-5 h-5 text-teal-600" />}
            />
          )}
          {webVitals.TTFB && (
            <MetricCard
              title="Time to First Byte"
              value={webVitals.TTFB.value}
              rating={webVitals.TTFB.rating}
              target={800}
              description="Server response time"
              icon={<Activity className="w-5 h-5 text-indigo-600" />}
            />
          )}
        </div>
      </div>

      {/* Memory Usage */}
      {memoryUsage && (
        <div className="p-4 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            Memory Usage
          </h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Used Memory</span>
              <span className="text-sm font-medium">{memoryUsage.used.toFixed(1)} MB</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div 
                className={`h-2 rounded-full transition-all duration-300 ${
                  memoryUsage.percentage > 80 ? 'bg-red-500' : 
                  memoryUsage.percentage > 60 ? 'bg-yellow-500' : 'bg-green-500'
                }`}
                style={{ width: `${Math.min(memoryUsage.percentage, 100)}%` }}
              />
            </div>
            <div className="text-xs text-gray-500">
              {memoryUsage.percentage.toFixed(1)}% of {memoryUsage.limit.toFixed(0)} MB limit
            </div>
          </div>
        </div>
      )}

      {/* Custom Metrics */}
      {showDetails && customMetrics.size > 0 && (
        <div className="p-4 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            Custom Metrics
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Array.from(customMetrics.entries()).map(([name, metric]) => (
              <MetricCard
                key={name}
                title={name.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase())}
                value={metric.value}
                rating={metric.rating}
                description="Application-specific performance metric"
                icon={<BarChart3 className="w-5 h-5 text-gray-600" />}
              />
            ))}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      {showDetails && (
        <div className="p-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Last updated: {new Date().toLocaleTimeString()}
            </span>
            <div className="flex items-center space-x-2">
              {violations.length > 0 && (
                <span className="text-xs text-red-600">
                  {violations.length} issues found
                </span>
              )}
              {webVitals.TTI?.value && webVitals.TTI.value < 3000 && (
                <span className="text-xs text-green-600 flex items-center">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  TTI target met
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PerformanceMonitor;