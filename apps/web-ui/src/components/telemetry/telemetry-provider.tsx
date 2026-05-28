/**
 * TelemetryProvider - React context provider for telemetry tracking
 * Part of TELEMETRY-003 Usage Metrics Tracking System
 */

'use client';

import React, { createContext, useContext, useCallback, useRef, useEffect, ReactNode } from 'react';
import { serviceEndpoints } from '@/lib/service-endpoints';

// Telemetry Types
export interface TelemetryEvent {
  eventType: string;
  service: 'web_ui' | 'agent' | 'kg' | 'orchestrator';
  featureName?: string;
  action?: string;
  userId?: string;
  sessionId?: string;
  context?: Record<string, any>;
  parameters?: Record<string, any>;
  metadata?: Record<string, any>;
  durationMs?: number;
  success?: boolean;
  errorMessage?: string;
  privacyLevel?: 'public' | 'aggregate_only' | 'internal_only' | 'restricted' | 'sensitive';
}

export interface TelemetryConfig {
  enabled: boolean;
  apiBaseUrl: string;
  batchSize: number;
  flushIntervalMs: number;
  maxRetries: number;
  debugMode: boolean;
  samplingRate: number;
}

export interface UsageMetric {
  id: string;
  metricType: string;
  name: string;
  value: number;
  unit: string;
  timestamp: string;
  periodStart: string;
  periodEnd: string;
  granularity: string;
  dimensions?: Record<string, any>;
  breakdown?: Record<string, number>;
}

export interface FeatureUsage {
  featureName: string;
  service: string;
  totalUses: number;
  uniqueUsers: number;
  successRate: number;
  avgDurationMs?: number;
  adoptionRate: number;
  retentionRate: number;
  frequency: number;
  trend: 'increasing' | 'decreasing' | 'stable';
  periodOverPeriodChange: number;
  peakUsageHour?: number;
  errorRate: number;
  avgResponseTimeMs?: number;
}

export interface TelemetryContextValue {
  // Configuration
  config: TelemetryConfig;
  
  // Core tracking methods
  track: (event: Partial<TelemetryEvent>) => Promise<void>;
  trackPageView: (pagePath: string, referrer?: string) => Promise<void>;
  trackFeatureUsage: (featureName: string, action: string, context?: Record<string, any>) => Promise<void>;
  trackUserInteraction: (component: string, action: string, metadata?: Record<string, any>) => Promise<void>;
  trackPerformance: (operationName: string, durationMs: number, success: boolean) => Promise<void>;
  trackError: (error: Error, context?: Record<string, any>) => Promise<void>;
  
  // Session management
  setUserId: (userId: string) => void;
  setSessionId: (sessionId: string) => void;
  clearUserContext: () => void;
  
  // Metrics retrieval
  getUsageMetrics: (params?: any) => Promise<UsageMetric[]>;
  getFeatureAnalysis: (params?: any) => Promise<FeatureUsage[]>;
  getRealTimeMetrics: () => Promise<any>;
  
  // Utilities
  flush: () => Promise<void>;
  isEnabled: () => boolean;
  getStats: () => any;
}

const defaultConfig: TelemetryConfig = {
  enabled: true,
  apiBaseUrl: '/api/telemetry',
  batchSize: 50,
  flushIntervalMs: 30000, // 30 seconds
  maxRetries: 3,
  debugMode: process.env.NODE_ENV === 'development',
  samplingRate: 1.0,
};

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

interface TelemetryProviderProps {
  children: ReactNode;
  config?: Partial<TelemetryConfig>;
}

class TelemetryClient {
  private config: TelemetryConfig;
  private eventQueue: TelemetryEvent[] = [];
  private flushTimer: NodeJS.Timeout | null = null;
  private userId: string | null = null;
  private sessionId: string | null = null;
  private stats = {
    eventsTracked: 0,
    eventsSent: 0,
    eventsDropped: 0,
    apiErrors: 0,
    lastFlush: null as Date | null,
  };

  constructor(config: TelemetryConfig) {
    this.config = config;
    this.initializeSession();
    this.startFlushTimer();
  }

  private initializeSession() {
    // Generate session ID if not provided
    if (!this.sessionId) {
      this.sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    // Load user ID from localStorage if available
    if (typeof window !== 'undefined') {
      const storedUserId = localStorage.getItem('br_user_id');
      if (storedUserId) {
        this.userId = storedUserId;
      }
    }
  }

  private startFlushTimer() {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
    }

    this.flushTimer = setInterval(() => {
      this.flush();
    }, this.config.flushIntervalMs);
  }

  setUserId(userId: string) {
    this.userId = userId;
    if (typeof window !== 'undefined') {
      localStorage.setItem('br_user_id', userId);
    }
  }

  setSessionId(sessionId: string) {
    this.sessionId = sessionId;
  }

  clearUserContext() {
    this.userId = null;
    this.sessionId = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('br_user_id');
    }
  }

  async track(event: Partial<TelemetryEvent>): Promise<void> {
    if (!this.config.enabled) {
      return;
    }

    // Apply sampling
    if (Math.random() > this.config.samplingRate) {
      this.stats.eventsDropped++;
      return;
    }

    const fullEvent: TelemetryEvent = {
      eventType: event.eventType || 'custom',
      service: 'web_ui',
      userId: this.userId || undefined,
      sessionId: this.sessionId || undefined,
      privacyLevel: 'aggregate_only',
      success: true,
      ...event,
    };

    this.eventQueue.push(fullEvent);
    this.stats.eventsTracked++;

    if (this.config.debugMode) {
      console.log('[Telemetry] Event tracked:', fullEvent);
    }

    // Flush immediately if queue is full
    if (this.eventQueue.length >= this.config.batchSize) {
      await this.flush();
    }
  }

  async trackPageView(pagePath: string, referrer?: string): Promise<void> {
    await this.track({
      eventType: 'page_view',
      featureName: 'page_view',
      action: 'view',
      context: {
        pagePath,
        referrer: referrer || document.referrer,
        userAgent: navigator.userAgent,
        timestamp: new Date().toISOString(),
      },
    });
  }

  async trackFeatureUsage(featureName: string, action: string, context?: Record<string, any>): Promise<void> {
    await this.track({
      eventType: 'feature_access',
      featureName,
      action,
      context,
    });
  }

  async trackUserInteraction(component: string, action: string, metadata?: Record<string, any>): Promise<void> {
    await this.track({
      eventType: 'feature_interaction',
      featureName: component,
      action,
      metadata,
    });
  }

  async trackPerformance(operationName: string, durationMs: number, success: boolean = true): Promise<void> {
    await this.track({
      eventType: 'feature_completion',
      featureName: 'performance',
      action: operationName,
      durationMs,
      success,
    });
  }

  async trackError(error: Error, context?: Record<string, any>): Promise<void> {
    await this.track({
      eventType: 'tool_error',
      featureName: 'error_tracking',
      action: 'error',
      errorMessage: error.message,
      success: false,
      context: {
        errorName: error.name,
        errorStack: error.stack?.substring(0, 500), // Limit stack trace length
        ...context,
      },
      privacyLevel: 'internal_only',
    });
  }

  async flush(): Promise<void> {
    if (this.eventQueue.length === 0) {
      return;
    }

    const events = [...this.eventQueue];
    this.eventQueue = [];

    try {
      const response = await fetch(`${this.config.apiBaseUrl}/events/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(events.map(event => ({
          event_type: event.eventType,
          service: event.service,
          feature_name: event.featureName,
          action: event.action,
          user_id: event.userId,
          session_id: event.sessionId,
          context: event.context,
          parameters: event.parameters,
          metadata: event.metadata,
          duration_ms: event.durationMs,
          success: event.success,
          error_message: event.errorMessage,
          privacy_level: event.privacyLevel,
        }))),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      this.stats.eventsSent += result.collected_count || 0;
      this.stats.eventsDropped += result.failed_count || 0;
      this.stats.lastFlush = new Date();

      if (this.config.debugMode) {
        console.log('[Telemetry] Batch sent:', result);
      }
    } catch (error) {
      this.stats.apiErrors++;
      
      // Re-queue events on failure (with limit to prevent memory leaks)
      if (this.eventQueue.length < this.config.batchSize * 2) {
        this.eventQueue.unshift(...events);
      } else {
        this.stats.eventsDropped += events.length;
      }

      if (this.config.debugMode) {
        console.error('[Telemetry] Failed to send batch:', error);
      }
    }
  }

  async getUsageMetrics(params: any = {}): Promise<UsageMetric[]> {
    try {
      const response = await fetch(`${this.config.apiBaseUrl}/metrics`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(params),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      return result.metrics || [];
    } catch (error) {
      console.error('[Telemetry] Failed to get usage metrics:', error);
      return [];
    }
  }

  async getFeatureAnalysis(params: any = {}): Promise<FeatureUsage[]> {
    try {
      const response = await fetch(`${this.config.apiBaseUrl}/features/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(params),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      return result.features || [];
    } catch (error) {
      console.error('[Telemetry] Failed to get feature analysis:', error);
      return [];
    }
  }

  async getRealTimeMetrics(): Promise<any> {
    try {
      const response = await fetch(`${this.config.apiBaseUrl}/realtime`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('[Telemetry] Failed to get real-time metrics:', error);
      return {};
    }
  }

  isEnabled(): boolean {
    return this.config.enabled;
  }

  getStats() {
    return { ...this.stats };
  }

  destroy() {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    this.flush(); // Final flush
  }
}

export const TelemetryProvider: React.FC<TelemetryProviderProps> = ({ 
  children, 
  config: userConfig = {} 
}) => {
  const config = { ...defaultConfig, ...userConfig };
  const clientRef = useRef<TelemetryClient | null>(null);

  // Initialize client
  if (!clientRef.current) {
    clientRef.current = new TelemetryClient(config);
  }

  const client = clientRef.current;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (clientRef.current) {
        clientRef.current.destroy();
      }
    };
  }, []);

  // Track page view on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      client.trackPageView(window.location.pathname, document.referrer);
    }
  }, [client]);

  const contextValue: TelemetryContextValue = {
    config,
    
    // Core tracking methods
    track: useCallback((event: Partial<TelemetryEvent>) => client.track(event), [client]),
    trackPageView: useCallback((pagePath: string, referrer?: string) => 
      client.trackPageView(pagePath, referrer), [client]),
    trackFeatureUsage: useCallback((featureName: string, action: string, context?: Record<string, any>) => 
      client.trackFeatureUsage(featureName, action, context), [client]),
    trackUserInteraction: useCallback((component: string, action: string, metadata?: Record<string, any>) => 
      client.trackUserInteraction(component, action, metadata), [client]),
    trackPerformance: useCallback((operationName: string, durationMs: number, success: boolean) => 
      client.trackPerformance(operationName, durationMs, success), [client]),
    trackError: useCallback((error: Error, context?: Record<string, any>) => 
      client.trackError(error, context), [client]),
    
    // Session management
    setUserId: useCallback((userId: string) => client.setUserId(userId), [client]),
    setSessionId: useCallback((sessionId: string) => client.setSessionId(sessionId), [client]),
    clearUserContext: useCallback(() => client.clearUserContext(), [client]),
    
    // Metrics retrieval
    getUsageMetrics: useCallback((params?: any) => client.getUsageMetrics(params), [client]),
    getFeatureAnalysis: useCallback((params?: any) => client.getFeatureAnalysis(params), [client]),
    getRealTimeMetrics: useCallback(() => client.getRealTimeMetrics(), [client]),
    
    // Utilities
    flush: useCallback(() => client.flush(), [client]),
    isEnabled: useCallback(() => client.isEnabled(), [client]),
    getStats: useCallback(() => client.getStats(), [client]),
  };

  return (
    <TelemetryContext.Provider value={contextValue}>
      {children}
    </TelemetryContext.Provider>
  );
};

export const useTelemetry = (): TelemetryContextValue => {
  const context = useContext(TelemetryContext);
  if (!context) {
    throw new Error('useTelemetry must be used within a TelemetryProvider');
  }
  return context;
};

// Hook for automatic component interaction tracking
export const useInteractionTracking = (componentName: string) => {
  const { trackUserInteraction } = useTelemetry();

  return useCallback((action: string, metadata?: Record<string, any>) => {
    trackUserInteraction(componentName, action, metadata);
  }, [componentName, trackUserInteraction]);
};

// Hook for performance tracking
export const usePerformanceTracking = () => {
  const { trackPerformance } = useTelemetry();

  return useCallback(<T extends (...args: any[]) => any>(
    operationName: string,
    operation: T
  ): T => {
    return ((...args: Parameters<T>) => {
      const startTime = performance.now();
      
      try {
        const result = operation(...args);
        
        // Handle promises
        if (result instanceof Promise) {
          return result
            .then((value) => {
              trackPerformance(operationName, performance.now() - startTime, true);
              return value;
            })
            .catch((error) => {
              trackPerformance(operationName, performance.now() - startTime, false);
              throw error;
            });
        } else {
          trackPerformance(operationName, performance.now() - startTime, true);
          return result;
        }
      } catch (error) {
        trackPerformance(operationName, performance.now() - startTime, false);
        throw error;
      }
    }) as T;
  }, [trackPerformance]);
};

// Hook for error boundary integration
export const useErrorTracking = () => {
  const { trackError } = useTelemetry();
  
  return useCallback((error: Error, errorInfo?: Record<string, any>) => {
    trackError(error, errorInfo);
  }, [trackError]);
};

export default TelemetryProvider;
