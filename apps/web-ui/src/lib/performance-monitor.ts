/**
 * Performance monitoring utilities for Brain Researcher UI
 * Tracks Core Web Vitals and custom performance metrics
 */

// Types for performance metrics
export interface PerformanceMetric {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
  timestamp: number;
  delta?: number;
}

export interface WebVitals {
  LCP?: PerformanceMetric; // Largest Contentful Paint
  FID?: PerformanceMetric; // First Input Delay
  CLS?: PerformanceMetric; // Cumulative Layout Shift
  FCP?: PerformanceMetric; // First Contentful Paint
  TTI?: PerformanceMetric; // Time to Interactive
  TTFB?: PerformanceMetric; // Time to First Byte
}

export interface CustomMetrics {
  chartRenderTime?: PerformanceMetric;
  graphLoadTime?: PerformanceMetric;
  apiResponseTime?: PerformanceMetric;
  bundleLoadTime?: PerformanceMetric;
  imageLoadTime?: PerformanceMetric;
  memoryUsage?: PerformanceMetric;
}

export interface PerformanceReport {
  webVitals: WebVitals;
  customMetrics: CustomMetrics;
  deviceInfo: {
    userAgent: string;
    connection?: string;
    memory?: number;
    cores?: number;
  };
  timestamp: number;
}

// Rating thresholds based on Core Web Vitals guidelines
const THRESHOLDS = {
  LCP: { good: 2500, poor: 4000 },
  FID: { good: 100, poor: 300 },
  CLS: { good: 0.1, poor: 0.25 },
  FCP: { good: 1800, poor: 3000 },
  TTI: { good: 3000, poor: 5000 }, // Our target: <3s
  TTFB: { good: 800, poor: 1800 }
};

// Performance observer singleton
class PerformanceMonitor {
  private metrics: Map<string, PerformanceMetric> = new Map();
  private observers: PerformanceObserver[] = [];
  private callbacks: Set<(metric: PerformanceMetric) => void> = new Set();
  private isSupported: boolean;

  constructor() {
    this.isSupported = typeof window !== 'undefined' && 
                      'performance' in window && 
                      'PerformanceObserver' in window;
    
    if (this.isSupported) {
      this.initializeObservers();
      this.measureInitialMetrics();
    }
  }

  private initializeObservers(): void {
    // Largest Contentful Paint
    try {
      const lcpObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries() as PerformanceEntry[];
        const lastEntry = entries[entries.length - 1];
        if (lastEntry) {
          this.recordMetric('LCP', lastEntry.startTime);
        }
      });
      lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });
      this.observers.push(lcpObserver);
    } catch (e) {
      console.warn('LCP observer not supported');
    }

    // First Input Delay
    try {
      const fidObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries() as any[];
        entries.forEach((entry) => {
          if (entry.processingStart && entry.startTime) {
            this.recordMetric('FID', entry.processingStart - entry.startTime);
          }
        });
      });
      fidObserver.observe({ entryTypes: ['first-input'] });
      this.observers.push(fidObserver);
    } catch (e) {
      console.warn('FID observer not supported');
    }

    // Cumulative Layout Shift
    try {
      const clsObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries() as any[];
        let clsValue = 0;
        entries.forEach((entry) => {
          if (!entry.hadRecentInput) {
            clsValue += entry.value;
          }
        });
        if (clsValue > 0) {
          this.recordMetric('CLS', clsValue);
        }
      });
      clsObserver.observe({ entryTypes: ['layout-shift'] });
      this.observers.push(clsObserver);
    } catch (e) {
      console.warn('CLS observer not supported');
    }

    // Paint metrics (FCP, LCP)
    try {
      const paintObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries() as PerformanceEntry[];
        entries.forEach((entry) => {
          if (entry.name === 'first-contentful-paint') {
            this.recordMetric('FCP', entry.startTime);
          }
        });
      });
      paintObserver.observe({ entryTypes: ['paint'] });
      this.observers.push(paintObserver);
    } catch (e) {
      console.warn('Paint observer not supported');
    }

    // Navigation timing for TTFB and TTI
    try {
      const navigationObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries() as PerformanceNavigationTiming[];
        entries.forEach((entry) => {
          // Time to First Byte
          const ttfb = entry.responseStart - entry.requestStart;
          this.recordMetric('TTFB', ttfb);

          // Estimate Time to Interactive (simplified)
          const navStart = (entry as any).navigationStart ?? entry.startTime ?? 0;
          const domComplete = entry.domComplete - navStart;
          const loadComplete = entry.loadEventEnd - navStart;
          const tti = Math.max(domComplete, loadComplete);
          this.recordMetric('TTI', tti);
        });
      });
      navigationObserver.observe({ entryTypes: ['navigation'] });
      this.observers.push(navigationObserver);
    } catch (e) {
      console.warn('Navigation observer not supported');
    }
  }

  private measureInitialMetrics(): void {
    // Measure memory usage if available
    if ('memory' in performance) {
      const memory = (performance as any).memory;
      this.recordMetric('memoryUsage', memory.usedJSHeapSize / 1024 / 1024); // MB
    }
  }

  private getRating(metricName: string, value: number): 'good' | 'needs-improvement' | 'poor' {
    const threshold = THRESHOLDS[metricName as keyof typeof THRESHOLDS];
    if (!threshold) return 'good';
    
    if (value <= threshold.good) return 'good';
    if (value <= threshold.poor) return 'needs-improvement';
    return 'poor';
  }

  recordMetric(name: string, value: number): void {
    const previousMetric = this.metrics.get(name);
    const metric: PerformanceMetric = {
      name,
      value,
      rating: this.getRating(name, value),
      timestamp: Date.now(),
      delta: previousMetric ? value - previousMetric.value : undefined
    };

    this.metrics.set(name, metric);
    this.callbacks.forEach(callback => callback(metric));
  }

  // Public methods
  public subscribe(callback: (metric: PerformanceMetric) => void): () => void {
    this.callbacks.add(callback);
    return () => this.callbacks.delete(callback);
  }

  public getMetric(name: string): PerformanceMetric | undefined {
    return this.metrics.get(name);
  }

  public getAllMetrics(): Map<string, PerformanceMetric> {
    return new Map(this.metrics);
  }

  public getWebVitals(): WebVitals {
    return {
      LCP: this.metrics.get('LCP'),
      FID: this.metrics.get('FID'),
      CLS: this.metrics.get('CLS'),
      FCP: this.metrics.get('FCP'),
      TTI: this.metrics.get('TTI'),
      TTFB: this.metrics.get('TTFB')
    };
  }

  public measureCustomMetric(name: string, startTime?: number): () => void {
    const start = startTime || performance.now();
    
    return () => {
      const end = performance.now();
      const duration = end - start;
      this.recordMetric(name, duration);
    };
  }

  public measureAsyncOperation<T>(
    name: string,
    operation: () => Promise<T>
  ): Promise<T> {
    const start = performance.now();
    
    return operation().finally(() => {
      const end = performance.now();
      const duration = end - start;
      this.recordMetric(name, duration);
    });
  }

  public getPerformanceReport(): PerformanceReport {
    const webVitals = this.getWebVitals();
    const customMetrics: CustomMetrics = {
      chartRenderTime: this.metrics.get('chartRenderTime'),
      graphLoadTime: this.metrics.get('graphLoadTime'),
      apiResponseTime: this.metrics.get('apiResponseTime'),
      bundleLoadTime: this.metrics.get('bundleLoadTime'),
      imageLoadTime: this.metrics.get('imageLoadTime'),
      memoryUsage: this.metrics.get('memoryUsage')
    };

    const deviceInfo = {
      userAgent: navigator.userAgent,
      connection: (navigator as any).connection?.effectiveType,
      memory: (navigator as any).deviceMemory,
      cores: navigator.hardwareConcurrency
    };

    return {
      webVitals,
      customMetrics,
      deviceInfo,
      timestamp: Date.now()
    };
  }

  public exportReport(): string {
    return JSON.stringify(this.getPerformanceReport(), null, 2);
  }

  public checkTTITarget(): boolean {
    const tti = this.metrics.get('TTI');
    return tti ? tti.value < 3000 : false; // Our <3s target
  }

  public destroy(): void {
    this.observers.forEach(observer => observer.disconnect());
    this.observers = [];
    this.callbacks.clear();
    this.metrics.clear();
  }
}

// Export singleton instance
export const performanceMonitor = new PerformanceMonitor();

// Helper functions for React components
export const usePerformanceMetric = (metricName: string) => {
  if (typeof window === 'undefined') return null;
  return performanceMonitor.getMetric(metricName);
};

export const measureComponentRender = (componentName: string) => {
  if (typeof window === 'undefined') return () => {};
  return performanceMonitor.measureCustomMetric(`${componentName}RenderTime`);
};

// Web Vitals integration for Next.js
export function reportWebVitals(metric: any) {
  if (typeof window === 'undefined') return;
  
  performanceMonitor.recordMetric(metric.name, metric.value);
  
  // Send to analytics service if needed
  if (process.env.NODE_ENV === 'production') {
    // gtag('event', metric.name, {
    //   value: Math.round(metric.name === 'CLS' ? metric.value * 1000 : metric.value),
    //   event_label: metric.id,
    //   non_interaction: true,
    // });
  }
}
