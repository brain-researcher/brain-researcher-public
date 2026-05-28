/**
 * React hooks for performance monitoring in Brain Researcher UI
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  performanceMonitor, 
  PerformanceMetric, 
  WebVitals, 
  PerformanceReport 
} from '@/lib/performance-monitor';

// Hook to subscribe to specific performance metrics
export function usePerformanceMetric(metricName: string) {
  const [metric, setMetric] = useState<PerformanceMetric | null>(null);

  useEffect(() => {
    // Get initial value
    const initialMetric = performanceMonitor.getMetric(metricName);
    if (initialMetric) {
      setMetric(initialMetric);
    }

    // Subscribe to updates
    const unsubscribe = performanceMonitor.subscribe((newMetric) => {
      if (newMetric.name === metricName) {
        setMetric(newMetric);
      }
    });

    return unsubscribe;
  }, [metricName]);

  return metric;
}

// Hook to track all Web Vitals
export function useWebVitals() {
  const [webVitals, setWebVitals] = useState<WebVitals>({});

  useEffect(() => {
    // Get initial values
    setWebVitals(performanceMonitor.getWebVitals());

    // Subscribe to updates
    const unsubscribe = performanceMonitor.subscribe((metric) => {
      const vitalNames = ['LCP', 'FID', 'CLS', 'FCP', 'TTI', 'TTFB'];
      if (vitalNames.includes(metric.name)) {
        setWebVitals(prev => ({
          ...prev,
          [metric.name]: metric
        }));
      }
    });

    return unsubscribe;
  }, []);

  return webVitals;
}

// Hook to measure component render time
export function useRenderPerformance(componentName: string) {
  const startTimeRef = useRef<number>();
  const endMeasure = useRef<(() => void) | null>(null);

  const startMeasure = useCallback(() => {
    startTimeRef.current = performance.now();
    endMeasure.current = performanceMonitor.measureCustomMetric(`${componentName}RenderTime`, startTimeRef.current);
  }, [componentName]);

  const finishMeasure = useCallback(() => {
    if (endMeasure.current) {
      endMeasure.current();
      endMeasure.current = null;
    }
  }, []);

  // Automatically start measuring on mount
  useEffect(() => {
    startMeasure();
    return finishMeasure;
  }, [startMeasure, finishMeasure]);

  return { startMeasure, finishMeasure };
}

// Hook to measure async operations (API calls, data loading)
export function useAsyncPerformance() {
  const measureAsync = useCallback(async <T>(
    operationName: string,
    operation: () => Promise<T>
  ): Promise<T> => {
    return performanceMonitor.measureAsyncOperation(operationName, operation);
  }, []);

  return { measureAsync };
}

// Hook to track page load performance
export function usePagePerformance() {
  const [metrics, setMetrics] = useState<{
    isLoading: boolean;
    loadTime?: number;
    tti?: number;
    lcp?: number;
    fcp?: number;
    meetsTarget: boolean;
  }>({
    isLoading: true,
    meetsTarget: false
  });

  useEffect(() => {
    const checkMetrics = () => {
      const webVitals = performanceMonitor.getWebVitals();
      const tti = webVitals.TTI?.value;
      const lcp = webVitals.LCP?.value;
      const fcp = webVitals.FCP?.value;
      
      // Calculate load time from navigation timing
      const loadTime = performance.timing 
        ? performance.timing.loadEventEnd - performance.timing.navigationStart 
        : undefined;

      const meetsTarget = performanceMonitor.checkTTITarget();
      const isLoading = !tti || !lcp || !fcp;

      setMetrics({
        isLoading,
        loadTime,
        tti,
        lcp,
        fcp,
        meetsTarget
      });
    };

    // Check immediately
    checkMetrics();

    // Subscribe to updates
    const unsubscribe = performanceMonitor.subscribe(() => {
      checkMetrics();
    });

    return unsubscribe;
  }, []);

  return metrics;
}

// Hook to track memory usage
export function useMemoryUsage() {
  const [memoryUsage, setMemoryUsage] = useState<{
    used: number;
    total: number;
    limit: number;
    percentage: number;
  } | null>(null);

  useEffect(() => {
    const updateMemoryUsage = () => {
      if ('memory' in performance) {
        const memory = (performance as any).memory;
        const usage = {
          used: memory.usedJSHeapSize / 1024 / 1024, // MB
          total: memory.totalJSHeapSize / 1024 / 1024, // MB
          limit: memory.jsHeapSizeLimit / 1024 / 1024, // MB
          percentage: (memory.usedJSHeapSize / memory.jsHeapSizeLimit) * 100
        };
        setMemoryUsage(usage);
      }
    };

    // Update initially
    updateMemoryUsage();

    // Update every 5 seconds
    const interval = setInterval(updateMemoryUsage, 5000);

    return () => clearInterval(interval);
  }, []);

  return memoryUsage;
}

// Hook to generate performance report
export function usePerformanceReport() {
  const [report, setReport] = useState<PerformanceReport | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const generateReport = useCallback(async () => {
    setIsGenerating(true);
    
    // Allow current metrics to settle
    await new Promise(resolve => setTimeout(resolve, 100));
    
    const newReport = performanceMonitor.getPerformanceReport();
    setReport(newReport);
    setIsGenerating(false);
  }, []);

  const exportReport = useCallback(() => {
    if (report) {
      const dataStr = JSON.stringify(report, null, 2);
      const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
      
      const exportFileDefaultName = `performance-report-${new Date().toISOString().split('T')[0]}.json`;
      
      const linkElement = document.createElement('a');
      linkElement.setAttribute('href', dataUri);
      linkElement.setAttribute('download', exportFileDefaultName);
      linkElement.click();
    }
  }, [report]);

  return {
    report,
    isGenerating,
    generateReport,
    exportReport
  };
}

// Hook for performance budgets and alerts
export function usePerformanceBudget(budgets: Record<string, number>) {
  const [violations, setViolations] = useState<Array<{
    metric: string;
    value: number;
    budget: number;
    severity: 'warning' | 'error';
  }>>([]);

  useEffect(() => {
    const checkBudgets = () => {
      const newViolations: typeof violations = [];
      
      Object.entries(budgets).forEach(([metricName, budget]) => {
        const metric = performanceMonitor.getMetric(metricName);
        if (metric && metric.value > budget) {
          newViolations.push({
            metric: metricName,
            value: metric.value,
            budget,
            severity: metric.value > budget * 1.5 ? 'error' : 'warning'
          });
        }
      });

      setViolations(newViolations);
    };

    // Check immediately
    checkBudgets();

    // Subscribe to metric updates
    const unsubscribe = performanceMonitor.subscribe(() => {
      checkBudgets();
    });

    return unsubscribe;
  }, [budgets]);

  return violations;
}

// Hook to track performance over time
export function usePerformanceHistory(metricName: string, maxEntries: number = 50) {
  const [history, setHistory] = useState<PerformanceMetric[]>([]);

  useEffect(() => {
    const unsubscribe = performanceMonitor.subscribe((metric) => {
      if (metric.name === metricName) {
        setHistory(prev => {
          const newHistory = [...prev, metric];
          return newHistory.slice(-maxEntries); // Keep only last N entries
        });
      }
    });

    return unsubscribe;
  }, [metricName, maxEntries]);

  const average = history.length > 0 
    ? history.reduce((sum, metric) => sum + metric.value, 0) / history.length
    : 0;

  const trend = history.length > 1
    ? history[history.length - 1].value - history[history.length - 2].value
    : 0;

  return {
    history,
    average,
    trend: trend > 0 ? 'up' : trend < 0 ? 'down' : 'stable'
  };
}

// Hook for real-time performance monitoring dashboard
export function usePerformanceDashboard() {
  const webVitals = useWebVitals();
  const memoryUsage = useMemoryUsage();
  const pagePerformance = usePagePerformance();
  const [customMetrics, setCustomMetrics] = useState<Map<string, PerformanceMetric>>(new Map());

  // Track custom metrics
  useEffect(() => {
    const unsubscribe = performanceMonitor.subscribe((metric) => {
      const customMetricNames = [
        'chartRenderTime',
        'graphLoadTime', 
        'apiResponseTime',
        'bundleLoadTime',
        'imageLoadTime'
      ];
      
      if (customMetricNames.some(name => metric.name.includes(name))) {
        setCustomMetrics(prev => new Map(prev.set(metric.name, metric)));
      }
    });

    return unsubscribe;
  }, []);

  const overallScore = calculatePerformanceScore(webVitals);

  return {
    webVitals,
    memoryUsage,
    pagePerformance,
    customMetrics,
    overallScore,
    status: overallScore >= 90 ? 'excellent' : 
           overallScore >= 70 ? 'good' : 
           overallScore >= 50 ? 'needs-improvement' : 'poor'
  };
}

// Helper function to calculate overall performance score
function calculatePerformanceScore(webVitals: WebVitals): number {
  const scores: number[] = [];
  
  // LCP Score (0-100)
  if (webVitals.LCP) {
    const lcp = webVitals.LCP.value;
    scores.push(lcp <= 2500 ? 100 : lcp <= 4000 ? 50 : 0);
  }
  
  // FID Score (0-100)  
  if (webVitals.FID) {
    const fid = webVitals.FID.value;
    scores.push(fid <= 100 ? 100 : fid <= 300 ? 50 : 0);
  }
  
  // CLS Score (0-100)
  if (webVitals.CLS) {
    const cls = webVitals.CLS.value;
    scores.push(cls <= 0.1 ? 100 : cls <= 0.25 ? 50 : 0);
  }
  
  // TTI Score (0-100) - Our key metric
  if (webVitals.TTI) {
    const tti = webVitals.TTI.value;
    scores.push(tti <= 3000 ? 100 : tti <= 5000 ? 50 : 0);
  }

  return scores.length > 0 ? scores.reduce((sum, score) => sum + score, 0) / scores.length : 0;
}