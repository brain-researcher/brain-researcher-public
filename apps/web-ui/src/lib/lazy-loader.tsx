/**
 * Advanced lazy loading utilities for Brain Researcher UI
 * Provides comprehensive lazy loading strategies for components, images, and data
 */

import { lazy, ComponentType, ReactElement, Suspense } from 'react';
import dynamic from 'next/dynamic';

// Types
export interface LazyComponentOptions {
  loading?: ComponentType;
  fallback?: ReactElement;
  ssr?: boolean;
  timeout?: number;
  retries?: number;
}

export interface IntersectionObserverOptions {
  root?: Element | null;
  rootMargin?: string;
  threshold?: number | number[];
  once?: boolean;
}

export interface LazyImageOptions {
  placeholder?: string;
  blur?: boolean;
  quality?: number;
  priority?: boolean;
  sizes?: string;
  onLoad?: () => void;
  onError?: () => void;
}

// Default loading component
const DefaultLoadingComponent = () => (
  <div className="flex items-center justify-center p-8">
    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
  </div>
);

// Skeleton loader for different content types
export const SkeletonLoaders = {
  Chart: () => (
    <div className="animate-pulse">
      <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded-lg mb-4"></div>
      <div className="flex space-x-4">
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/4"></div>
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/3"></div>
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/6"></div>
      </div>
    </div>
  ),
  
  KnowledgeGraph: () => (
    <div className="animate-pulse">
      <div className="h-96 bg-gray-200 dark:bg-gray-700 rounded-lg mb-4 relative">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-gray-400 dark:text-gray-500">Loading Knowledge Graph...</div>
        </div>
      </div>
    </div>
  ),
  
  DataTable: () => (
    <div className="animate-pulse space-y-3">
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-4 bg-gray-200 dark:bg-gray-700 rounded"></div>
        ))}
      </div>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, j) => (
            <div key={j} className="h-3 bg-gray-100 dark:bg-gray-800 rounded"></div>
          ))}
        </div>
      ))}
    </div>
  ),
  
  Dashboard: () => (
    <div className="animate-pulse space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
        <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
      </div>
    </div>
  )
};

// Enhanced lazy component wrapper with error boundaries and retries
export function createLazyComponent<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>,
  options: LazyComponentOptions = {}
): ComponentType<any> {
  const {
    loading = DefaultLoadingComponent,
    ssr = false,
    timeout = 10000,
    retries = 2
  } = options;

  // For Next.js dynamic imports with enhanced options
  if (typeof window !== 'undefined' || !ssr) {
    const LoadingComp = loading;
    return dynamic(importFn, {
      loading: () => <LoadingComp />,
      ssr,
      // Add timeout and retry logic
      suspense: false
    });
  }

  // Fallback to React.lazy with retry logic
  let retryCount = 0;
  const retryImport = (): Promise<{ default: T }> => {
    return importFn().catch(error => {
      if (retryCount < retries) {
        retryCount++;
        console.warn(`Import failed, retrying (${retryCount}/${retries}):`, error);
        // Exponential backoff
        return new Promise(resolve => {
          setTimeout(() => resolve(retryImport()), Math.pow(2, retryCount) * 1000);
        });
      }
      throw error;
    });
  };

  return lazy(retryImport);
}

// Intersection Observer utility for viewport-based lazy loading
export class LazyIntersectionObserver {
  private static instance: LazyIntersectionObserver;
  private observers: Map<Element, IntersectionObserver> = new Map();
  private callbacks: Map<Element, () => void> = new Map();

  static getInstance(): LazyIntersectionObserver {
    if (!LazyIntersectionObserver.instance) {
      LazyIntersectionObserver.instance = new LazyIntersectionObserver();
    }
    return LazyIntersectionObserver.instance;
  }

  observe(
    element: Element,
    callback: () => void,
    options: IntersectionObserverOptions = {}
  ): () => void {
    const {
      root = null,
      rootMargin = '50px',
      threshold = 0.1,
      once = true
    } = options;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            callback();
            if (once) {
              this.unobserve(element);
            }
          }
        });
      },
      { root, rootMargin, threshold }
    );

    observer.observe(element);
    this.observers.set(element, observer);
    this.callbacks.set(element, callback);

    return () => this.unobserve(element);
  }

  unobserve(element: Element): void {
    const observer = this.observers.get(element);
    if (observer) {
      observer.unobserve(element);
      observer.disconnect();
      this.observers.delete(element);
      this.callbacks.delete(element);
    }
  }

  disconnect(): void {
    this.observers.forEach(observer => observer.disconnect());
    this.observers.clear();
    this.callbacks.clear();
  }
}

// Lazy loading hook for React components
export function useLazyLoad(
  callback: () => void,
  options: IntersectionObserverOptions = {}
) {
  const observer = LazyIntersectionObserver.getInstance();
  
  return (element: Element | null) => {
    if (element) {
      return observer.observe(element, callback, options);
    }
    return () => {};
  };
}

// Progressive image loading utility
export class ProgressiveImageLoader {
  private static cache = new Map<string, HTMLImageElement>();

  static async loadImage(src: string, options: LazyImageOptions = {}): Promise<HTMLImageElement> {
    const { quality = 85, onLoad, onError } = options;

    // Check cache first
    if (this.cache.has(src)) {
      const cachedImage = this.cache.get(src)!;
      onLoad?.();
      return cachedImage;
    }

    return new Promise((resolve, reject) => {
      const img = new Image();
      
      img.onload = () => {
        this.cache.set(src, img);
        onLoad?.();
        resolve(img);
      };
      
      img.onerror = (error) => {
        onError?.();
        reject(error);
      };
      
      // Add quality parameter if supported
      const url = new URL(src, window.location.origin);
      if (quality < 100) {
        url.searchParams.set('q', quality.toString());
      }
      
      img.src = url.toString();
    });
  }

  static preloadImages(srcs: string[], options: LazyImageOptions = {}): Promise<HTMLImageElement[]> {
    return Promise.all(srcs.map(src => this.loadImage(src, options)));
  }

  static clearCache(): void {
    this.cache.clear();
  }
}

// Lazy data loading utility with caching
export class LazyDataLoader<T = any> {
  private static cache = new Map<string, { data: any; timestamp: number; ttl: number }>();

  static async loadData<T>(
    key: string,
    fetcher: () => Promise<T>,
    options: { ttl?: number; force?: boolean } = {}
  ): Promise<T> {
    const { ttl = 300000, force = false } = options; // Default 5 minutes TTL

    // Check cache first
    if (!force && this.cache.has(key)) {
      const cached = this.cache.get(key)!;
      if (Date.now() - cached.timestamp < cached.ttl) {
        return cached.data as T;
      }
    }

    // Fetch new data
    try {
      const data = await fetcher();
      this.cache.set(key, {
        data,
        timestamp: Date.now(),
        ttl
      });
      return data;
    } catch (error) {
      // Return stale data if available
      if (this.cache.has(key)) {
        console.warn('Using stale data due to fetch error:', error);
        return this.cache.get(key)!.data as T;
      }
      throw error;
    }
  }

  static invalidate(key?: string): void {
    if (key) {
      this.cache.delete(key);
    } else {
      this.cache.clear();
    }
  }

  static preload<T>(key: string, fetcher: () => Promise<T>): void {
    // Fire and forget preload
    this.loadData(key, fetcher).catch(console.error);
  }
}

// Lazy component definitions for heavy components
export const LazyComponents = {
  // Charts
  LineChart: createLazyComponent(
    () => import('@/components/charts/LineChart').then(m => ({ default: (m as any).default || (m as any).LineChart })),
    { loading: SkeletonLoaders.Chart, ssr: false }
  ),
  
  BarChart: createLazyComponent(
    () => import('@/components/charts/BarChart').then(m => ({ default: (m as any).default || (m as any).BarChart })),
    { loading: SkeletonLoaders.Chart, ssr: false }
  ),

  Heatmap: createLazyComponent(
    () => import('@/components/charts/Heatmap').then(m => ({ default: (m as any).default || (m as any).Heatmap })),
    { loading: SkeletonLoaders.Chart, ssr: false }
  ),

  ScatterPlot: createLazyComponent(
    () => import('@/components/charts/ScatterPlot').then(m => ({ default: (m as any).default || (m as any).ScatterPlot })),
    { loading: SkeletonLoaders.Chart, ssr: false }
  ),

  // 3D Components (heaviest)
  Brain3D: createLazyComponent(
    () => import('@/components/brain/Brain3D').then(m => ({ default: (m as any).default || (m as any).Brain3D })),
    { loading: () => <div className="h-96 bg-gray-100 dark:bg-gray-800 rounded-lg flex items-center justify-center">Loading 3D Brain...</div>, ssr: false }
  ),

  // Knowledge Graph
  KnowledgeGraphExplorer: createLazyComponent(
    () => import('@/components/knowledge-graph/ExplorerView').then(m => ({ default: (m as any).default || (m as any).ExplorerView })),
    { loading: SkeletonLoaders.KnowledgeGraph, ssr: false }
  ),

  // Analytics Dashboard
  AnalyticsDashboard: createLazyComponent(
    () => import('@/components/analytics/AnalyticsDashboard').then(m => ({ default: (m as any).default || (m as any).AnalyticsDashboard })),
    { loading: SkeletonLoaders.Dashboard, ssr: false }
  ),

  // Result Display
  ResultDisplay: createLazyComponent(
    () => import('@/components/results/basic-result-display').then(mod => ({ default: mod.BasicResultDisplay })),
    { loading: SkeletonLoaders.DataTable, ssr: false }
  ),

  // Workflow components
  PipelineVisualization: createLazyComponent(
    () => import('@/components/pipeline-visualization').then(m => ({ default: (m as any).default || m })),
    { loading: SkeletonLoaders.Chart, ssr: false }
  )
};

// Bundle splitting by route/feature
export const RouteComponents = {
  // Dashboard route components
  dashboard: {
    DashboardPage: createLazyComponent(
      () => Promise.resolve({ default: () => null }),
      { loading: SkeletonLoaders.Dashboard }
    )
  },

  // Charts route components  
  charts: {
    ChartsPage: createLazyComponent(
      () => Promise.resolve({ default: () => null }),
      { loading: SkeletonLoaders.Chart }
    )
  },

  // Knowledge graph route components
  knowledgeGraph: {
    KnowledgeGraphPage: createLazyComponent(
      () => Promise.resolve({ default: () => null }),
      { loading: SkeletonLoaders.KnowledgeGraph }
    )
  }
};

// Preloading utilities
export function preloadRouteComponent(route: keyof typeof RouteComponents): void {
  // Preload route-specific components
  const routeComponents = RouteComponents[route];
  if (routeComponents) {
    Object.values(routeComponents).forEach(component => {
      // Components are already lazy-loaded, this triggers the import
      if (typeof window !== 'undefined') {
        (component as any)?.preload?.();
      }
    });
  }
}

export function preloadCriticalImages(images: string[]): void {
  if (typeof window !== 'undefined') {
    ProgressiveImageLoader.preloadImages(images);
  }
}

export function preloadCriticalData(dataKeys: { key: string; fetcher: () => Promise<any> }[]): void {
  if (typeof window !== 'undefined') {
    dataKeys.forEach(({ key, fetcher }) => {
      LazyDataLoader.preload(key, fetcher);
    });
  }
}
