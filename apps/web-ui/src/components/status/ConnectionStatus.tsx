/**
 * Real-time connection status component with service monitoring,
 * automatic reconnection UI, and offline mode indication.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Wifi, 
  WifiOff, 
  RefreshCw, 
  AlertCircle, 
  CheckCircle, 
  Clock,
  Settings,
  ChevronDown,
  ChevronUp,
  Activity
} from 'lucide-react';
import { resolveAgentHealthUrl, resolveKgHealthUrl } from '@/lib/service-endpoints';

interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unavailable';
  latency?: number;
  lastCheck?: Date;
  error?: string;
  url?: string;
}

interface ConnectionState {
  online: boolean;
  services: Record<string, ServiceStatus>;
  failureCounts: Record<string, number>;
  lastUpdate: Date;
  reconnecting: boolean;
  retryCount: number;
}

interface ConnectionStatusProps {
  className?: string;
  showDetails?: boolean;
  autoReconnect?: boolean;
  checkInterval?: number;
  services?: string[];
  onStatusChange?: (status: ConnectionState) => void;
}

const DEFAULT_SERVICE_NAMES = ['agent', 'kg'] as const;

const DEFAULT_SERVICES = [
  { name: 'agent', url: resolveAgentHealthUrl() },
  { name: 'kg', url: resolveKgHealthUrl() },
];
const SERVICE_LABELS: Record<string, string> = {
  agent: 'Agent',
  kg: 'BR-KG',
};
const HARD_FAILURE_THRESHOLD = 2;

const normalizeServiceStatus = (value: unknown): ServiceStatus['status'] | null => {
  if (typeof value !== 'string') return null;

  const normalized = value.toLowerCase();
  if (normalized === 'healthy' || normalized === 'ok' || normalized === 'up' || normalized === 'pass') {
    return 'healthy';
  }
  if (normalized === 'degraded' || normalized === 'warn' || normalized === 'warning') {
    return 'degraded';
  }
  if (normalized === 'unhealthy' || normalized === 'error' || normalized === 'down' || normalized === 'failed' || normalized === 'fail') {
    return 'unhealthy';
  }
  if (normalized === 'unavailable') {
    return 'unavailable';
  }
  return null;
};

export function ConnectionStatus({
  className = '',
  showDetails = false,
  autoReconnect = true,
  checkInterval = 30000,
  services,
  onStatusChange
}: ConnectionStatusProps) {
  const monitoredServices = useMemo(
    () => (services && services.length > 0 ? services : [...DEFAULT_SERVICE_NAMES]),
    [services]
  );

  const [state, setState] = useState<ConnectionState>({
    online: typeof navigator !== 'undefined' ? navigator.onLine : true,
    services: {},
    failureCounts: {},
    lastUpdate: new Date(),
    reconnecting: false,
    retryCount: 0
  });

  const [expanded, setExpanded] = useState(false);
  const [lastOfflineTime, setLastOfflineTime] = useState<Date | null>(null);

  // Service health check function
  const checkServiceHealth = useCallback(async (serviceName: string, url: string): Promise<ServiceStatus> => {
    const startTime = Date.now();
    
    try {
      const response = await fetch(url, {
        method: 'GET',
        signal: AbortSignal.timeout(10000)
      });
      
      const latency = Date.now() - startTime;
      const data = await response.json();
      
      let status: ServiceStatus['status'] = 'healthy';
      
      if (!response.ok) {
        status = response.status >= 500 ? 'unhealthy' : 'degraded';
      } else if (data.status) {
        status = normalizeServiceStatus(data.status) ?? 'healthy';
      } else if (typeof data.ok === 'boolean') {
        status = data.ok ? 'healthy' : 'unhealthy';
      } else if (latency > 5000) {
        status = 'degraded';
      }
      
      return {
        name: serviceName,
        status,
        latency,
        lastCheck: new Date(),
        url
      };
      
    } catch (error) {
      return {
        name: serviceName,
        status: 'unavailable',
        lastCheck: new Date(),
        error: error instanceof Error ? error.message : 'Unknown error',
        url
      };
    }
  }, []);

  // Check all services
  const checkAllServices = useCallback(async (): Promise<Record<string, ServiceStatus>> => {
    const serviceChecks = monitoredServices.map(serviceName => {
      const serviceConfig = DEFAULT_SERVICES.find(s => s.name === serviceName);
      if (!serviceConfig) return null;
      
      return { serviceName, check: checkServiceHealth(serviceName, serviceConfig.url) };
    }).filter(Boolean) as Array<{ serviceName: string; check: Promise<ServiceStatus> }>;
    
    try {
      const results = await Promise.allSettled(serviceChecks.map(item => item.check));
      const serviceStatuses: Record<string, ServiceStatus> = {};
      
      results.forEach((result, index) => {
        const serviceName = serviceChecks[index]?.serviceName || monitoredServices[index];
        if (result.status === 'fulfilled') {
          serviceStatuses[serviceName] = result.value;
        } else {
          serviceStatuses[serviceName] = {
            name: serviceName,
            status: 'unavailable',
            lastCheck: new Date(),
            error: 'Health check failed'
          };
        }
      });
      
      return serviceStatuses;
    } catch (error) {
      console.error('Failed to check service health:', error);
      return {};
    }
  }, [monitoredServices, checkServiceHealth]);

  // Handle online/offline events
  useEffect(() => {
    if (typeof window === 'undefined' || typeof navigator === 'undefined') return;

    setState(prev => ({
      ...prev,
      online: navigator.onLine
    }));

    const handleOnline = () => {
      setState(prev => ({ 
        ...prev, 
        online: true, 
        reconnecting: false,
        failureCounts: {},
        retryCount: 0
      }));
      setLastOfflineTime(null);
    };

    const handleOffline = () => {
      setState(prev => ({ 
        ...prev, 
        online: false, 
        reconnecting: false 
      }));
      setLastOfflineTime(new Date());
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Service health monitoring
  useEffect(() => {
    if (!state.online) return;

    const runHealthCheck = async () => {
      const serviceStatuses = await checkAllServices();
      
      setState(prev => {
        if (Object.keys(serviceStatuses).length === 0) {
          const unchangedState = {
            ...prev,
            lastUpdate: new Date(),
            reconnecting: false,
          };
          if (onStatusChange) onStatusChange(unchangedState);
          return unchangedState;
        }

        const nextFailureCounts = { ...prev.failureCounts };
        const adjustedServices: Record<string, ServiceStatus> = {};
        Object.entries(serviceStatuses).forEach(([serviceName, serviceStatus]) => {
          const isHardFailure =
            serviceStatus.status === 'unavailable' || serviceStatus.status === 'unhealthy';
          const previousCount = prev.failureCounts[serviceName] || 0;
          const nextCount = isHardFailure ? previousCount + 1 : 0;
          nextFailureCounts[serviceName] = nextCount;

          if (isHardFailure && nextCount < HARD_FAILURE_THRESHOLD) {
            adjustedServices[serviceName] = {
              ...serviceStatus,
              status: 'degraded',
            };
            return;
          }

          adjustedServices[serviceName] = serviceStatus;
        });

        const newState = {
          ...prev,
          services: adjustedServices,
          failureCounts: nextFailureCounts,
          lastUpdate: new Date(),
          reconnecting: false
        };
        
        // Notify parent of status change
        if (onStatusChange) {
          onStatusChange(newState);
        }
        
        return newState;
      });
    };

    // Initial check
    runHealthCheck();

    // Set up interval
    const interval = setInterval(runHealthCheck, checkInterval);

    return () => clearInterval(interval);
  }, [state.online, checkAllServices, checkInterval, onStatusChange]);

  // Auto-reconnect logic
  useEffect(() => {
    if (!autoReconnect || state.online || state.reconnecting) return;

    const attemptReconnect = async () => {
      setState(prev => ({ ...prev, reconnecting: true }));
      
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        await fetch('/api/health', {
          method: 'HEAD',
          cache: 'no-store',
          signal: controller.signal,
        });
        clearTimeout(timeout);
        
        // If successful, update state
        setState(prev => ({ 
          ...prev, 
          online: true, 
          reconnecting: false,
          failureCounts: {},
          retryCount: 0
        }));
        setLastOfflineTime(null);
      } catch {
        setState(prev => ({ 
          ...prev, 
          reconnecting: false,
          retryCount: prev.retryCount + 1
        }));
      }
    };

    // Exponential backoff with jitter
    const backoffDelay = Math.min(1000 * Math.pow(2, state.retryCount), 30000);
    const jitter = Math.random() * 1000;
    const timeout = setTimeout(attemptReconnect, backoffDelay + jitter);

    return () => clearTimeout(timeout);
  }, [state.online, state.reconnecting, state.retryCount, autoReconnect]);

  // Manual reconnect
  const handleManualReconnect = useCallback(async () => {
    setState(prev => ({ ...prev, reconnecting: true }));
    
    try {
      const serviceStatuses = await checkAllServices();
      
      setState(prev => ({
        ...prev,
        services: serviceStatuses,
        failureCounts: {},
        lastUpdate: new Date(),
        reconnecting: false,
        retryCount: 0
      }));
    } catch {
      setState(prev => ({ 
        ...prev, 
        reconnecting: false 
      }));
    }
  }, [checkAllServices]);

  // Compute overall status
  const overallStatus = useMemo(() => {
    if (!state.online) return 'offline';
    
    const serviceStatuses = Object.values(state.services);
    if (serviceStatuses.length === 0) return 'unknown';
    
    const unhealthyCount = serviceStatuses.filter(s => 
      s.status === 'unhealthy' || s.status === 'unavailable'
    ).length;
    
    const degradedCount = serviceStatuses.filter(s => s.status === 'degraded').length;
    
    if (unhealthyCount > 0) return 'unhealthy';
    if (degradedCount > 0) return 'degraded';
    return 'healthy';
  }, [state.online, state.services]);

  // Get status color and icon
  const getStatusInfo = (status: string) => {
    switch (status) {
      case 'healthy':
        return {
          color: 'text-green-600',
          bg: 'bg-green-100',
          icon: CheckCircle,
          label: 'All systems operational'
        };
      case 'degraded':
        return {
          color: 'text-yellow-600',
          bg: 'bg-yellow-100',
          icon: AlertCircle,
          label: 'Some services degraded'
        };
      case 'unhealthy':
        return {
          color: 'text-red-600',
          bg: 'bg-red-100',
          icon: AlertCircle,
          label: 'Service issues detected'
        };
      case 'offline':
        return {
          color: 'text-gray-600',
          bg: 'bg-gray-100',
          icon: WifiOff,
          label: 'No internet connection'
        };
      default:
        return {
          color: 'text-gray-600',
          bg: 'bg-gray-100',
          icon: Clock,
          label: 'Checking connection...'
        };
    }
  };

  const statusInfo = getStatusInfo(overallStatus);
  const StatusIcon = statusInfo.icon;

  return (
    <div className={`relative ${className}`}>
      {/* Main status indicator */}
      <div
        className={`flex items-center px-3 py-2 rounded-md cursor-pointer transition-colors ${statusInfo.bg} hover:opacity-80`}
        onClick={() => setExpanded(!expanded)}
      >
        <StatusIcon className={`h-4 w-4 ${statusInfo.color} mr-2`} />
        
        <span className={`text-sm font-medium ${statusInfo.color} whitespace-nowrap truncate`}>
          {statusInfo.label}
        </span>
        
        {state.reconnecting && (
          <RefreshCw className="h-3 w-3 ml-2 animate-spin text-blue-500" />
        )}
        
        {showDetails && (
          <div className="ml-2">
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-gray-500" />
            ) : (
              <ChevronDown className="h-4 w-4 text-gray-500" />
            )}
          </div>
        )}
      </div>

      {/* Expanded details */}
      {expanded && showDetails && (
        <div className="absolute top-full left-0 mt-2 w-80 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
          <div className="p-4">
            {/* Overall status */}
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">System Status</h3>
              <button
                onClick={handleManualReconnect}
                disabled={state.reconnecting}
                className="inline-flex items-center px-3 py-1 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw className={`h-3 w-3 mr-1 ${state.reconnecting ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>

            {/* Connection info */}
            <div className="mb-4 p-3 bg-gray-50 rounded-md">
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <Wifi className="h-4 w-4 text-gray-600 mr-2" />
                  <span className="text-sm font-medium text-gray-900">
                    Internet Connection
                  </span>
                </div>
                <span className={`text-sm font-medium ${state.online ? 'text-green-600' : 'text-red-600'}`}>
                  {state.online ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              
              {!state.online && lastOfflineTime && (
                <p className="text-xs text-gray-600 mt-1">
                  Offline since {lastOfflineTime.toLocaleTimeString()}
                </p>
              )}
            </div>

            {/* Service statuses */}
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-gray-900 mb-2">Services</h4>
              
              {Object.values(state.services).map(service => {
                const serviceStatusInfo = getStatusInfo(service.status);
                const ServiceStatusIcon = serviceStatusInfo.icon;
                
                return (
                  <div key={service.name} className="flex items-center justify-between py-2">
                    <div className="flex items-center">
                      <ServiceStatusIcon className={`h-3 w-3 ${serviceStatusInfo.color} mr-2`} />
                      <span className="text-sm text-gray-900">
                        {SERVICE_LABELS[service.name] ?? service.name}
                      </span>
                    </div>
                    
                    <div className="flex items-center text-xs text-gray-600">
                      {service.latency && (
                        <span className="mr-2">{service.latency}ms</span>
                      )}
                      <span className={`px-2 py-1 rounded-full ${serviceStatusInfo.bg} ${serviceStatusInfo.color}`}>
                        {service.status}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Last update time */}
            <div className="mt-4 pt-3 border-t border-gray-200">
              <p className="text-xs text-gray-500">
                Last updated: {state.lastUpdate.toLocaleTimeString()}
              </p>
              
              {state.retryCount > 0 && (
                <p className="text-xs text-gray-500">
                  Retry attempts: {state.retryCount}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Hook for accessing connection status in other components
export function useConnectionStatus() {
  const [connectionState, setConnectionState] = useState<ConnectionState>({
    online: navigator.onLine,
    services: {},
    failureCounts: {},
    lastUpdate: new Date(),
    reconnecting: false,
    retryCount: 0
  });

  const updateStatus = useCallback((newState: ConnectionState) => {
    setConnectionState(newState);
  }, []);

  return {
    ...connectionState,
    updateStatus
  };
}

// Simple status indicator component
export function SimpleConnectionIndicator({ className = '' }: { className?: string }) {
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return (
    <div className={`flex items-center ${className}`}>
      {online ? (
        <div className="flex items-center text-green-600">
          <div className="h-2 w-2 bg-green-500 rounded-full mr-2" />
          <span className="text-xs">Online</span>
        </div>
      ) : (
        <div className="flex items-center text-red-600">
          <div className="h-2 w-2 bg-red-500 rounded-full mr-2" />
          <span className="text-xs">Offline</span>
        </div>
      )}
    </div>
  );
}

export default ConnectionStatus;
